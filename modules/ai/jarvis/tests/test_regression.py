"""Testes do `core.regression` — comparação contra baseline com tolerâncias."""

from __future__ import annotations

from jarvis.core.regression import (
    QUALITY_TOLERANCE,
    check,
    load_baseline,
    save_baseline,
)


def _base() -> dict:
    return {
        "benchmark": {"total_ms": 1000.0, "rotas": {"fastpath": 10.0, "nixos": 2000.0}},
        "eval_rag": {"top_k": 5, "ndcg_at_k": 0.9, "recall_at_k": 1.0, "precision_at_k": 0.2},
    }


def test_check_ok_when_within_tolerance():
    cur = {
        "benchmark": {"rotas": {"fastpath": 15.0, "nixos": 3500.0}},  # < 2x
        "eval_rag": {"ndcg_at_k": 0.88, "recall_at_k": 1.0, "precision_at_k": 0.2},
    }
    result = check(_base(), cur)
    assert result["ok"] is True
    assert result["problemas"] == []


def test_check_fails_on_latency_regression():
    cur = {
        "benchmark": {"rotas": {"fastpath": 10.0, "nixos": 5000.0}},  # > 2x de 2000
        "eval_rag": {"ndcg_at_k": 0.9, "recall_at_k": 1.0, "precision_at_k": 0.2},
    }
    result = check(_base(), cur)
    assert result["ok"] is False
    assert any("nixos" in p for p in result["problemas"])


def test_check_fails_on_quality_regression():
    cur = {
        "benchmark": {"rotas": {"fastpath": 10.0, "nixos": 2000.0}},
        "eval_rag": {"ndcg_at_k": 0.8, "recall_at_k": 0.9, "precision_at_k": 0.2},
    }
    result = check(_base(), cur)
    assert result["ok"] is False
    assert any("ndcg_at_k" in p for p in result["problemas"])
    assert any("recall_at_k" in p for p in result["problemas"])


def test_check_ignores_missing_routes():
    cur = {
        "benchmark": {"rotas": {"fastpath": 10.0}},  # nixos não medido
        "eval_rag": {"ndcg_at_k": 0.9, "recall_at_k": 1.0, "precision_at_k": 0.2},
    }
    result = check(_base(), cur)
    assert result["ok"] is True


def test_check_tolerance_is_documented():
    # garante que a folga de latência é 2x (contrato do módulo)
    assert QUALITY_TOLERANCE == 0.05


def test_save_and_load_roundtrip(tmp_path):
    p = tmp_path / "b.json"
    save_baseline(_base(), p)
    loaded = load_baseline(p)
    assert loaded["benchmark"]["rotas"]["nixos"] == 2000.0
    assert loaded["eval_rag"]["ndcg_at_k"] == 0.9


def test_load_missing_returns_empty():
    assert load_baseline("/nao/existe.json") == {}
