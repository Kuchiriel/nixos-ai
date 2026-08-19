"""Índice legado (.ai-index, NumPy) — leitura, busca pura e migração one-shot.

O legado (Manjaro/AI_SYSTEM) mantinha o RAG de código em:
  ~/.ai-index/global_vectors.npy   (4617×768, float64, nomic-embed-text via Ollama)
  ~/.ai-index/global_meta.json     (lista [{path, facts, content}])
  ~/.ai-index/symbols.json         (símbolo → [paths])
  ~/.ai-index/file_hashes.json     (path → sha256)

Este módulo:
- Carrega o índice (LegacyIndex) sem depender de nada além de numpy.
- Reimplementa a busca do `codebase_indexer.search` V4.0.5 em NumPy puro
  (`legacy_search`) — usada como ground-truth no teste de paridade.
- Migra o índice para o Qdrant (`migrate`) reusando os vetores existentes
  (dense) e derivando o sparse BM25 do conteúdo — sem re-embedding de 4617
  arquivos na migração; a reindexação com o modelo novo é o `jarvis index`.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from jarvis.core.config import Config
from jarvis.core.rag import build_rich_content, sparse_terms, sparse_vector
from jarvis.providers.vector_store import QdrantStore, dense_key

# Nomes dos arquivos do índice legado
HASHES_FILE = "file_hashes.json"
GLOBAL_META = "global_meta.json"
GLOBAL_VECTORS = "global_vectors.npy"
GLOBAL_SYMBOLS = "symbols.json"


class LegacyIndexError(RuntimeError):
    pass


@dataclass
class LegacyIndex:
    """Índice legado carregado em memória (ordem alinhada meta ↔ vectors)."""

    meta: list[dict[str, Any]]
    vectors: np.ndarray
    symbols: dict[str, list[str]]
    hashes: dict[str, str] = field(default_factory=dict)
    index_dir: Path | None = None

    def __len__(self) -> int:
        return len(self.meta)

    def paths(self) -> list[str]:
        return [m.get("path", "") for m in self.meta]

    # --- helpers de payload (mesmo schema do novo Qdrant) ---

    def payload_for(self, idx: int) -> dict[str, Any]:
        m = self.meta[idx]
        path = m.get("path", "")
        facts = m.get("facts", [])
        return {
            "path": path,
            "filename": os.path.basename(path),
            "ext": os.path.splitext(path)[1].lower(),
            "facts": facts,
            "symbols": [f.split(": ", 1)[-1] for f in facts],
            "content": m.get("content", ""),
        }

    def rich_content_for(self, idx: int, max_chars: int = 3000) -> str:
        m = self.meta[idx]
        return build_rich_content(
            m.get("path", ""),
            m.get("facts", []),
            m.get("content", ""),
            max_chars=max_chars,
        )


def load_legacy_index(index_dir: str | Path) -> LegacyIndex:
    """Carrega um .ai-index legado. Lança LegacyIndexError se incompleto."""
    index_dir = Path(index_dir).expanduser()
    meta_path = index_dir / GLOBAL_META
    vectors_path = index_dir / GLOBAL_VECTORS
    symbols_path = index_dir / GLOBAL_SYMBOLS

    missing = [p.name for p in (meta_path, vectors_path, symbols_path) if not p.exists()]
    if missing:
        raise LegacyIndexError(f"índice legado incompleto em {index_dir}: faltam {missing}")

    try:
        meta = json.loads(meta_path.read_text())
        vectors = np.load(vectors_path)
        symbols = json.loads(symbols_path.read_text())
    except (json.JSONDecodeError, ValueError) as exc:
        raise LegacyIndexError(f"falha ao ler índice legado em {index_dir}: {exc}") from exc

    if not isinstance(meta, list) or vectors.ndim != 2 or len(meta) != vectors.shape[0]:
        raise LegacyIndexError(
            f"formato inesperado: meta={type(meta).__name__} len={len(meta) if isinstance(meta, list) else '?'} "
            f"vectors.shape={vectors.shape}"
        )

    hashes: dict[str, str] = {}
    hashes_path = index_dir / HASHES_FILE
    if hashes_path.exists():
        try:
            hashes = json.loads(hashes_path.read_text())
        except json.JSONDecodeError:
            pass

    return LegacyIndex(meta=meta, vectors=vectors, symbols=symbols, hashes=hashes, index_dir=index_dir)


# ---------------------------------------------------------------------------
# Busca legada pura (ground-truth V4.0.5) — reimplementação do codebase_indexer.search
# ---------------------------------------------------------------------------

def _query_words(query: str) -> set[str]:
    return set(re.findall(r"\w+", query.lower()))


def _target_extension(query: str) -> str | None:
    m = re.search(r"\.([a-zA-Z][a-zA-Z0-9]{0,3})\b", query)
    return "." + m.group(1).lower() if m else None


def legacy_search(
    index: LegacyIndex,
    query_vec: np.ndarray | list[float],
    query: str,
    *,
    top_k: int = 5,
    min_score: float = 0.1,
) -> list[dict[str, Any]]:
    """Porta fiel do `codebase_indexer.search` V4.0.5 (NumPy puro).

    - cosine similarity (dot / norms)
    - filtro de extensão alvo (ex: ".py" na query)
    - filename sovereignty (+100000), palavra no filename (+2.0) / path (+0.5)
    - threshold 0.1
    """
    vectors = index.vectors
    q = np.asarray(query_vec, dtype=float).reshape(1, -1)
    norms = np.linalg.norm(vectors, axis=1)
    q_norm = np.linalg.norm(q)
    if q_norm == 0:
        return []
    similarities = (vectors @ q.T).ravel() / (norms * q_norm)

    target_ext = _target_extension(query)
    query_l = query.lower()
    query_words = _query_words(query)

    for idx, m in enumerate(index.meta):
        path = str(Path(m.get("path", "")).resolve()).lower()
        filename = os.path.basename(path).lower()

        if target_ext and not path.endswith(target_ext):
            similarities[idx] = -1.0
            continue

        stem = filename.split(".")[0]
        if filename in query_l or (len(stem) > 5 and stem in query_l):
            similarities[idx] += 100000.0

        for word in query_words:
            word_l = word.lower()
            if len(word_l) > 3:
                if word_l in filename:
                    similarities[idx] += 2.0
                elif word_l in path:
                    similarities[idx] += 0.5

    order = np.argsort(similarities)[::-1]
    results = []
    for idx in order[:top_k]:
        if similarities[idx] > min_score:
            results.append({
                "score": float(similarities[idx]),
                "path": index.meta[idx].get("path", ""),
                "metadata": index.meta[idx],
            })
    return results


def legacy_search_symbols(index: LegacyIndex, query: str) -> list[dict[str, str]]:
    """Porta do `search_symbols` V4.0.5: símbolos exatos com 3+ caracteres."""
    results: list[dict[str, str]] = []
    for word in re.findall(r"\w+", query):
        if len(word) < 3:
            continue
        for path in index.symbols.get(word, []):
            results.append({"symbol": word, "path": path})
    return results


# ---------------------------------------------------------------------------
# Migração one-shot → Qdrant
# ---------------------------------------------------------------------------

def _point_id(path: str) -> int:
    """ID determinístico (crc32) — estável entre execuções (não usa hash())."""
    return abs(dense_key(path))


def migrate(
    index: LegacyIndex,
    config: Config | None = None,
    *,
    batch_size: int = 100,
    collection: str | None = None,
) -> int:
    """Migra o índice legado para o Qdrant reusando os vetores dense existentes.

    O sparse BM25 é derivado do rich_content (path + facts + content) — o mesmo
    texto que o legado embebia — então a paridade dense é exata e a busca híbrida
    nova ganha o componente lexical sem re-embedding.

    Retorna o número de pontos migrados.
    """
    cfg = config or Config()
    store = QdrantStore(cfg)
    dim = int(index.vectors.shape[1])
    target = collection or cfg.qdrant_collection_code
    store.ensure_collection(target, dim=dim)

    points: list[dict[str, Any]] = []
    total = 0
    for idx in range(len(index)):
        path = index.meta[idx].get("path", "")
        rich = index.rich_content_for(idx, max_chars=cfg.rich_content_chars)
        point = {
            "id": _point_id(path),
            "vector": {
                "dense": [float(v) for v in index.vectors[idx]],
                "bm25": sparse_vector(sparse_terms(rich)),
            },
            "payload": index.payload_for(idx),
        }
        points.append(point)
        if len(points) >= batch_size:
            store.upsert(target, points)
            total += len(points)
            points = []

    if points:
        store.upsert(target, points)
        total += len(points)
    return total


# ---------------------------------------------------------------------------
# Teste de paridade (top-k legado vs novo)
# ---------------------------------------------------------------------------

def _overlap(a: list[str], b: list[str], k: int) -> float:
    """Overlap do top-k entre duas listas de paths: |A∩B| / k.

    Critério do proposal: "paridade top-k ≥ 80% overlap nos primeiros 5"
    — mede quantas das k posições coincidem, sem penalizar o tamanho
    relativo das listas (Jaccard penalizaria rankings de tamanhos distintos).
    """
    if not a or not b:
        return 0.0
    top_a, top_b = set(a[:k]), set(b[:k])
    if not top_a and not top_b:
        return 1.0
    return len(top_a & top_b) / k


def parity_report(
    index: LegacyIndex,
    config: Config | None = None,
    *,
    queries: Iterable[str],
    top_k: int = 5,
) -> dict[str, Any]:
    """Compara o top-k da busca legada (NumPy) vs a busca híbrida nova (Qdrant).

    Usa os vetores dense existentes como query vectors (amostras do próprio
    índice) — a paridade mede se o ranking novo reproduz o ranking legado,
    não a qualidade dos embeddings (modelo novo entra em `jarvis index`).

    Retorna {overlap_medio, por_query: [{query, overlap, legado: [...], novo: [...]}]}.
    """
    from jarvis.core.rag import HybridSearch  # import tardio p/ evitar ciclo

    cfg = config or Config()
    store = QdrantStore(cfg)
    if not store.is_available():
        raise LegacyIndexError("Qdrant indisponível — paridade exige o serviço ativo")

    search = HybridSearch(cfg)

    per_query: list[dict[str, Any]] = []
    overlaps: list[float] = []
    for query in queries:
        # vetor da query = embedding armazenado do primeiro arquivo cujo path casa
        qvec = None
        for idx, m in enumerate(index.meta):
            if query in m.get("path", ""):
                qvec = index.vectors[idx]
                break
        if qvec is None:
            continue

        legacy = legacy_search(index, qvec, query, top_k=top_k)
        legacy_paths = [r["path"] for r in legacy]

        novo = search.search(
            query,
            top_k=top_k,
            dense_override=[float(v) for v in qvec],
        )
        novo_paths = [h.path for h in novo]

        ov = _overlap(legacy_paths, novo_paths, top_k)
        overlaps.append(ov)
        per_query.append({
            "query": query,
            "overlap": round(ov, 3),
            "legado": legacy_paths,
            "novo": novo_paths,
        })

    return {
        "total_queries": len(overlaps),
        "overlap_medio": round(sum(overlaps) / len(overlaps), 3) if overlaps else 0.0,
        "min_overlap": round(min(overlaps), 3) if overlaps else 0.0,
        "por_query": per_query,
    }
