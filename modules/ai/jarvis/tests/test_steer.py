"""Steering via arquivo: send/check/stop."""

from __future__ import annotations

from jarvis.core import steer as S


def test_send_check_consumes_once(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    assert S.check_steer() is None
    assert S.send_steer("  vá por ali  ")["ok"] is True
    assert S.check_steer() == "vá por ali"
    assert S.check_steer() is None  # consumo destrutivo


def test_send_empty_rejected(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    assert S.send_steer("   ")["ok"] is False


def test_is_stop_words():
    assert S.is_stop("stop") and S.is_stop("/STOP") and S.is_stop(" Pare ")
    assert not S.is_stop("continue")
