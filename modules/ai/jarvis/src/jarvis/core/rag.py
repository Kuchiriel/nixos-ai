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
import signal
import sys
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable, Sequence

from jarvis.core.config import Config
from jarvis.providers.llm import LLMClient
from jarvis.providers.vector_store import QdrantStore, dense_key, stable_id


class IndexDeadline(BaseException):
    """Teto de relogio do index estourou.

    BaseException DE PROPOSITO: `index_file` tem `except Exception` no
    fallback de embed (batch -> item a item) e engoliria um TimeoutError,
    deixando o hang continuar (medido 08/11: um rag-index ficou 13h em
    `poll` num socket do :8081 com o servidor saudavel). Quem captura e o
    `index_directory`, que devolve o parcial.
    """


class _hard_deadline:
    """SIGALRM: interrompe ate um socket pendurado. So no thread principal."""

    def __init__(self, seconds: float | None) -> None:
        self.seconds = float(seconds or 0)
        self._old = None
        self._active = False

    def __enter__(self) -> "_hard_deadline":
        if self.seconds <= 0:
            return self
        if threading.current_thread() is not threading.main_thread():
            return self  # signal.alarm exige o thread principal
        def _boom(signum, frame):  # noqa: ANN001
            raise IndexDeadline(f"index deadline {self.seconds:.0f}s")
        self._old = signal.signal(signal.SIGALRM, _boom)
        signal.alarm(max(1, int(self.seconds)))
        self._active = True
        return self

    def __exit__(self, *exc: object) -> bool:
        if self._active:
            signal.alarm(0)
            signal.signal(signal.SIGALRM, self._old)
        return False

# ---------------------------------------------------------------------------
# Corpus offline de sobrevivência (fase A do N.O.M.A.D)
# ---------------------------------------------------------------------------

# Coleção PRÓPRIA do corpus offline: nunca entra no default de busca
# (code_index/books) — texto de sobrevivência não dilui a busca de código.
# O nome vive aqui (e não em config.py) porque o corpus é opcional; o env
# permite trocar o nome sem rebuild.
OFFLINE_COLLECTION = os.environ.get(
    "JARVIS_QDRANT_COLLECTION_OFFLINE", "offline_survival")

# Léxico de sobrevivência: pergunta de água/veneno/emergência é respondida
# pelo corpus local (funciona sem internet).
OFFLINE_KEYWORDS: tuple[str, ...] = (
    "água", "agua", "water", "primeiros socorros", "first aid", "veneno",
    "poison", "sobrevivencia", "sobrevivência", "survival", "cozimento",
    "cook", "abrigo", "shelter", "emergencia", "emergência", "emergency",
    "blackout", "purificar", "purify", "fome", "hunger", "filtro",
)

# Pergunta de código/paper/documento do projeto NÃO vai pro corpus offline:
# continua no rag_search (comportamento anterior).
OFFLINE_EXCLUDE: tuple[str, ...] = (
    "código", "codigo", "script", "repositório", "repositorio", "repo",
    "commit", "branch", "nixos", "docker", "paper", "arxiv", "livro",
)


def offline_route_reason(question: str) -> str | None:
    """Keyword que joga a pergunta pro corpus offline (None = não é offline).

    Decisão PURA (sem rede, sem I/O): a voz e o harness usam a MESMA
    função, e o teste de rota cobre só isto.
    """
    q = (question or "").lower()
    if not q.strip():
        return None
    if any(marker in q for marker in OFFLINE_EXCLUDE):
        return None
    for keyword in OFFLINE_KEYWORDS:
        if keyword in q:
            return keyword
    return None


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

# ---------------------------------------------------------------------------
# Metadata extraction helpers for improved retrieval
# ---------------------------------------------------------------------------
import re
import os

def _extract_arxiv_id(path: str, content: str) -> str | None:
    """Extract arXiv ID from path or content. Only matches in paper-like contexts."""
    import re
    fname = os.path.basename(path)
    # 1) Filename with known prefixes (arxiv-, paper-, d2-, memt-*, etc.)
    m = re.search(r'(?:arxiv[-_]|paper[-_]|d2[-_]|memt[-_].*[-_]|heartbeat[-_]thinking[-_]|searchgym[-_]|^)(\d{4}\.\d{4,5}(?:v\d+)?)', fname, re.IGNORECASE)
    if m:
        return m.group(1)
    # 2) Papers directory: any arxiv pattern in filename is trustworthy
    if "/papers/" in path.replace(os.sep, "/"):
        m = re.search(r'\b(\d{4}\.\d{4,5}(?:v\d+)?)\b', fname)
        if m:
            return m.group(1)
    # 3) Standalone arXiv ID in filename (strict contexts)
    m = re.search(r'\b(\d{4}\.\d{4,5}(?:v\d+)?)\b', fname)
    if m and (fname.startswith('arxiv') or 'paper' in fname.lower() or fname[0].isdigit()):
        return m.group(1)
    # 4) From content
    m = re.search(r'arXiv:(\d{4}\.\d{4,5}(?:v\d+)?)', content[:2000])
    if m:
        return m.group(1)
    return None

def _extract_year(content: str) -> str | None:
    """Extract year from content."""
    m = re.search(r'(20\d{2})', content[:2000])
    if m:
        year = int(m.group(1))
        if 2000 <= year <= 2030:
            return str(year)
    return None

def _extract_domain(path: str, content: str) -> str | None:
    """Extract domain from path or content."""
    path_lower = path.lower()
    if any(w in path_lower for w in ['voz', 'stt', 'asr', 'tts', 'voice']):
        return 'voice'
    if any(w in path_lower for w in ['kernel', 'harness', 'agent']):
        return 'agent'
    if any(w in path_lower for w in ['rag', 'hybrid', 'search', 'retrieval']):
        return 'rag'
    if any(w in path_lower for w in ['vision', 'vision']):
        return 'vision'
    if any(w in path_lower for w in ['embedding', 'embedding']):
        return 'embedding'
    if any(w in path_lower for w in ['llm', 'llama', 'qwen']):
        return 'llm'
    if any(w in path_lower for w in ['memory', 'memory']):
        return 'memory'
    if any(w in path_lower for w in ['eval', 'eval']):
        return 'eval'
    if any(w in path_lower for w in ['benchmark', 'benchmark']):
        return 'benchmark'
    # Check content for domain keywords
    content_lower = content[:2000].lower()
    if any(w in content_lower for w in ['speech', 'audio', 'voice', 'whisper', 'asr', 'tts']):
        return 'voice'
    if any(w in content_lower for w in ['agent', 'tool', 'function', 'api']):
        return 'agent'
    if any(w in content_lower for w in ['retrieval', 'retriever', 'rag', 'embedding', 'vector']):
        return 'rag'
    if any(w in content_lower for w in ['memory', 'episodic', 'semantic']):
        return 'memory'
    return None

# ---------------------------------------------------------------------------
# .ragignore — sintaxe gitignore (padrão de mercado: mesma engine do .gitignore,
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


# Sigla pontuada (N.O.M.A.D, S.O.S., C.A.B.): 2-5 letras maiúsculas
# separadas por ponto. A heurística de extensão via regex pegava a letra
# interna ("N.O.M.A.D" -> ".o") e zerava a busca em texto de sobrevivência.
_ACRONYM_RE = re.compile(r"\b[A-Z](?:\.[A-Z]){1,4}\.?\b")
_EXT_RE = re.compile(r"\.([a-zA-Z][a-zA-Z0-9]{0,3})\b")


# (19/11) Strong document identifiers survive extra query tokens better when
# the dense vector is built from the identifier alone (measured: "CYCLE-9" ranks
# the right doc #1; "CYCLE-9 Harbor" drops it from top-10).
_STRONG_ID_RE = re.compile(r"\b(?:[A-Z][A-Z0-9]*-\d+|\d{4}\.\d{4,5})\b")


def strong_query_identifier(query: str) -> str | None:
    """Return the first strong document identifier in a query, or None."""
    m = _STRONG_ID_RE.search(query or "")
    return m.group(0) if m else None


def _target_extension(query: str) -> str | None:
    """Extensão de arquivo citada na query (".py", ".md"), se houver.

    Ignora pontos que fazem parte de uma sigla pontuada (N.O.M.A.D, S.O.S.):
    o filtro por extensão zerava a busca em corpus de sobrevivência.
    """
    acronyms = [m.span() for m in _ACRONYM_RE.finditer(query)]
    for m in _EXT_RE.finditer(query):
        span = m.span()
        if any(a_start < span[1] and span[0] < a_end for a_start, a_end in acronyms):
            continue
        return "." + m.group(1).lower()
    return None


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

        # `filename` vazio (hit sem path, ex.: payload de `books`) e substring
        # de QUALQUER query: `"" in query_l` e True, e o hit levava +100000
        # de soberania, dominando o top-k (medido 19/11: dois pontos de book
        # no top-2 de uma pergunta de codigo, score 100000.18).
        if filename and (filename in query_l or (len(stem) >= 8 and stem in query_l)):
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


# ALLOW (03/10, a pedido do dono): dirs que SEMPRE indexam, mesmo que um
# exclude substring casaria (ex.: "items" mata data-sandbox/items).
# Match EXATO no nome do dir, com precedência sobre excludes.
_ALLOW_DIRS: tuple[str, ...] = (
    "data", "data-sandbox", "data-canary", "dataset", "datasets",
    "docs", "doc", "lib", "libs", "src", "scripts", "tools", "tests",
    "items", "world", "monster", "npc", "schema", "facts", "stubs",
)


def _prune_on_index() -> bool:
    """Opt-in: apaga versoes antigas do MESMO path durante a indexacao.

    Default OFF: indexar nunca apaga nada sem `JARVIS_RAG_PRUNE_ON_INDEX=1`.
    A reconciliacao em lote (dry-run + manifesto) fica em `core/rag_prune.py`.
    """
    return os.environ.get("JARVIS_RAG_PRUNE_ON_INDEX", "").strip().lower() in (
        "1", "true", "yes", "on")


def iter_indexable_files(root: str | Path, exclude_dirs: Iterable[str] | None = None) -> Iterable[str]:
    """Varre um diretório/arquivo com as mesmas regras do V4.0.5 (excludes, tamanho).
    Respeita também um .ragignore na raiz (sintaxe gitignore; ver _load_ragignore).
    `_ALLOW_DIRS` tem precedência EXATA sobre os excludes (substring)."""
    excludes = tuple(e.lower() for e in (exclude_dirs if exclude_dirs is not None else _EXCLUDE_DIRS))
    allows = {a.lower() for a in _ALLOW_DIRS}
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
        # ALLOW exact-match vence: dir permitido não é excluído por substring
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".")
            and (d.lower() in allows or (
                d.lower() not in excludes
                and not any(ex in d.lower() for ex in excludes)
            ))
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
        # Por que cada arquivo NAO foi indexado nesta rodada (path, motivo).
        # MEDIDO 07/11: `rag_index` devolvia "Indexed 0 files" SEM dizer o
        # motivo — o arquivo estava em quarentena PATH_ERROR (fora das read
        # roots) e o diagnóstico custou 4 rounds. Agora a tool reporta.
        self.skipped: list[tuple[str, str]] = []

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
                    self.skipped.append((path, "unchanged"))
                    return None  # arquivo não mudou, pula
                # NÃO grava o manifest aqui: o arquivo pode cair em
                # quarentena (PATH_ERROR/PII) ou falhar no embed, e um
                # arquivo marcado como indexado sem ter sido indexado
                # nunca mais é retryado — perda silenciosa (vault inteiro
                # ficava invisível por estar fora das read roots). O
                # registro é feito em _mark_indexed(), no fim, só se
                # algum chunk foi de fato upsertado.
                if ext in CODE_EXTS:
                    content = Path(path).read_text(encoding="utf-8", errors="replace")
                    _sanitizer_version = "code-direct-read"
                else:
                    from jarvis.core.doc_sanitize import sanitize_document
                    san = sanitize_document(path)
                    if san.status != "ok":
                        self.skipped.append((path, getattr(san, "reason", "quarantine")))
                        return None  # quarentena: manifest gravado, sem indexar
                    content = san.text
            except OSError as e:
                self.skipped.append((path, f"unreadable: {e.__class__.__name__}"))
                return None
        else:
            # §19: barreira efetiva também p/ conteúdo explícito (MCP/agentes).
            # Sem fonte em disco, piso mínimo absoluto (1 char não-vazio).
            from jarvis.core.doc_sanitize import sanitize_text
            san = sanitize_text(content, fmt=ext if ext.startswith(".") else ".md",
                                min_chars=1)
            if san.status != "ok":
                self.skipped.append((path, getattr(san, "reason", "quarantine")))
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
        # Lote denso em 1 POST (medido 07/10: 44ms/item solo vs 2ms/item em
        # lote). Fallback preservado: se o lote falhar, volta ao por-chunk
        # com metades (semântica antiga intacta).
        rich_list = [build_rich_content(path, facts if i == 0 else [], chunk, max_chars=chunk_size)
                     for i, chunk in enumerate(chunks)]
        # Route by content: ~/Books → books collection; resto → code_index
        target_collection = ("books" if path.startswith(
            str(Path.home() / "Books")) else
            self._cfg.qdrant_collection_code)
        # sha do fonte UMA vez por arquivo (medido 19/11: ficava dentro do
        # loop de chunks e relia o arquivo inteiro a cada chunk).
        import hashlib as _hl
        if os.path.exists(path):
            source_sha = _hl.sha256(Path(path).read_bytes()).hexdigest()
        else:
            source_sha = _hl.sha256(content.encode()).hexdigest()
        try:
            dense_list = self._llm.embed_batch(rich_list)
            if len(dense_list) != len(rich_list):
                raise ValueError("batch size mismatch")
            batched = True
        except Exception:
            dense_list = [None] * len(rich_list)
            batched = False
        dropped = 0
        for i, chunk in enumerate(chunks):
            rich = rich_list[i]
            dense = dense_list[i] if batched else None
            if not dense:
                try:
                    dense = self._llm.embed(rich)
                except Exception:
                    # Chunk maior que o ctx do embedder: indexa METADE do
                    # texto, e o payload passa a guardar essa metade. Antes
                    # o vetor vinha da metade mas o payload do chunk inteiro:
                    # o ponto recuperava por um vetor que nao representava o
                    # conteudo recuperado (medido 19/11, audit P1-3).
                    chunk = chunk[:len(chunk) // 2]
                    rich = build_rich_content(path, facts if i == 0 else [], chunk, max_chars=len(chunk))
                    try:
                        dense = self._llm.embed(rich)
                    except Exception:
                        dense = None
            if not dense:
                # Sem vetor o ponto nao pode ser gravado: registra o motivo
                # em `skipped` para o chamador nao achar que o arquivo
                # entrou inteiro (antes o `continue` era silencioso).
                dropped += 1
                continue

            terms = sparse_terms(rich)
            # Point id = sha256 63-bit de (source_sha256, chunk_index) —
            # estável a rename/move (audit P0-1): reindex sobrescreve em vez
            # de duplicar, e a colisão 32-bit de crc32 não se aplica.
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
                    "arxiv_id": _extract_arxiv_id(path, content),
                    "year": _extract_year(content),
                    "domain": _extract_domain(path, content),
                },
            }
            # Route by content: ~/Books → books collection; resto → code_index
            self._store.upsert(target_collection, [point])
            last_payload = point["payload"]

        if dropped:
            self.skipped.append((path, f"chunk_dropped {dropped}/{len(chunks)}"))

        if last_payload is not None and _prune_on_index():
            # Opt-in (JARVIS_RAG_PRUNE_ON_INDEX=1): aposenta as versoes
            # anteriores DESTE path no mesmo passo da indexacao. Sem isso o
            # id muda a cada edicao e o indice acumula versoes antigas
            # recuperaveis (medido 19/11: rag.py 7 versoes, 231 pontos,
            # 39 chunks atuais). Filtro exato por path + sha diferente;
            # default OFF para nao apagar nada sem pedido explicito.
            try:
                self._store.delete_by_filter(
                    target_collection,
                    must=[{"key": "path", "match": {"value": path}}],
                    must_not=[{"key": "source_sha256", "match": {"value": source_sha}}],
                )
            except Exception:  # noqa: BLE001 — prune nunca derruba a indexacao
                pass
            
        if last_payload is not None:
            self._mark_indexed(path)
        return last_payload

    def _mark_indexed(self, path: str) -> None:
        """Registra no manifest que `path` foi REALMENTE indexado.

        Só pode ser chamado depois de um upsert bem-sucedido: o manifest
        é o que faz `index_file` pular arquivo inalterado, então gravar
        antes de indexar transforma quarentena/erro de embed em perda
        permanente e silenciosa.
        """
        try:
            self._indexed_hashes[path] = Path(path).stat().st_mtime
        except OSError:
            pass

    def index_directory(self, root: str | Path, force: bool = False,
                        deadline_s: float | None = None) -> int:
        """Indexa todos os arquivos elegíveis de um diretório. Retorna o total de arquivos.

        deadline_s: teto de relogio DURO (default: env JARVIS_INDEX_DEADLINE,
        1800s). Medido 08/11: sem teto, um `rag-index` ficou 13h pendurado num
        socket do :8081. Ao estourar, para e devolve o parcial; o upsert e
        idempotente por id, entao rodar de novo completa.
        """
        if deadline_s is None:
            try:
                deadline_s = float(os.environ.get("JARVIS_INDEX_DEADLINE", "1800"))
            except ValueError:
                deadline_s = 1800.0
        self.ensure_collection()
        processed_files = set()
        self.skipped = []
        t0 = time.monotonic()
        seen = 0
        try:
            with _hard_deadline(deadline_s):
                for path in iter_indexable_files(root, exclude_dirs=self._cfg.index_exclude_dirs):
                    if deadline_s and deadline_s > 0 and time.monotonic() - t0 > deadline_s:
                        raise IndexDeadline(f"index deadline {deadline_s:.0f}s")
                    if self.index_file(path, force=force) is not None:
                        processed_files.add(path)
                    seen += 1
                    if seen % 25 == 0:
                        print(f"index: {seen} arquivos ({time.monotonic() - t0:.0f}s)",
                              file=sys.stderr, flush=True)
        except IndexDeadline as e:
            print(f"index: PARCIAL — {e} apos {time.monotonic() - t0:.0f}s; "
                  f"{len(processed_files)} arquivos entraram (re-rodar completa)",
                  file=sys.stderr, flush=True)
        # "unchanged" e o caso normal de reindexacao incremental; o resto
        # (quarentena, chunk pulado, ilegivel) e o que explica um arquivo
        # que nao entrou. Sem isso o resumo so dizia quantos entraram.
        reasons: dict[str, int] = {}
        for _path, reason in self.skipped:
            if reason == "unchanged":
                continue
            key = reason.split()[0] if reason else "unknown"
            reasons[key] = reasons.get(key, 0) + 1
        if reasons:
            detail = ", ".join(f"{k}={v}" for k, v in sorted(reasons.items(), key=lambda kv: -kv[1]))
            print(f"index: {len(processed_files)} entraram; nao entraram: {detail}",
                  file=sys.stderr, flush=True)
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
        metadata_filter: dict[str, Any] | None = None,
        hyde: bool = False,
        collection: str | None = None,
    ) -> list[HybridHit]:
        """Busca híbrida (prefetch dense+sparse + RRF) e re-rank V4.0.5.

        Args:
            query: Query text
            top_k: Number of results to return
            dense_limit: Max dense candidates
            sparse_limit: Max sparse candidates
            dense_override: Pre-computed dense vector
            use_rerank: Whether to apply cross-encoder reranking
            diversify: Whether to diversify by source
            metadata_filter: Optional metadata filter (e.g., {"arxiv_id": "2610.17124", "domain": "voice"})
            hyde: Whether to use HyDE (Hypothetical Document Embeddings) for ambiguous queries
            collection: Which Qdrant collection to search (default: code_index, use "books" for papers)
        """
        # (19/11) dense-query normalization: if the query has a strong doc id,
        # embed just that id (extra tokens dilute the vector). Sparse/RRF/boosts
        # still use the full query — this only changes the dense vector text.
        dense_query = query
        if not hyde:
            sid = strong_query_identifier(query)
            if sid:
                dense_query = sid

        if hyde:
            query = self._hyde_expand(query)

        if dense_override is not None:
            dense = dense_override
        else:
            dense = self._llm.embed(dense_query)
            if not dense:
                return []

        sparse = sparse_vector(sparse_terms(query))

        # Build filter for Qdrant as plain dict (mesmo formato do ext_filter
        # em vector_store.py — sem dependência de qdrant_client models)
        qdrant_filter = None
        if metadata_filter:
            conditions = [{"key": k, "match": {"value": v}}
                          for k, v in metadata_filter.items()]
            qdrant_filter = {"must": conditions}

        # Determine which collection to search: explicit -> 1; default -> both
        if collection:
            collections_to_search = [collection]
        else:
            collections_to_search = [self._cfg.qdrant_collection_code, "books"]
        all_raw = []
        for coll in collections_to_search:
            try:
                raw = self._store.search_hybrid(
                    coll,
                    dense,
                    sparse,
                    top_k=top_k * 4,
                    dense_limit=dense_limit,
                    sparse_limit=sparse_limit,
                    ext_filter=_target_extension(query),
                    filter=qdrant_filter,
                )
                all_raw.extend(raw)
            except Exception:
                continue  # Collection might not exist

        # Deduplicate by document_id when present; keep hits without it.
        seen = set()
        deduped = []
        for hit in all_raw:
            doc_id = hit.get("payload", {}).get("document_id")
            if doc_id:
                if doc_id in seen:
                    continue
                seen.add(doc_id)
            deduped.append(hit)
        raw = deduped

        boosted = apply_legacy_boosts(query, raw)
        if use_rerank and boosted:
            # Slice fixo em 5 (medido 19/11: subir para 8 piorou o acerto de
            # 3/5 para 0/5 no k=8 — o cross-encoder com 350 chars/doc
            # desordena mais do que ajuda; ver RAG-EVAL no docs/audit).
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

    def _hyde_expand(self, query: str) -> str:
        """Generate hypothetical document for HyDE (Hypothetical Document Embeddings).

        Generates a hypothetical answer to the query, then uses that as the
        search query. Helps with ambiguous or underspecified queries.
        """
        try:
            prompt = f"""Answer the following question concisely:

Question: {query}

Answer:"""
            from jarvis.providers.llm import LLMClient
            from jarvis.core.config import Config
            cfg = Config()
            llm = LLMClient(cfg)
            response = llm.generate(prompt, max_tokens=200, temperature=0.3)
            return f"{query} {response.strip()}"
        except Exception:
            return query

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
            n_slice = len(rerank_slice)
            # O cross-encoder manda: ordem = score dele (empate: ordem boost).
            # A fusão anterior (1/(K+i+1) + 1/(K+rrank)) era quase simétrica —
            # rerank 1º no fim do slice empatava com rerank último no começo e
            # o desempate devolvia a ordem do boost, anulando o reranker.
            order = sorted(range(n_slice), key=lambda i: (-scores[i], i))
            tail = candidates[n_slice:]
            # Score dos re-rankeados fica ACIMA da cauda e decrescente: o
            # diversify_by_source reordena por score, então score pequeno
            # (~1/61) fazia a cauda (boost 2..100000) subir na frente — medido
            # 19/11: recall@8 0.93 sem rerank contra 0.36 com rerank.
            base = max(
                max((float(h.get("score", 0.0)) for h in rerank_slice), default=0.0),
                max((float(h.get("score", 0.0)) for h in tail), default=0.0),
            )
            ranked_slice = []
            for pos, i in enumerate(order):
                hit = dict(rerank_slice[i])
                hit["score"] = base + 1.0 - pos * 1e-3
                ranked_slice.append(hit)
            return ranked_slice + tail
        except Exception:  # noqa: BLE001 + Fallback silencioso para qualquer erro de comunicação ou parsing
            return candidates
