"""Contracts C/D — knowledge state + grounding (EXP-J/G)."""
import time
from jarvis.core.knowledge_state import (KnowledgeState, Grounding,
                                         classify_state, classify_grounding,
                                         annotate, KnowledgeRecord)


def test_state_current_historical():
    assert classify_state(time.time()) == KnowledgeState.CURRENT
    assert classify_state(time.time() - 40 * 86400) == KnowledgeState.HISTORICAL
    assert classify_state(None) == KnowledgeState.UNVERIFIED
    assert classify_state(0) == KnowledgeState.UNVERIFIED


def test_superseded_dominates():
    assert classify_state(time.time(), superseded=True) == KnowledgeState.SUPERSEDED


def test_grounding_observed_vs_retrieved():
    assert classify_grounding(None, via_tool=True) == Grounding.OBSERVED
    assert classify_grounding("rag", via_tool=False) == Grounding.RETRIEVED
    assert classify_grounding("model", via_tool=False) == Grounding.INFERRED
    assert classify_grounding(None, via_tool=False) == Grounding.UNKNOWN


def test_annotate_payload():
    rec = annotate({"text": "x", "ts": time.time(), "source": "rag"})
    assert isinstance(rec, KnowledgeRecord)
    assert rec.state == KnowledgeState.CURRENT
    assert rec.grounding == Grounding.RETRIEVED


def test_to_payload_serializable():
    rec = annotate({"text": "y", "ts": time.time() - 1000})
    d = rec.to_payload()
    assert d["state"] == "current"
    assert "grounding" in d