"""Tests for audiobook.py — pure functions only (no TTS, no network)."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest


def test_chunk_text_simple():
    """chunk_text splits text into chunks respecting target size."""
    from jarvis.core.audiobook import chunk_text

    text = "Paragraph one.\n\nParagraph two.\n\nParagraph three."
    chunks = chunk_text(text, target_chars=30)
    assert len(chunks) >= 2
    for chunk in chunks:
        assert len(chunk) <= 40  # some slack for paragraph boundaries


def test_chunk_text_empty():
    """chunk_text handles empty text."""
    from jarvis.core.audiobook import chunk_text

    assert chunk_text("") == []


def test_chunk_text_single_paragraph():
    """chunk_text with single paragraph under limit."""
    from jarvis.core.audiobook import chunk_text

    text = "Short text."
    chunks = chunk_text(text, target_chars=1000)
    assert len(chunks) == 1
    assert chunks[0] == "Short text."


def test_chunk_text_long_paragraph():
    """chunk_text splits long paragraph by sentences."""
    from jarvis.core.audiobook import chunk_text

    text = "Sentence one. Sentence two. Sentence three. Sentence four."
    chunks = chunk_text(text, target_chars=30)
    assert len(chunks) >= 2


def test_extract_txt(tmp_path):
    """extract_text reads .txt files."""
    from jarvis.core.audiobook import extract_text

    txt_file = tmp_path / "test.txt"
    txt_file.write_text("Hello world")
    assert extract_text(txt_file) == "Hello world"


def test_extract_text_unsupported(tmp_path):
    """extract_text returns error for unsupported formats."""
    from jarvis.core.audiobook import extract_text

    bad_file = tmp_path / "test.xyz"
    bad_file.write_text("content")
    result = extract_text(bad_file)
    # Returns empty string or error for unsupported formats
    assert result == "" or "ERROR" in result or "error" in result.lower()


def test_scan_books_empty(tmp_path):
    """scan_books returns empty list for empty directory."""
    from jarvis.core.audiobook import scan_books

    books = scan_books(tmp_path)
    assert books == []


def test_scan_books_with_files(tmp_path):
    """scan_books finds .txt and .epub files."""
    from jarvis.core.audiobook import scan_books

    (tmp_path / "book1.txt").write_text("content")
    (tmp_path / "book2.epub").write_text("epub content")
    (tmp_path / "book3.pdf").write_text("pdf content")
    (tmp_path / "ignored.xyz").write_text("unsupported")
    books = scan_books(tmp_path)
    names = [b["name"] for b in books]
    # scan_books strips extension from name
    assert "book1" in names
    assert "book2" in names
    assert "book3" in names  # .pdf now supported
    # .xyz not supported
    assert all("ignored" not in n for n in names)


def test_bookmark_state_dataclass():
    """BookmarkState is a proper dataclass."""
    from jarvis.core.audiobook import BookmarkState

    bs = BookmarkState()
    assert bs.book == ""
    assert bs.book_path == ""
    assert bs.chunk_index == 0


def test_dispatch_help():
    """dispatch returns help on empty args."""
    from jarvis.core.audiobook import dispatch

    result = dispatch([])
    assert isinstance(result, str)
    assert len(result) > 0


def test_dispatch_status():
    """dispatch status returns current state."""
    from jarvis.core.audiobook import dispatch

    result = dispatch(["status"])
    assert isinstance(result, str)
