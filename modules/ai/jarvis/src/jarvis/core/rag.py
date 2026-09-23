"""RAG híbrido  espelho do `codebase_indexer` V4.0.5 do legado sobre Qdrant.

Porta do algoritmo legado (Manjaro/AI_SYSTEM/core/codebase_indexer.py V4.0.5):

- `extract_facts`: mesmas regex por extensão (fn:/ent:) e STOP_SYMBOLS.
- `build_rich_content`: mesmo formato embebido pelo legado
  (`[PATH: ...]\\n[FACTS: ...]\\n{content[:5000]}`).
- Indexação: dense (embedding via llama.cpp `--embeddings`) + sparse BM25
  (termos do rich_content) + payload (path/facts/symbols/filename/content).
- Busca: prefetch dense + sparse com fusão RRF (nativa do Qdrant) e, em
  seguida, re-rank com os boosts do V4.0.5 (filename sovereignty, palavra no
  filename/path, símbolos na query)  preservando o comportamento do legado.

Sem acoplamento a caminhos hardcoded: tudo via Config/adapters.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from jarvis.core.config import Config
from jarvis.providers.llm import LLMClient
from jarvis.providers.vector_store import QdrantStore, dense_key, stable_id

# ---------------------------------------------------------------------------
# .ragignore — sintaxe gitignore (padrão de mercado: mesma engine do .gitignore,
# via pathspec quando disponível; fallback embutido com subconjunto da spec).
# Descoberta na raiz do tree indexado; `!` re-inclui; último match vence.
# ---------------------------------------------------------------------------
_RAGIGNORE_NAME = ".ragignore"


def _load_ragignore(root: Path) -> "object | None":
    """Carrega o .ragignore da raiz. Retorna spec (pathspec) ou matcher fallback."""
    ignore_file = root / _RAGIGNORE_NAME
    if not ignore_file.is_file():
        return None
    try:
        lines = ignore_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return None
    patterns = [ln for ln in (l.strip() for l in lines) if ln and not ln.startswith("#")]
    if not patterns:
        return None
    try:
        import pathspec  # lib-canônica de gitignore (black/ruff); opcional
        return pathspec.PathSpec.from_lines("gitwildmatch", patterns)
    except ImportError:
        return _SimpleIgnoreMatcher(patterns)


def _ragignore_rejects(matcher: "object | None", rel: str) -> bool:
    """True se `rel` (caminho relativo à raiz, POSIX) deve ser ignorado.
    pathspec ≥1.1: check_file().include é 'casou regra POSITIVA?' (última
    regra vence) — na semântica gitignore, positivo = IGNORAR; negação (!)
    devolve False (manter); None = sem match (manter)."""
    if matcher is None:
        return False
    chk = getattr(matcher, "check_file", None)
    if chk is not None:
        return chk(rel).include is True
    m = getattr(matcher, "match_file", None)
    if m is None:
        return False
    return bool(m(rel))


class _SimpleIgnoreMatcher:
    """Fallback SEM deps: subconjunto gitignore — `*`, `?`, `**`, classes [abc],
    âncora `/` inicial, trailing `/` (só dir), `!` negação; último match vence.
    Implementado por tradução p/ regex (o mesmo desenho do gitignore real)."""

    _GLOB_RE = {"**": ".*", "*": "[^/]*", "?": "[^/]"}

    def __init__(self, patterns: list[str]):
        # (neg, rx, dir_only, base_literal) — base_literal p/ semântica de
        # dir-only: "x/" casa o dir (com "/") e TUDO sob ele, nunca um
        # ARQUIVO de nome "x" (spec gitignore).
        self._rules: list[tuple[bool, re.Pattern[str], bool, str]] = []
        for pat in patterns:
            neg = pat.startswith("!")
            if neg:
                pat = pat[1:]
            dir_only = pat.endswith("/")
            if dir_only:
                pat = pat.rstrip("/")
            # Spec gitignore: separador no INÍCIO ou MEIO ancora na raiz;
            # no FIM não ("anchors-v2/" segue casando em qualquer nível).
            anchored = pat.startswith("/") or "/" in pat
            if anchored:
                pat = pat.lstrip("/")
            if pat.startswith("**/"):
                anchored = False  # "**/x" ≡ "x" (explícito any-depth)
            rx = ""
            i = 0
            while i < len(pat):
                ch = pat[i]
                if ch == "*":
                    if pat[i:i+2] == "**":
                        rx += self._GLOB_RE["**"]
                        i += 2
                        # "a/**/b" também casa "a/b" (spec gitignore)
                        if pat[i:i+1] == "/":
                            rx += "[/]?"
                            i += 1  # separador já emitido como opcional
                        continue
                    rx += self._GLOB_RE["*"]
                elif ch == "?":
                    rx += self._GLOB_RE["?"]
                elif ch == "[":
                    j = pat.find("]", i + 1)
                    if j == -1:
                        rx += re.escape(ch)
                    else:
                        cls = pat[i:j+1]  # "[abc]" / "[!abc]" / "[a-z]"
                        if cls[1] == "!":
                            cls = "[^" + cls[2:]
                        rx += cls
                        i = j
                else:
                    rx += re.escape(ch)
                i += 1
            if dir_only:
                rx += "(/.*)?$"
            elif anchored:
                rx = "^" + rx + "(/.*)?$"
            else:
                rx = "(^|/)" + rx + "(/.*)?$"
            self._rules.append((neg, re.compile(rx), dir_only, pat))

    def match_file(self, rel: str) -> bool:
        # search (não match): padrões não-ancorados casam em QUALQUER nível
        # ("personagens/" pega "deep/nested/personagens/" — spec gitignore);
        # padrões ancorados já carregam ^...$ na própria regex.
        ignored = False
        for neg, rx, dir_only, base in self._rules:
            if dir_only and not rel.endswith("/") and not rel.startswith(base + "/"):
                continue  # padrão "x/" não ignora um arquivo chamado "x"
            if rx.search(rel):
                ignored = not neg
        return ignored

# ---------------------------------------------------------------------------
# Porta do V4.0.5  padrões de símbolos por extensão
# ---------------------------------------------------------------------------

_PATTERNS: dict[str, dict[str, str | None]] = {
    ".py": {"func": r"def\s+([a-zA-Z_][a-zA-Z0-9_]*)", "class": r"class\s+([a-zA-Z_][a-zA-Z0-9_]*)"},
    ".cpp": {"func": r"([a-zA-Z0-9_:]+)\s*\(", "class": r"(?:class|struct|namespace)\s+([a-zA-Z_][a-zA-Z0-9_]*)"},
    ".h": {"func": r"([a-zA-Z0-9_:]+)\s*\(", "class": r"(?:class|struct)\s+([a-zA-Z_][a-zA-Z0-9_]*)"},
    ".hpp": {"func": r"([a-zA-Z0-9_:]+)\s*\(", "class": r"(?:class|struct)\s+([a-zA-Z_][a-zA-Z0-9_]*)"},
    ".pb.h": {"func": r"void\s+(set_[a-zA-Z0-9_]+)\s*\(", "class": r"class\s+([a-zA-Z0-9_]+)"},
    ".rive": {"func": r"^\+\s*([^[\n\r]*)", "class": None},
    ".lua": {"func": r"(?:function\s+([a-zA-Z0-9_:.]+)|([a-zA-Z0-9_.]+)\s*=\s*function)\s*\(", "class": None},
    ".proto": {"func": r"(?:message|enum)\s+([a-zA-Z0-9_]+)", "class": r"\s+\w+\s+([a-zA-Z0-9_]+)\s*="},
    # NixOS: atributos de config (`services.x.y = ...;`) e options (mkOption/mkEnableOption)
    ".nix": {
        "func": r"([a-zA-Z0-9_.-]+)\s*=\s*[^;{}]*?(?:;|\{)",
        "class": r"(?:mkOption|mkEnableOption|mkIf|mkForce|mkDefault)\b",
    },
}

_STOP_SYMBOLS: frozenset[str] = frozenset({
    "if", "for", "the", "and", "then", "else", "local", "function", "return",
    "true", "false", "nil", "null", "message", "enum", "class", "struct",
})

# Config de varredura (Código-fonte & Scripting)
_ALLOWED_EXTENSIONS: tuple[str, ...] = (
    # Python, Shell & NixOS / Linux Config
    ".py", ".sh", ".bash", ".zsh", ".fish", ".nix", ".service", ".timer", ".conf",

    # C / C++ / C# / Rust / Go / Zig
    ".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx", ".inl", ".pb.h", ".pb.cc",
    ".rs", ".go", ".zig", ".cs",

    # Scripts de Jogos / Legado OTServer
    ".lua", ".rive", ".proto",

    # Web & Linguagens Gerais
    ".js", ".jsx", ".ts", ".tsx", ".vue", ".svelte", ".astro", ".html", ".css", ".scss",
    ".java", ".kt", ".kts", ".rb", ".php", ".ex", ".exs", ".erl", ".sql",

    # Texto Pleno
    ".txt",

    # Documentos sanitizados pré-RAG (doc_sanitize: extract→normalize→
    # validate; quarentena em vez de lixo no Qdrant)
    ".pdf", ".epub", ".htm",
)

# Metadados, Documentação & Configurações Estruturadas
_METADATA_EXTENSIONS: tuple[str, ...] = (
    ".md", ".markdown", ".json", ".jsonc", ".json5", ".yaml", ".yml",
    ".toml", ".ini", ".env.example", ".xml", ".kdl", ".ron", ".csv",
)

_EXCLUDE_DIRS: tuple[str, ...] = (
    # VCS & IDEs
    "git", "idea", "vscode", "file-history", "claude", "fleet", "zed",

    # Caches Gerais & Sistema
    "cache", "tmp", "trash", "appcache", "gpu_cache", "code_cache", "local", "config",

    # Python & Testes / Cobertura
    "pycache", "pytest_cache", "mypy_cache", "ruff_cache", "tox",
    "coverage", "htmlcov", "nyc_output", "ipynb_checkpoints",

    # JavaScript / Node / Frontend
    "node_modules", "npm", "pnpm-store", "pnpm", "yarn", "next", "nuxt",
    "svelte-kit", "astro",

    # C/C++, Rust, Go, Zig
    "cmake", "cmakefiles", "build", "vcpkg", "cargo", "rustup", "target",
    "clangd", "ccls-cache", "zig-cache", "zig-out", "go-build",

    # Java, .NET, PHP, Dart/Flutter
    "gradle", "m2", "nuget", "pub-cache", "dart_tool", "vendor", "composer",

    # Binários, Builds & Caches de Executáveis
    "bin", "obj", "dist", "site-packages", "venv", "env",

    # Engines de Jogos & Mobile (Unity, Unreal, Godot, Android, iOS)
    "godot", "import", "library", "intermediate", "deriveddatacache",
    "saved", "android", "ios",

    # DevOps, Nuvem & Containers
    "terraform", "terragrunt-cache", "serverless", "aws-sam", "vagrant",

    # Vetores & Caches de RAG/IA
    "chroma", "qdrant", "lancedb", "faiss", "ollama", "huggingface",

    # Dados Específicos/Legados OTServer/Tibia
    "clientdata", "monster", "world", "items", "npc", "fresh", "backup",
)

_MAX_FILE_SIZE_KB = 2000
_STORED_CONTENT_CHARS = 30000


def extract_facts(content: str, ext: str) -> list[str]:
    """Extrai fatos (fn:/ent:) de um arquivo  porta fiel do V4.0.5."""
    matched_ext = next((k for k in _PATTERNS if ext.endswith(k)), None)
    if matched_ext is None:
        return []
    patterns = _PATTERNS[matched_ext]

    facts: list[str] = []
    try:
        for kind, raw in (("fn", patterns["func"]), ("ent", patterns["class"])):
            if not raw:
                continue
            for m in re.findall(raw, content, re.MULTILINE):
                val = m if isinstance(m, str) else next((x for x in m if x), "")
                if val and val.lower() not in _STOP_SYMBOLS and len(val) >= 4:
                    facts.append(f"{kind}: {val}")
    except re.error:
        pass
    return list(set(facts))[:200]


def get_symbol_block(content: str, symbol_name: str) -> str | None:
    """Extrai o bloco de código onde o símbolo está definido (porta V4.0.5)."""
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if symbol_name in line and any(
            kw in line for kw in ("message", "class", "struct", "enum", "function", "def ", "void set_")
        ):
            start_line = i
            block: list[str] = []
            brace_count = 0
            found_start = False
            for j in range(i, min(i + 200, len(lines))):
                curr_line = lines[j]
                block.append(curr_line)
                if "{" in curr_line:
                    brace_count += curr_line.count("{")
                    found_start = True
                if "}" in curr_line:
                    brace_count -= curr_line.count("}")
                if found_start and brace_count == 0:
                    return "\n".join(block)
            return "\n".join(lines[start_line : start_line + 30])
    return None


def build_rich_content(
    path: str,
    facts: Iterable[str],
    content: str,
    *,
    max_chars: int = 3000,
) -> str:
    """Mesmo formato do texto embebido pelo legado V4.0.5.

    `max_chars` limita o conteúdo para caber no contexto do modelo de
    embedding (nomic-embed-text-v2-moe tem ctx 2048; 3000 chars  1450
    tokens). O legado usava 5000 chars com um modelo de ctx maior.
    """
    facts_str = ", ".join(facts)
    return f"[PATH: {path}]\n[FACTS: {facts_str}]\n{content[:max_chars]}"


# ---------------------------------------------------------------------------
# Sparse BM25 (termos)  alimenta o sparse vector do Qdrant
# ---------------------------------------------------------------------------

_SPARSE_MIN_LEN = 2
_SPARSE_STOPWORDS: frozenset[str] = frozenset({
    "the", "and", "for", "are", "was", "with", "from", "this", "that",
    "def", "class", "return", "import", "none", "true", "false", "nil",
})


def sparse_terms(text: str) -> dict[str, float]:
    """Tokeniza texto em {termo: frequência} para o sparse vector BM25.

    Suporta caracteres acentuados (PT-BR: c, a, e, etc.) via w+ do regex.
    """
    counts: dict[str, float] = {}
    for token in re.findall(r"[\w]+", text.lower()):
        if len(token) < _SPARSE_MIN_LEN or token in _SPARSE_STOPWORDS:
            continue
        counts[token] = counts.get(token, 0.0) + 1.0
    return counts


def sparse_vector(terms: dict[str, float]) -> dict[str, list[int | float]]:
    """Converte {termo: peso} em {indices, values} (crc32 determinístico)."""
    ordered = sorted(terms.items())
    return {
        "indices": [dense_key(term) for term, _ in ordered],
        "values": [weight for _, weight in ordered],
    }


# ---------------------------------------------------------------------------
# Boosts do V4.0.5 (re-rank pós-fusão)  espelho fiel
# ---------------------------------------------------------------------------

_FILENAME_SOVEREIGNTY = 100000.0
_WORD_IN_FILENAME = 2.0
_WORD_IN_PATH = 0.5
# Penalidade estrutural: testes e scripts de apoio raramente são a resposta
_TEST_PATH_PENALTY = 2.0
_SCRIPT_PATH_PENALTY = 1.0
# Fusão RRF (Reciprocal Rank Fusion)
_RERANK_K = 60
# Desempate de empates exatos do RRF pela posição do híbrido+boost (1e-6/(i+1))
_RERANK_TIEBREAK = 1e-6


@dataclass
class HybridHit:
    """Um resultado da busca híbrida, com score final já re-rankeado."""

    path: str
    score: float
    payload: dict[str, Any] = field(default_factory=dict)


def _target_extension(query: str) -> str | None:
    m = re.search(r"\.([a-zA-Z][a-zA-Z0-9]{0,3})\b", query)
    return "." + m.group(1).lower() if m else None


def apply_legacy_boosts(
    query: str,
    hits: Sequence[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Aplica os boosts do V4.0.5 sobre resultados crus da fusão."""
    query_l = query.lower()
    target_ext = _target_extension(query)
    query_words = {w for w in re.findall(r"\w+", query_l) if len(w) > 3}

    scored: list[dict[str, Any]] = []
    for raw_hit in hits:
        hit = dict(raw_hit)
        payload = hit.get("payload", {})
        path = str(payload.get("path", "")).lower()
        filename = os.path.basename(path).lower()

        if target_ext and not path.endswith(target_ext):
            continue

        score = float(hit.get("score", 0.0))
        stem = filename.split(".")[0]

        if filename in query_l or (len(stem) >= 8 and stem in query_l):
            score += _FILENAME_SOVEREIGNTY
        for word in query_words:
            if word in filename:
                score += _WORD_IN_FILENAME
            elif word in path:
                score += _WORD_IN_PATH

        if "/tests/" in path or filename.startswith("test_"):
            score -= _TEST_PATH_PENALTY
        elif path.endswith(".sh"):
            score -= _SCRIPT_PATH_PENALTY

        hit["score"] = score
        scored.append(hit)

    scored.sort(key=lambda h: h["score"], reverse=True)
    return scored


# ---------------------------------------------------------------------------
# Indexador híbrido
# ---------------------------------------------------------------------------

def _is_allowed(root: str, file: str) -> bool:
    ext = os.path.splitext(file)[1].lower()
    if ext in _ALLOWED_EXTENSIONS:
        return True
    if ext in _METADATA_EXTENSIONS:
        # .md/.json/.yaml em TODO lugar (dono 16/09: docs são o mapa;
        # gate antigo escondia AGENTS/SESSAO/audits do RAG)
        return True
    return False


def iter_indexable_files(root: str | Path, exclude_dirs: Iterable[str] | None = None) -> Iterable[str]:
    """Varre um diretório/arquivo com as mesmas regras do V4.0.5 (excludes, tamanho).
    Respeita também um .ragignore na raiz (sintaxe gitignore; ver _load_ragignore)."""
    excludes = tuple(e.lower() for e in (exclude_dirs if exclude_dirs is not None else _EXCLUDE_DIRS))
    root_path = Path(root).expanduser()
    rag = _load_ragignore(root_path)

    if root_path.is_file():
        if _is_allowed(str(root_path.parent), root_path.name):
            try:
                if root_path.stat().st_size <= _MAX_FILE_SIZE_KB * 1024:
                    yield str(root_path)
            except OSError:
                pass
        return

    for dirpath, dirnames, filenames in os.walk(root_path):
        # Filtra os subdiretórios verificando o nome do diretório individual, não o caminho absoluto
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".")
            and d.lower() not in excludes
            and not any(ex in d.lower() for ex in excludes)
        ]
        if rag is not None:
            # Poda dir inteiro se o rel-path casa com padrão de ignore (mesma
            # regra do git: dir excluído não é nem descido; `!` não resgata).
            # Trailing "/" = contexto de diretório (dir-only patterns).
            dirnames[:] = [
                d for d in dirnames
                if not _ragignore_rejects(rag, os.path.relpath(os.path.join(dirpath, d), root_path).replace(os.sep, "/") + "/")
            ]

        for file in filenames:
            if file.startswith("."):
                continue
            if rag is not None and _ragignore_rejects(
                    rag, os.path.relpath(os.path.join(dirpath, file), root_path).replace(os.sep, "/")):
                continue
            if _is_allowed(dirpath, file):
                path = Path(dirpath) / file
                try:
                    if path.stat().st_size <= _MAX_FILE_SIZE_KB * 1024:
                        yield str(path)
                except OSError:
                    continue

class HybridIndexer:
    """Indexa arquivos de código no Qdrant (dense + sparse BM25 + payload)."""

    def __init__(self, config: Config | None = None) -> None:
        self._cfg = config or Config()
        self._store = QdrantStore(self._cfg)
        self._llm = LLMClient(self._cfg)
        self._indexed_hashes: dict[str, float] = {}  # path → mtime (cache de indexação)

    def ensure_collection(self) -> None:
        self._store.ensure_collection(self._cfg.qdrant_collection_code, dim=self._cfg.embed_dim)

    def index_file(self, path: str, *, content: str | None = None, force: bool = False) -> dict[str, Any] | None:
        """Indexa um arquivo com chunking para respeitar o limite de contexto.

        Pula arquivos que não mudaram desde a última indexação (por mtime).
        Use force=True para re-indexar mesmo sem mudanças.

        Sanitização pré-RAG (doc_sanitize): quando o conteúdo vem do disco,
        passa por detect→extract→normalize→validate ANTES do chunking.
        Quarentena (malformado/corrompido/não-suportado) NÃO é indexada —
        retorna None (mesmo contrato de "pular"), com manifest gravado.
        """
        ext = os.path.splitext(path)[1].lower()
        # Código-fonte: leitura DIRETA preservando whitespace (indentação é
        # semântica em Python/YAML). normalize_text colapsaria espaços →
        # corromperia código. Sanitizer de DOCUMENTOS não se aplica aqui;
        # proveniência marca o caminho (code-direct-read).
        CODE_EXTS = {".py", ".sh", ".nix", ".toml", ".yaml", ".yml", ".js",
                     ".ts", ".tsx", ".lua", ".c", ".h", ".cpp", ".rs", ".go", ".sql"}
        if content is None:
            try:
                stat = Path(path).stat()
                mtime = stat.st_mtime
                if not force and path in self._indexed_hashes and self._indexed_hashes[path] >= mtime:
                    return None  # arquivo não mudou, pula
                self._indexed_hashes[path] = mtime
                if ext in CODE_EXTS:
                    content = Path(path).read_text(encoding="utf-8", errors="replace")
                    _sanitizer_version = "code-direct-read"
                else:
                    from jarvis.core.doc_sanitize import sanitize_document
                    san = sanitize_document(path)
                    if san.status != "ok":
                        return None  # quarentena: manifest gravado, sem indexar
                    content = san.text
            except OSError:
                return None
        else:
            # §19: barreira efetiva também p/ conteúdo explícito (MCP/agentes).
            # Sem fonte em disco, piso mínimo absoluto (1 char não-vazio).
            from jarvis.core.doc_sanitize import sanitize_text
            san = sanitize_text(content, fmt=ext if ext.startswith(".") else ".md",
                                min_chars=1)
            if san.status != "ok":
                return None  # quarentena in-memory: sem indexar

        # proveniência canônica do ponto (§13; audit P1-6)
        from datetime import datetime, timezone as _tz
        from jarvis.core.doc_sanitize import SANITIZER_VERSION
        try:
            _sanitizer_version  # code-direct-read já definiu
        except NameError:
            _sanitizer_version = SANITIZER_VERSION
        _ingested_at = datetime.now(_tz.utc).isoformat()

        # Chunking alinhado com o contexto do modelo de embedding.
        # nomic-embed-text-v2-moe tem ctx 2048; 1500 chars ≈ 700 tokens.
        # Com metadata, total fica ~800-900 tokens (safe for ubatch 1024).
        # Chunks maiores = mais contexto = melhor qualidade, mas limitado pelo ubatch.
        chunk_size = 1200
        chunks = [content[i:i + chunk_size] for i in range(0, len(content), chunk_size)]

        facts = extract_facts(content, ext)

        last_payload = None
        for i, chunk in enumerate(chunks):
            rich = build_rich_content(path, facts if i == 0 else [], chunk, max_chars=chunk_size)
            try:
                dense = self._llm.embed(rich)
            except Exception:
                # If embedding fails (e.g., input too large), try with smaller chunk
                smaller = chunk[:len(chunk) // 2]
                rich_fallback = build_rich_content(path, facts if i == 0 else [], smaller, max_chars=len(smaller))
                try:
                    dense = self._llm.embed(rich_fallback)
                except Exception:
                    continue  # Skip this chunk entirely
            if not dense:
                continue

            terms = sparse_terms(rich)
            # Point id = sha256 63-bit de (source_sha256, chunk_index) —
            # estável a rename/move (audit P0-1): reindex sobrescreve em vez
            # de duplicar, e a colisão 32-bit de crc32 não se aplica.
            import hashlib as _hl
            source_sha = _hl.sha256(open(path, 'rb').read()).hexdigest() if os.path.exists(path) else _hl.sha256(content.encode()).hexdigest()
            point = {
                "id": stable_id("doc", source_sha, str(i)),
                "vector": {
                    "dense": dense,
                    "bm25": sparse_vector(terms),
                },
                "payload": {
                    "path": path,
                    "document_id": f"doc:{source_sha[:16]}",
                    "chunk_id": f"{source_sha[:16]}:{i}",
                    "chunk_index": i,
                    "filename": os.path.basename(path),
                    "ext": ext,
                    "facts": facts if i == 0 else [],
                    "content": chunk,
                    "source_sha256": source_sha,
                    "content_hash": _hl.sha256(chunk.encode()).hexdigest(),
                    "sanitizer_version": _sanitizer_version if _sanitizer_version else "1.0.0",
                    "ingested_at": _ingested_at,
                    "embedding_model": self._cfg.embed_model,
                },
            }
            self._store.upsert(self._cfg.qdrant_collection_code, [point])
            last_payload = point["payload"]
            
        return last_payload

    def index_directory(self, root: str | Path) -> int:
        """Indexa todos os arquivos elegíveis de um diretório. Retorna o total de arquivos."""
        self.ensure_collection()
        processed_files = set()
        for path in iter_indexable_files(root, exclude_dirs=self._cfg.index_exclude_dirs):
            if self.index_file(path) is not None:
                processed_files.add(path)
        return len(processed_files)

# ---------------------------------------------------------------------------
# Busca híbrida
# ---------------------------------------------------------------------------

def diversify_by_source(hits: list[dict[str, Any]], *, penalty: float = 0.95) -> list[dict[str, Any]]:
    """Diversidade por fonte (MMR-lite determinístico, pós-fusão/rerank).

    Arquivos grandes inundam o top-k com chunks medíocres (medido 18/09:
    18 chunks de harness.py no top-100 afundavam a definição de
    loop_detector.py para além do rank 100). Penalidade multiplicativa
    cumulativa por fonte: a 1ª ocorrência mantém o score, cada repetição
    decai ×penalty — reordena apenas quando uma fonte já saturou o topo.
    Hit sem chave de fonte (payload sem path/book/source_id) não é
    penalizado. Single-source: ordem relativa preservada.
    """
    def _src(hit: dict[str, Any]) -> str:
        payload = hit.get("payload", {}) or {}
        return str(payload.get("path") or payload.get("book") or payload.get("source_id") or "")

    counts: dict[str, int] = {}
    pool = [dict(h) for h in hits]
    out: list[dict[str, Any]] = []
    while pool:
        best_i, best_adj, best_src = 0, -1.0, ""
        for i, hit in enumerate(pool):
            src = _src(hit)
            adj = float(hit.get("score", 0.0) or 0.0)
            if src:
                adj *= penalty ** counts.get(src, 0)
            if adj > best_adj:
                best_i, best_adj, best_src = i, adj, src
        hit = pool.pop(best_i)
        if best_src:
            counts[best_src] = counts.get(best_src, 0) + 1
        hit["score"] = float(best_adj)
        out.append(hit)
    return out


class HybridSearch:
    """Busca híbrida (dense + sparse BM25, fusão RRF) + re-rank V4.0.5."""

    def __init__(self, config: Config | None = None) -> None:
        self._cfg = config or Config()
        self._store = QdrantStore(self._cfg)
        self._llm = LLMClient(self._cfg)

    def search(
        self,
        query: str,
        *,
        top_k: int = 5,
        dense_limit: int = 50,
        sparse_limit: int = 50,
        dense_override: list[float] | None = None,
        use_rerank: bool = True,
        diversify: bool = True,
    ) -> list[HybridHit]:
        """Busca híbrida (prefetch dense+sparse + RRF) e re-rank V4.0.5."""
        if dense_override is not None:
            dense = dense_override
        else:
            dense = self._llm.embed(query)
            if not dense:
                return []

        sparse = sparse_vector(sparse_terms(query))
        raw = self._store.search_hybrid(
            self._cfg.qdrant_collection_code,
            dense,
            sparse,
            top_k=top_k * 4,
            dense_limit=dense_limit,
            sparse_limit=sparse_limit,
            ext_filter=_target_extension(query),
        )

        boosted = apply_legacy_boosts(query, raw)
        if use_rerank and boosted:
            ranked = self._rerank_candidates(query, boosted)
        else:
            ranked = boosted

        # Diversidade por fonte default ON com penalty=0.95: benchmark v2
        # (10 queries) mostrou dominação estrita — ON(0.95) = 10/10 na janela
        # MCP=5 (OFF 10/10 também) E 10/10 na janela 3 para books (OFF 9/10:
        # nickyeo afogado pelo paper dominante). Penalty 0.85/0.90 regredia o
        # alvo intra-arquivo (semantic-loop 11→25); 0.95 não. Fonte da
        # decisão: logs/acceptance-bench-v2.json + sweep 0.85–0.95 de 18/09.
        if diversify:
            ranked = diversify_by_source(ranked)

        return [
            HybridHit(
                path=hit["payload"].get("path", ""),
                score=hit["score"],
                payload=hit["payload"],
            )
            for hit in ranked[:top_k]
        ]

    def _rerank_candidates(self, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Reordena os candidatos (já boosted) pelo cross-encoder.

        Otimização 19/09: reranker CPU (bge-reranker-v2-m3 Q4) leva ~10s para
        20 docs×600 chars (12k chars). Limita a top 10 e 350 chars cada
        (3.5k) → ~1.5s sem perda de qualidade (fusão RRF já pré-filtrou).
        """
        try:
            from jarvis.providers.reranker import Reranker, RerankerError

            # Só re-rankeia os 5 melhores do boost (top_k) — 10→5 corta 1.2s
            rerank_slice = candidates[:5]
            reranker = Reranker(self._cfg.rerank_base_url, timeout=120.0)
            docs = [
                str(hit.get("payload", {}).get("content", ""))[:350]
                or str(hit.get("payload", {}).get("path", ""))
                for hit in rerank_slice
            ]
            scores = reranker.rerank(query, docs)
            # Se cortou, só reordena o slice; resto mantém ordem boost
            if len(scores) != len(rerank_slice):
                return candidates
            # Reconstroi lista completa: slice reordenado + tail intocado
            n_slice = len(rerank_slice)
            order = sorted(range(n_slice), key=lambda i: -scores[i])
            rrank = {idx: pos + 1 for pos, idx in enumerate(order)}
            fused: list[tuple[float, int]] = []
            for i in range(n_slice):
                s = 1.0 / (_RERANK_K + i + 1) + 1.0 / (_RERANK_K + rrank[i])
                fused.append((s + _RERANK_TIEBREAK / (i + 1), i))
            fused.sort(key=lambda x: -x[0])
            ranked_slice = [dict(rerank_slice[i]) for _, i in fused]
            for (s, _), hit in zip(fused, ranked_slice):
                hit["score"] = float(s)
            return ranked_slice + candidates[n_slice:]
        except Exception:  # noqa: BLE001 + Fallback silencioso para qualquer erro de comunicação ou parsing
            return candidates
