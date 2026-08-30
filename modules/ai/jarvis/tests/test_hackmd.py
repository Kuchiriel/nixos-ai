"""Tests for hackmd.py — pure functions and token retrieval (mocked network)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest


def test_get_token_from_env(monkeypatch):
    """_get_token reads from HMD_API_ACCESS_TOKEN env var."""
    from jarvis.core.hackmd import _get_token

    monkeypatch.setenv("HMD_API_ACCESS_TOKEN", "test-token-123")
    assert _get_token() == "test-token-123"


def test_get_token_from_config(tmp_path, monkeypatch):
    """_get_token reads from ~/.hackmd/config.json."""
    from jarvis.core.hackmd import _get_token

    monkeypatch.delenv("HMD_API_ACCESS_TOKEN", raising=False)
    config_dir = tmp_path / ".hackmd"
    config_dir.mkdir()
    config_file = config_dir / "config.json"
    config_file.write_text(json.dumps({"accessToken": "config-token-456"}))

    with patch("pathlib.Path.home", return_value=tmp_path):
        assert _get_token() == "config-token-456"


def test_get_token_missing(monkeypatch):
    """_get_token returns None when no token available."""
    from jarvis.core.hackmd import _get_token

    monkeypatch.delenv("HMD_API_ACCESS_TOKEN", raising=False)
    with patch("pathlib.Path.home", return_value=Path("/nonexistent")):
        assert _get_token() is None


def test_headers_with_token(monkeypatch):
    """_headers returns proper auth headers."""
    from jarvis.core.hackmd import _headers

    monkeypatch.setenv("HMD_API_ACCESS_TOKEN", "my-token")
    h = _headers()
    assert h["Authorization"] == "Bearer my-token"
    assert "Content-Type" in h


@patch("jarvis.core.hackmd.requests.post")
@patch("jarvis.core.hackmd._get_token", return_value="fake-token")
def test_create_nightwatch_report(mock_token, mock_post):
    """create_nightwatch_report formats report correctly."""
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"noteId": "test-123", "title": "Nightwatch Report"}
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    from jarvis.core.hackmd import create_nightwatch_report

    result = create_nightwatch_report("All tests passed", cycle=3)
    assert isinstance(result, dict)
    assert "title" in result or "content" in result
    mock_post.assert_called_once()


@patch("jarvis.core.hackmd.requests.post")
@patch("jarvis.core.hackmd._get_token", return_value="fake-token")
def test_create_knowledge_entry(mock_token, mock_post):
    """create_knowledge_entry formats entry correctly."""
    mock_resp = MagicMock()
    mock_resp.status_code = 201
    mock_resp.json.return_value = {"noteId": "test-456", "title": "Test Title"}
    mock_resp.raise_for_status = MagicMock()
    mock_post.return_value = mock_resp

    from jarvis.core.hackmd import create_knowledge_entry

    result = create_knowledge_entry("Test Title", "Test content", tags=["test", "ai"])
    assert isinstance(result, dict)
    mock_post.assert_called_once()


@patch("jarvis.core.hackmd._get_token", return_value=None)
def test_list_notes_no_token(mock_token):
    """list_notes raises ValueError when no token."""
    from jarvis.core.hackmd import list_notes

    with pytest.raises(ValueError, match="token not configured"):
        list_notes()


@patch("jarvis.core.hackmd._get_token", return_value=None)
def test_get_note_no_token(mock_token):
    """get_note raises ValueError when no token."""
    from jarvis.core.hackmd import get_note

    with pytest.raises(ValueError, match="token not configured"):
        get_note("test-id")
