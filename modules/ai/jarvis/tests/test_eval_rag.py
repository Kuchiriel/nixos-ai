"""Testes do `core.eval_rag` — métricas de qualidade do retrieval com search fake."""

from __future__ import annotations

from types import SimpleNamespace

from jarvis.core.eval_rag import (
    DEFAULT_TOP_K,
    RAG_QUERIES,
    _ndcg_at_k,
    eval_report,
    evaluate,
)


def _hit(path: str) -> SimpleNamespace:
    return SimpleNamespace(path=path)


def _search(ranking: list[str], top_k: int = DEFAULT_TOP_K):
    """Fake search que devolve o ranking dado (truncado em top_k)."""

    def fn(query: str, *, top_k: int = DEFAULT_TOP_K) -> list[SimpleNamespace]:
        return [_hit(p) for p in ranking[:top_k]]

    return fn


def test_ndcg_perfect_ranking():
    # Relevante na posição 1 → NDCG 1.0
    assert _ndcg_at_k(["a.py"], {"a.py"}, 5) == 1.0


def test_ndcg_discounts_lower_positions():
    # Relevante na posição 3 → DCG = 1/log2(4) = 0.5; IDCG = 1.0
    assert _ndcg_at_k(["x.py", "y.py", "a.py"], {"a.py"}, 5) == 0.5


def test_ndcg_missing_relevant_is_zero():
    assert _ndcg_at_k(["x.py"], {"a.py"}, 5) == 0.0


def test_evaluate_metrics_with_fake_search():
    relevant = ["a.py", "b.py"]
    results = evaluate(_search(["a.py", "c.py", "b.py", "d.py"]),
                       queries=[("q", relevant)], top_k=3)
    r = results[0]
    # hits = [a.py, c.py, b.py] → 2 relevantes em top_k=3
    assert r.relevant_found == 2
    assert r.precision == 2 / 3
    assert r.recall == 1.0  # 2/2 relevantes
    # NDCG: pos1=1.0, pos3=1/log2(4)=0.5 → DCG=1.5; IDCG=1+1/log2(3)=1.6309
    assert abs(r.ndcg - 1.5 / 1.6309297535714574) < 1e-6


def test_evaluate_handles_search_error():
    def broken(query: str, *, top_k: int = 5):
        raise RuntimeError("qdrant fora do ar")

    results = evaluate(broken, queries=[("q", ["a.py"])], top_k=5)
    assert results[0].error
    assert results[0].ndcg == 0.0


def test_report_aggregates_averages():
    relevant = ["a.py"]
    report = eval_report(_search(["a.py", "b.py"]),
                         queries=[("q1", relevant), ("q2", relevant)],
                         top_k=5)
    assert report["médias"]["queries"] == 2
    assert report["médias"]["erros"] == 0
    assert report["médias"]["recall_at_k"] == 1.0
    assert report["médias"]["precision_at_k"] == 0.2  # 1/5 por query
    assert report["médias"]["ndcg_at_k"] == 1.0
    assert len(report["por_query"]) == 2


def test_ground_truth_queries_are_well_formed():
    for query, relevant in RAG_QUERIES:
        assert query.strip()
        assert isinstance(relevant, list) and len(relevant) >= 1
        assert all(p.endswith((".py", ".nix")) for p in relevant)
