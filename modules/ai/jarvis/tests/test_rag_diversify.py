"""Diversidade por fonte na fusão (MMR-lite) — propriedades determinísticas.

Motivação (medido 18/09): 18 chunks de harness.py no top-100 afundavam a
definição de loop_detector.py para além do rank 100. A penalidade cumulativa
por fonte reordena só quando uma fonte satura o topo. Scores exibidos são os
ajustados (monotônicos) — consumidores não podem assumir score bruto.
"""
from __future__ import annotations

import pytest

from jarvis.core.rag import diversify_by_source


def _hit(path: str, score: float) -> dict:
    return {"score": score, "payload": {"path": path, "content": f"c-{path}-{score}"}}


def test_single_source_preserves_relative_order() -> None:
    hits = [_hit("a.py", 3.0), _hit("a.py", 2.0), _hit("a.py", 1.0)]
    out = diversify_by_source(hits)
    # Ordem relativa preservada; scores ajustados monotonicamente
    # (2.0×0.85, 1.0×0.85²) — re-sort posterior mantém a diversidade.
    assert out[0]["score"] == 3.0
    assert out[0]["payload"]["path"] == "a.py"
    assert out[1]["score"] == pytest.approx(1.7)
    assert out[2]["score"] == pytest.approx(0.7225)


def test_alternates_sources_when_one_floods() -> None:
    # a.py tem os 2 melhores scores, mas b.py saturaria o topo sem diversidade.
    hits = [_hit("a.py", 10.0), _hit("a.py", 9.5), _hit("a.py", 9.0), _hit("b.py", 9.2)]
    out = diversify_by_source(hits, penalty=0.85)
    srcs = [h["payload"]["path"] for h in out]
    assert srcs[0] == "a.py"  # melhor absoluto mantém o topo
    # b.py (9.2) deve preceder o 3º chunk de a.py (9.0 × 0.85 = 7.65)
    assert srcs.index("b.py") < 3


def test_no_source_key_is_never_penalized() -> None:
    hits = [
        {"score": 2.0, "payload": {"content": "sem fonte"}},
        _hit("a.py", 1.9),
        _hit("a.py", 1.8),
    ]
    out = diversify_by_source(hits)
    assert out[0]["payload"]["content"] == "sem fonte"
    assert [h["payload"]["path"] for h in out[1:]] == ["a.py", "a.py"]


def test_scores_adjusted_not_deleted() -> None:
    hits = [_hit("a.py", 5.0), _hit("a.py", 5.0), _hit("a.py", 5.0)]
    out = diversify_by_source(hits, penalty=0.5)
    assert out[0]["score"] == 5.0
    assert out[1]["score"] == 2.5
    assert out[2]["score"] == 1.25


def test_input_not_mutated() -> None:
    hits = [_hit("a.py", 2.0), _hit("b.py", 1.0)]
    original = [dict(h) for h in hits]
    diversify_by_source(hits)
    assert hits == original
