"""Testes do módulo Vision (core/vision.py)."""

from __future__ import annotations

import os
from pathlib import Path
from unittest.mock import patch

import pytest

from jarvis.core.vision import (
    VISION_TOOL,
    capture_full,
    capture_region,
    capture_window,
    cleanup_old_screenshots,
    handle_capture,
)


# ---------------------------------------------------------------------------
# capture_full
# ---------------------------------------------------------------------------


def test_capture_full_no_display() -> None:
    """Sem display → erro gracioso."""
    with patch.dict(os.environ, {}, clear=True):
        result = capture_full()
        assert result["ok"] is False
        assert "display" in result["error"].lower()


def test_capture_full_no_grim() -> None:
    """Com display mas sem grim → erro gracioso."""
    with patch.dict(os.environ, {"WAYLAND_DISPLAY": "wayland-0"}):
        with patch("jarvis.core.vision._has_binary", return_value=False):
            result = capture_full()
            assert result["ok"] is False
            assert "grim" in result["error"].lower()


# ---------------------------------------------------------------------------
# capture_region
# ---------------------------------------------------------------------------


def test_capture_region_no_display() -> None:
    with patch.dict(os.environ, {}, clear=True):
        result = capture_region()
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# capture_window
# ---------------------------------------------------------------------------


def test_capture_window_no_display() -> None:
    with patch.dict(os.environ, {}, clear=True):
        result = capture_window()
        assert result["ok"] is False


# ---------------------------------------------------------------------------
# cleanup
# ---------------------------------------------------------------------------


def test_cleanup_old_screenshots(tmp_path: Path) -> None:
    """Remove screenshots antigos."""
    # Cria arquivos fake
    old = tmp_path / "jarvis-screenshot-1000.png"
    old.write_bytes(b"fake")
    # Torna antigo (2 horas atrás)
    os.utime(old, (0, 0))
    new = tmp_path / "jarvis-screenshot-9999.png"
    new.write_bytes(b"fake")

    with patch("jarvis.core.vision.SCREENSHOT_DIR", tmp_path):
        removed = cleanup_old_screenshots(max_age_s=3600)
    assert removed == 1
    assert not old.exists()
    assert new.exists()


# ---------------------------------------------------------------------------
# handle_capture (tool handler)
# ---------------------------------------------------------------------------


def test_handle_capture_invalid_mode() -> None:
    result = handle_capture({"mode": "invalid"})
    assert "ERROR" in result
    assert "desconhecido" in result


def test_handle_capture_full_no_display() -> None:
    with patch.dict(os.environ, {}, clear=True):
        result = handle_capture({"mode": "full"})
        assert "ERROR" in result


# ---------------------------------------------------------------------------
# VISION_TOOL definition
# ---------------------------------------------------------------------------


def test_vision_tool_schema() -> None:
    assert VISION_TOOL["type"] == "function"
    assert VISION_TOOL["function"]["name"] == "capture_screen"
    params = VISION_TOOL["function"]["parameters"]
    assert "mode" in params["properties"]
    assert "window_title" in params["properties"]
    assert "mode" in params["required"]
