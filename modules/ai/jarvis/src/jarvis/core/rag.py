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

import requests

from jarvis.core.config import Config
from jarvis.providers.llm import LLMClient
from jarvis.providers.vector_store import QdrantStore, dense_key

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
    "cache", "tmp", "trash", "appcache", "gpu_cache", "code_cache",

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
    """Tokeniza texto em {termo: frequência} para o sparse vector BM25."""
    counts: dict[str, float] = {}
    for token in re.findall(r"[a-zA-Z0-9_]+", text.lower()):
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
        return (
            "/AI_SYSTEM" in root
            or "forensic" in root.lower()
            or "capture" in root.lower()
            or file in {"GEMINI.md", "JARVIS.md", "AGENTS.md", "README.md"}
        )
    return False


def iter_indexable_files(root: str | Path, exclude_dirs: Iterable[str] | None = None) -> Iterable[str]:
    """Varre um diretório/arquivo com as mesmas regras do V4.0.5 (excludes, tamanho)."""
    excludes = tuple(e.lower() for e in (exclude_dirs if exclude_dirs is not None else _EXCLUDE_DIRS))
    root_path = Path(root)
    
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
        
        for file in filenames:
            if file.startswith("."):
                continue
            if _is_allowed(dirpath, file):
                path = Path(dirpath) / file
                try:
                    if path.stat().st_size <= _MAX_FILE_SIZE_KB * 1024:
                        yield str(path)
                except OSError:
                    continue

'''
def iter_indexable_files(root: str | Path, exclude_dirs: Iterable[str] | None = None) -> Iterable[str]:
    """Varre um diretório/arquivo com as mesmas regras do V4.0.5 (excludes, tamanho)."""
    excludes = tuple(exclude_dirs) if exclude_dirs is not None else _EXCLUDE_DIRS
    root_path = Path(root).resolve()
    
    if root_path.is_file():
        if _is_allowed(str(root_path.parent), root_path.name):
            try:
                if root_path.stat().st_size <= _MAX_FILE_SIZE_KB * 1024:
                    yield str(root_path)
            except OSError:
                pass
        return

    for dirpath, dirnames, filenames in os.walk(root_path):
        dirnames[:] = [
            d for d in dirnames
            if not d.startswith(".")
            and not any(ex in d.lower() for ex in excludes)
        ]
        if any(ex in dirpath.lower() for ex in excludes):
            continue
        for file in filenames:
            if file.startswith("."):
                continue
            if _is_allowed(dirpath, file):
                path = Path(dirpath) / file
                try:
                    if path.stat().st_size <= _MAX_FILE_SIZE_KB * 1024:
                        yield str(path.resolve())
                except OSError:
                    continue
'''

class HybridIndexer:
    """Indexa arquivos de código no Qdrant (dense + sparse BM25 + payload)."""

    def __init__(self, config: Config | None = None) -> None:
        self._cfg = config or Config()
        self._store = QdrantStore(self._cfg)
        self._llm = LLMClient(self._cfg)

    def ensure_collection(self) -> None:
        self._store.ensure_collection(self._cfg.qdrant_collection_code, dim=self._cfg.embed_dim)

    def index_file(self, path: str, *, content: str | None = None) -> dict[str, Any] | None:
        """Indexa um arquivo com chunking para respeitar o limite de contexto."""
        ext = os.path.splitext(path)[1].lower()
        if content is None:
            try:
                content = Path(path).read_text(encoding="utf-8", errors="ignore")
            except OSError:
                return None

        # Chunking alinhado com o contexto do modelo
        chunk_size = 800 
        chunks = [content[i:i + chunk_size] for i in range(0, len(content), chunk_size)]

        facts = extract_facts(content, ext)

        last_payload = None
        for i, chunk in enumerate(chunks):
            rich = build_rich_content(path, facts if i == 0 else [], chunk, max_chars=chunk_size)
            dense = self._llm.embed(rich)
            if not dense:
                continue

            terms = sparse_terms(rich)
            point = {
                "id": abs(dense_key(f"{path}_chunk_{i}")),
                "vector": {
                    "dense": dense,
                    "bm25": sparse_vector(terms),
                },
                "payload": {
                    "path": path,
                    "chunk_index": i,
                    "filename": os.path.basename(path),
                    "ext": ext,
                    "facts": facts if i == 0 else [],
                    "content": chunk,
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

        return [
            HybridHit(
                path=hit["payload"].get("path", ""),
                score=hit["score"],
                payload=hit["payload"],
            )
            for hit in ranked[:top_k]
        ]

    def _rerank_candidates(self, query: str, candidates: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Reordena os candidatos (já boosted) pelo cross-encoder."""
        try:
            from jarvis.providers.reranker import Reranker, RerankerError

            reranker = Reranker(self._cfg.rerank_base_url, timeout=120.0)
            docs = [
                str(hit.get("payload", {}).get("content", ""))[:600]
                or str(hit.get("payload", {}).get("path", ""))
                for hit in candidates
            ]
            scores = reranker.rerank(query, docs)
        except Exception:  # Fallback silencioso para qualquer erro de comunicação ou parsing
            return candidates

        n = len(candidates)
        if len(scores) != n:
            return candidates

        order = sorted(range(n), key=lambda i: -scores[i])
        rrank = {idx: pos + 1 for pos, idx in enumerate(order)}
        
        fused: list[tuple[float, int]] = []
        for i in range(n):
            s = 1.0 / (_RERANK_K + i + 1) + 1.0 / (_RERANK_K + rrank[i])
            fused.append((s + _RERANK_TIEBREAK / (i + 1), i))
        
        fused.sort(key=lambda x: -x[0])
        ranked = [dict(candidates[i]) for _, i in fused]
        
        for (s, _), hit in zip(fused, ranked):
            hit["score"] = float(s)
            
        return ranked
