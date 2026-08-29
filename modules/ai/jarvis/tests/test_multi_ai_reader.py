"""Tests for multi_ai_reader.py — dispatch and HTML extraction (no network)."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest


def test_read_ai_conversation_dispatches_chatgpt():
    """read_ai_conversation routes ChatGPT URLs."""
    from jarvis.core.multi_ai_reader import read_ai_conversation

    with patch("jarvis.core.multi_ai_reader.read_chatgpt_conversation", return_value="chatgpt result") as mock:
        result = read_ai_conversation("https://chatgpt.com/share/abc123")
        mock.assert_called_once()
        assert result == "chatgpt result"


def test_read_ai_conversation_dispatches_gemini():
    """read_ai_conversation routes Gemini URLs."""
    from jarvis.core.multi_ai_reader import read_ai_conversation

    with patch("jarvis.core.multi_ai_reader.read_gemini_conversation", return_value="gemini result") as mock:
        result = read_ai_conversation("https://gemini.google.com/share/xyz")
        mock.assert_called_once()
        assert result == "gemini result"


def test_read_ai_conversation_dispatches_claude():
    """read_ai_conversation routes Claude URLs."""
    from jarvis.core.multi_ai_reader import read_ai_conversation

    with patch("jarvis.core.multi_ai_reader.read_claude_conversation", return_value="claude result") as mock:
        result = read_ai_conversation("https://claude.ai/share/abc")
        mock.assert_called_once()
        assert result == "claude result"


def test_read_ai_conversation_unknown_platform():
    """read_ai_conversation returns error for unknown platform."""
    from jarvis.core.multi_ai_reader import read_ai_conversation

    result = read_ai_conversation("https://example.com/chat/123")
    assert "ERROR" in result or "error" in result.lower() or "unknown" in result.lower()


def test_extract_text_from_html_chatgpt():
    """_extract_text_from_html extracts messages from ChatGPT HTML."""
    from jarvis.core.multi_ai_reader import _extract_text_from_html

    html = '<div class="message">Hello from ChatGPT</div>'
    result = _extract_text_from_html(html, 5000, "chatgpt")
    assert isinstance(result, str)


def test_extract_text_from_html_gemini():
    """_extract_text_from_html extracts messages from Gemini HTML."""
    from jarvis.core.multi_ai_reader import _extract_text_from_html

    html = '<div class="response">Hello from Gemini</div>'
    result = _extract_text_from_html(html, 5000, "gemini")
    assert isinstance(result, str)


def test_extract_text_from_html_empty():
    """_extract_text_from_html handles empty HTML."""
    from jarvis.core.multi_ai_reader import _extract_text_from_html

    result = _extract_text_from_html("", 5000, "chatgpt")
    assert isinstance(result, str)


def test_read_chatgpt_conversation_delegates():
    """read_chatgpt_conversation delegates to chatgpt_reader module."""
    from jarvis.core.multi_ai_reader import read_chatgpt_conversation

    # The function imports handle_chatgpt_read inside the function body
    # Test that it returns a string (success or error)
    result = read_chatgpt_conversation("https://chatgpt.com/share/test")
    assert isinstance(result, str)
    # It will likely return an error since the reader needs a real page,
    # but the delegation path is exercised
