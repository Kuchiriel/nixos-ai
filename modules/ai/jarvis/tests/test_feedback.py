"""Testes da camada de feedback (core/feedback.py)."""

import json

from jarvis.core.feedback import (
    STATUS_FILE,
    clear_status,
    get_status,
    notify,
    play_sound,
    set_status,
    waybar_format,
)


def test_set_and_get_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("jarvis.core.feedback.STATUS_FILE", tmp_path / "status.json")
    set_status("thinking", "buscando...")
    status = get_status()
    assert status["state"] == "thinking"
    assert status["text"] == "buscando..."
    assert "ts" in status


def test_clear_status(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("jarvis.core.feedback.STATUS_FILE", tmp_path / "status.json")
    set_status("error", "algo")
    clear_status()
    assert get_status()["state"] == "idle"


def test_get_status_missing_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("jarvis.core.feedback.STATUS_FILE", tmp_path / "nope.json")
    status = get_status()
    assert status["state"] == "idle"


def test_waybar_format_idle(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("jarvis.core.feedback.STATUS_FILE", tmp_path / "status.json")
    set_status("idle", "")
    out = waybar_format()
    assert out["class"] == "idle"
    assert out["text"].startswith("IDLE")


def test_waybar_format_states(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("jarvis.core.feedback.STATUS_FILE", tmp_path / "status.json")
    for state, icon in [("listening", "LISTEN"), ("thinking", "THINK"), ("error", "ERROR"), ("speaking", "SPEAK")]:
        set_status(state, "contexto")
        out = waybar_format()
        assert out["class"] == state
        assert out["text"].startswith(icon)


def test_waybar_format_invalid_json(tmp_path, monkeypatch) -> None:
    f = tmp_path / "status.json"
    monkeypatch.setattr("jarvis.core.feedback.STATUS_FILE", f)
    f.write_text("{not-json")
    out = waybar_format()
    assert out["class"] == "idle"


def test_notify_returns_false_without_binary(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("jarvis.core.feedback.shutil.which", lambda _: None)
    assert notify("t", "b") is False


def test_play_sound_unknown_name() -> None:
    assert play_sound("nope") is False


def test_status_file_is_json(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr("jarvis.core.feedback.STATUS_FILE", tmp_path / "status.json")
    set_status("done", "ok")
    raw = (tmp_path / "status.json").read_text()
    parsed = json.loads(raw)
    assert parsed["state"] == "done"
    assert parsed["text"] == "ok"
