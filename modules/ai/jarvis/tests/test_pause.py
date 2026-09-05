"""Unit tests for the global pause signal (nightwatch.pause)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest

import nightwatch.pause as P


@pytest.fixture
def flag(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "PAUSE_FILE", tmp_path / "PAUSED")
    return tmp_path / "PAUSED"


def test_pause_resume_roundtrip(flag):
    assert P.is_paused() == (False, "")
    P.pause("OOM test")
    paused, why = P.is_paused()
    assert paused and "OOM test" in why
    assert P.resume() is True
    assert P.is_paused() == (False, "")
    assert P.resume() is False


def test_manual_origin_preserved(flag):
    P.pause("gemini trabalhando", origin="ide")
    _, why = P.is_paused()
    assert why.startswith("ide:")


def test_check_pressure_shape():
    st = P.check_pressure()
    assert st["level"] in ("ok", "warning", "critical")
    assert "full_avg60" in st and "avail_kb" in st
