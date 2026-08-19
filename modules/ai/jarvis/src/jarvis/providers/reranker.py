"""Cliente do endpoint `/rerank` do llama-server (Fase 10 — RAG SOTA).

O `llama-server` com `--rerank` carrega um modelo cross-encoder
(bge-reranker-v2-m3 GGUF, do store) e expõe `/rerank`:
`POST {"query": "...", "documents": ["..."]}` → `{"results": [{"index": 0,
"relevance_score": 0.9, ...}]}`.

Uso no JARVIS: o `HybridSearch` roda o re-rank híbrido (RRF + boosts V4.0.5)
e, opcionalmente, reordena com o cross-encoder — o reranker vê a query + o
conteúdo armazenado de cada candidato e devolve scores de relevância real.

Tolerante a falhas: se o serviço não estiver de pé (lab/host sem o serviço
ativado), o RAG segue funcionando sem o rerank (fallback silencioso).
"""

from __future__ import annotations

from typing import Any

import requests


class RerankerError(RuntimeError):
    pass


class Reranker:
    """Reranker cross-encoder via llama.cpp /rerank."""

    def __init__(self, base_url: str | None = None, *, timeout: float = 30.0) -> None:
        self._base = (base_url or "http://127.0.0.1:8082").rstrip("/")
        self._timeout = timeout

    def is_available(self) -> bool:
        try:
            resp = requests.get(f"{self._base}/health", timeout=2.0)
            return resp.status_code == 200
        except requests.RequestException:
            return False

    def rerank(self, query: str, documents: list[str], *, top_k: int | None = None) -> list[float]:
        """Reranka `documents` contra `query`. Retorna scores na mesma ordem.

        Levanta `RerankerError` se o serviço falhar — quem chama decide o
        fallback (o RAG usa: erro → segue sem rerank).
        """
        if not documents:
            return []
        payload: dict[str, Any] = {"query": query, "documents": documents}
        if top_k is not None:
            payload["top_n"] = top_k
        try:
            resp = requests.post(f"{self._base}/rerank", json=payload, timeout=self._timeout)
            resp.raise_for_status()
            data = resp.json()
        except (requests.RequestException, requests.HTTPError, ValueError) as exc:
            raise RerankerError(f"rerank falhou: {exc}") from exc

        results = data.get("results", [])
        if not results:
            raise RerankerError("rerank sem resultados")
        # results vem ordenado por score; mapeia index → score preservando a ordem
        scores = [0.0] * len(documents)
        for item in results:
            idx = item.get("index")
            if isinstance(idx, int) and 0 <= idx < len(documents):
                scores[idx] = float(item.get("relevance_score", 0.0))
        return scores
