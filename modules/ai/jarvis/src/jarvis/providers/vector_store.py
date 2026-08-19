"""Provider de busca vetorial — Qdrant via API REST.

Schema de payload por coleção:
- code_index:  { path, facts, filename, content, symbols }
- memories:    { kind, text, source, confidence, created_at, retention_days }
- books:       { book_id, chapter, chunk_index, text }

A busca híbrida (dense + sparse BM25) usa a Universal Query API nativa
(prefetch + fusão RRF): dense ("dense") e sparse ("bm25") — espelho do
algoritmo híbrido do legado (semântico + símbolos + filename) sobre Qdrant.
"""

from __future__ import annotations

import zlib
from typing import Any

import requests

from jarvis.core.config import Config

# dimensões dos embeddings: defaults coerentes com modelos locais comuns
DEFAULT_DIM = 768

# nomes dos vetores na coleção híbrida
DENSE_VECTOR_NAME = "dense"
SPARSE_VECTOR_NAME = "bm25"


class VectorStoreError(RuntimeError):
    pass


def dense_key(term: str) -> int:
    """Hash determinístico (crc32) para termos do sparse vector.

    `hash()` do Python é randomizado por processo (PYTHONHASHSEED), o que
    quebraria a estabilidade entre execuções — crc32 é determinístico.
    """
    return zlib.crc32(term.encode("utf-8"))


class QdrantStore:
    def __init__(self, config: Config | None = None) -> None:
        self._cfg = config or Config()
        self._base = self._cfg.qdrant_url.rstrip("/")
        self._timeout = 10.0

    # --- infra ---

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{self._base}/collections", timeout=2.0)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def _request(self, method: str, path: str, **kwargs: Any) -> dict[str, Any]:
        try:
            resp = requests.request(method, f"{self._base}{path}", timeout=self._timeout, **kwargs)
        except requests.RequestException as exc:
            raise VectorStoreError(f"falha de conexão com Qdrant: {exc}") from exc
        if resp.status_code >= 400:
            raise VectorStoreError(f"Qdrant HTTP {resp.status_code} em {path}: {resp.text[:300]}")
        return resp.json()

    # --- coleções ---

    def ensure_collection(self, name: str, dim: int = DEFAULT_DIM) -> None:
        """Cria a coleção se não existir (dense nomeado + sparse BM25 habilitado)."""
        collections = self._request("GET", "/collections").get("result", {}).get("collections", [])
        if any(c.get("name") == name for c in collections):
            return
        payload = {
            "vectors": {DENSE_VECTOR_NAME: {"size": dim, "distance": "Cosine"}},
            # modifier idf ≈ BM25 real (frequência × IDF) — pesquisa 2026:
            # hybrid + RRF é o padrão; sparse sem IDF é só term frequency
            "sparse_vectors": {SPARSE_VECTOR_NAME: {"modifier": "idf"}},
        }
        self._request("PUT", f"/collections/{name}", json=payload)

    def delete_collection(self, name: str) -> None:
        self._request("DELETE", f"/collections/{name}")

    def info(self, name: str) -> dict[str, Any]:
        return self._request("GET", f"/collections/{name}")

    # --- pontos ---

    @staticmethod
    def _normalize_vector(vector: list[float] | dict[str, Any]) -> dict[str, Any]:
        """Aceita lista (dense simples) ou dict nomeado ({dense, bm25})."""
        if isinstance(vector, list):
            return {DENSE_VECTOR_NAME: vector}
        return vector

    def upsert(self, name: str, points: list[dict[str, Any]]) -> None:
        """points: [{id, vector, payload}] — vector pode ser lista (dense) ou dict nomeado."""
        normalized = []
        for p in points:
            item = dict(p)
            item["vector"] = self._normalize_vector(p["vector"])
            normalized.append(item)
        self._request("PUT", f"/collections/{name}/points", json={"points": normalized})

    def delete_points(self, name: str, ids: list[int]) -> None:
        self._request(
            "POST",
            f"/collections/{name}/points/delete",
            json={"points": ids},
        )

    def search(
        self,
        name: str,
        vector: list[float],
        *,
        top_k: int = 5,
        score_threshold: float | None = None,
        with_payload: bool = True,
    ) -> list[dict[str, Any]]:
        """Busca densa simples sobre o vetor nomeado 'dense'."""
        payload: dict[str, Any] = {
            # /points/search usa NamedVectorStruct: {"name": ..., "vector": [...]}
            "vector": {"name": DENSE_VECTOR_NAME, "vector": vector},
            "limit": top_k,
            "with_payload": with_payload,
        }
        if score_threshold is not None:
            payload["score_threshold"] = score_threshold
        result = self._request("POST", f"/collections/{name}/points/search", json=payload)
        return result.get("result", [])

    def search_hybrid(
        self,
        name: str,
        dense: list[float],
        sparse: dict[str, list[int | float]],
        *,
        top_k: int = 10,
        dense_limit: int = 50,
        sparse_limit: int = 50,
        with_payload: bool = True,
        dense_weight: float = 5.0,
        ext_filter: str | None = None,
    ) -> list[dict[str, Any]]:
        """Busca híbrida nativa: prefetch dense + sparse com fusão RRF.

        `sparse` deve ser {"indices": [...], "values": [...]}.
        O RRF é ponderado com mais peso no dense (o legado V4.0.5 era
        dense-dominante: cosine + boosts de filename/símbolo), evitando
        que o BM25 lexical domine o ranking.

        `ext_filter` (ex: ".py") restringe os prefetches via payload.ext —
        espelho do filtro de extensão que o V4.0.5 aplicava antes do scoring.
        """
        prefetch: list[dict[str, Any]] = [
            {"query": dense, "using": DENSE_VECTOR_NAME, "limit": dense_limit},
            {"query": sparse, "using": SPARSE_VECTOR_NAME, "limit": sparse_limit},
        ]
        if ext_filter:
            payload_filter = {"must": [{"key": "ext", "match": {"value": ext_filter}}]}
            prefetch = [{**p, "filter": payload_filter} for p in prefetch]
        payload: dict[str, Any] = {
            "prefetch": prefetch,
            "query": {"rrf": {"weights": [dense_weight, 1.0]}},
            "limit": top_k,
            "with_payload": with_payload,
        }
        result = self._request("POST", f"/collections/{name}/points/query", json=payload)
        # Query API retorna {"result": {"points": [...]}} (diferente do /points/search)
        inner = result.get("result", {})
        if isinstance(inner, dict):
            return inner.get("points", [])
        return inner if isinstance(inner, list) else []

    def count(self, name: str) -> int:
        result = self._request("POST", f"/collections/{name}/points/count", json={"exact": True})
        return result.get("result", {}).get("count", 0)
