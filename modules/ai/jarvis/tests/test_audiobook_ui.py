"""Tests for audiobook_ui.py — waybar status, dispatch, scan."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


def test_waybar_status_idle():
    """waybar_status returns idle when no bookmark."""
    from jarvis.core.audiobook_ui import waybar_status

    with patch("jarvis.core.audiobook._load_bookmark") as mock:
        mock.return_value = MagicMock(book="", playing=False)
        result = waybar_status()
        assert result["class"] == "audiobook-idle"
        assert result["text"] == ""


def test_waybar_status_playing():
    """waybar_status returns playing state."""
    from jarvis.core.audiobook_ui import waybar_status

    with patch("jarvis.core.audiobook._load_bookmark") as mock:
        mock.return_value = MagicMock(book="LOTM", playing=True, chunk_index=5, total_chunks=100)
        result = waybar_status()
        assert result["class"] == "audiobook-playing"
        assert "LOTM" in result["tooltip"]


def test_waybar_status_paused():
    """waybar_status returns paused state."""
    from jarvis.core.audiobook_ui import waybar_status

    with patch("jarvis.core.audiobook._load_bookmark") as mock:
        mock.return_value = MagicMock(book="LOTM", playing=False, chunk_index=5, total_chunks=100)
        result = waybar_status()
        assert result["class"] == "audiobook-paused"


def test_waybar_status_error():
    """waybar_status handles errors gracefully."""
    from jarvis.core.audiobook_ui import waybar_status

    with patch("jarvis.core.audiobook._load_bookmark", side_effect=Exception("boom")):
        result = waybar_status()
        assert result["class"] == "audiobook-idle"


def test_dispatch_help(tmp_path, monkeypatch):
    """dispatch_audiobook shows help."""
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    from jarvis.core.audiobook_ui import dispatch_audiobook

    result = dispatch_audiobook([])
    assert result == 0


def test_dispatch_unknown():
    """dispatch_audiobook handles unknown command."""
    from jarvis.core.audiobook_ui import dispatch_audiobook

    result = dispatch_audiobook(["unknown_cmd"])
    assert result == 1


def test_dispatch_scan(tmp_path):
    """dispatch_audiobook scan finds books."""
    from jarvis.core.audiobook_ui import dispatch_audiobook

    (tmp_path / "book.txt").write_text("content")
    result = dispatch_audiobook(["scan", str(tmp_path)])
    assert result == 0


def test_dispatch_status(tmp_path, monkeypatch):
    """dispatch_audiobook status returns current state."""
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    from jarvis.core.audiobook_ui import dispatch_audiobook

    result = dispatch_audiobook(["status"])
    assert result == 0


def test_dispatch_waybar(tmp_path, monkeypatch):
    """dispatch_audiobook waybar outputs JSON."""
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    from jarvis.core.audiobook_ui import dispatch_audiobook

    result = dispatch_audiobook(["waybar"])
    assert result == 0


def test_scan_and_notify(tmp_path):
    """scan_and_notify returns message about found books."""
    from jarvis.core.audiobook_ui import scan_and_notify

    (tmp_path / "test.txt").write_text("content")
    result = scan_and_notify(str(tmp_path))
    assert "1" in result  # 1 book found


def test_scan_and_notify_empty(tmp_path):
    """scan_and_notify handles empty directory."""
    from jarvis.core.audiobook_ui import scan_and_notify

    result = scan_and_notify(str(tmp_path))
    assert "Nenhum" in result
