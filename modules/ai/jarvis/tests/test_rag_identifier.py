"""Regression: strong document identifiers survive extra query tokens (19/11)."""

from jarvis.core.rag import strong_query_identifier


def test_cycle9_identifier():
    assert strong_query_identifier("CYCLE-9") == "CYCLE-9"
    assert strong_query_identifier("CYCLE-9 Harbor") == "CYCLE-9"
    assert strong_query_identifier("veredito do CYCLE-9 Harbor BLOCKED") == "CYCLE-9"


def test_arxiv_identifier():
    assert strong_query_identifier("paper 2610.04902 SERA") == "2610.04902"


def test_ordinary_query_unchanged():
    assert strong_query_identifier("como purificar agua") is None
    assert strong_query_identifier("Harbor external calibration") is None
