"""Testes do reranker (Fase 10) — provider + integração no RAG."""

from __future__ import annotations

import pytest
import requests

from jarvis.providers.reranker import Reranker, RerankerError


class _FakeResp:
    def __init__(self, data, status=200):
        self._data = data
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise requests.HTTPError(f"HTTP {self.status_code}")

    def json(self):
        return self._data


def test_rerank_maps_scores_by_index(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=None):
        captured["payload"] = json
        return _FakeResp({
            "results": [
                {"index": 2, "relevance_score": 0.9},
                {"index": 0, "relevance_score": 0.7},
                {"index": 1, "relevance_score": 0.2},
            ]
        })

    monkeypatch.setattr("jarvis.providers.reranker.requests.post", fake_post)
    scores = Reranker("http://x:8082").rerank("q", ["a", "b", "c"])
    assert scores == [0.7, 0.2, 0.9]
    assert captured["payload"] == {"query": "q", "documents": ["a", "b", "c"]}


def test_rerank_empty_documents_returns_empty(monkeypatch):
    monkeypatch.setattr("jarvis.providers.reranker.requests.post", lambda *a, **k: (_ for _ in ()).throw(AssertionError()))
    assert Reranker().rerank("q", []) == []


def test_rerank_raises_on_http_error(monkeypatch):
    def fake_post(url, json=None, timeout=None):
        return _FakeResp({}, status=500)

    monkeypatch.setattr("jarvis.providers.reranker.requests.post", fake_post)
    with pytest.raises(RerankerError):
        Reranker().rerank("q", ["a"])


def test_is_available(monkeypatch):
    monkeypatch.setattr("jarvis.providers.reranker.requests.get",
                        lambda url, timeout=None: _FakeResp({}))
    assert Reranker().is_available() is True

    def fail(url, timeout=None):
        raise requests.ConnectionError("conexão recusada")

    monkeypatch.setattr("jarvis.providers.reranker.requests.get", fail)
    assert Reranker().is_available() is False


def test_rrf_fusion_resolves_rerank_disagreement(monkeypatch):
    """A fusão RRF combina os rankings: o consenso vence quando o cross-encoder
    discorda do híbrido+boost (ex: benchmark.py > router.py por densidade
    lexical). O relevante (pos 0 do boost) deve subir mesmo com rerank baixo.
    """
    from jarvis.core.rag import HybridSearch
    from jarvis.core.config import Config

    boosted = [
        {"score": 3.0, "payload": {"path": "router.py", "content": "roteia a cascata"}},
        {"score": 1.4, "payload": {"path": "benchmark.py", "content": "exercita a cascata inteira"}},
        {"score": 1.3, "payload": {"path": "clean.sh", "content": ""}},
        {"score": 0.9, "payload": {"path": "README.md", "content": ""}},
    ]
    # cross-encoder erra: dá o maior score ao benchmark (densidade lexical)
    rerank_scores = [-1.86, 1.44, -6.79, -6.60]

    def fake_rerank(query, docs, timeout=None):
        return list(rerank_scores)

    monkeypatch.setattr("jarvis.providers.reranker.Reranker.rerank", fake_rerank)
    hs = HybridSearch(Config())
    ranked = hs._rerank_candidates("roteamento da cascata", boosted)
    paths = [h["payload"]["path"] for h in ranked]
    # o relevante (router.py) volta ao topo pelo consenso dos rankings
    assert paths[0] == "router.py"
    assert paths[1] == "benchmark.py"
    # score reflete a fusão (ordem final), não o score cru do rerank
    assert ranked[0]["score"] > ranked[1]["score"]


def test_rrf_fusion_fallback_keeps_order_on_error(monkeypatch):
    """Falha do serviço → ordem original preservada (fallback silencioso)."""
    from jarvis.core.rag import HybridSearch
    from jarvis.core.config import Config

    boosted = [
        {"score": 3.0, "payload": {"path": "a.py", "content": "x"}},
        {"score": 1.0, "payload": {"path": "b.py", "content": "y"}},
    ]

    def fail(query, docs, timeout=None):
        raise requests.ConnectionError("conexão recusada")

    monkeypatch.setattr("jarvis.providers.reranker.Reranker.rerank", fail)
    hs = HybridSearch(Config())
    ranked = hs._rerank_candidates("q", boosted)
    assert [h["payload"]["path"] for h in ranked] == ["a.py", "b.py"]
