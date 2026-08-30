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


def test_dispatch_help(tmp_path, monkeypatch):
    """dispatch returns help on empty args."""
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    from jarvis.core.audiobook import dispatch

    result = dispatch([])
    assert isinstance(result, str)
    assert len(result) > 0


def test_dispatch_status(tmp_path, monkeypatch):
    """dispatch status returns current state."""
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "state"))
    from jarvis.core.audiobook import dispatch

    result = dispatch(["status"])
    assert isinstance(result, str)


# --- SFX tests ---


def test_detect_sfx_rain():
    """detect_sfx finds rain keyword."""
    from jarvis.core.audiobook import detect_sfx

    text = "The rain fell heavily on the ancient roof."
    sfx = detect_sfx(text)
    keywords = [kw for kw, _ in sfx]
    assert "rain" in keywords


def test_detect_sfx_multiple():
    """detect_sfx finds multiple effects."""
    from jarvis.core.audiobook import detect_sfx

    text = "Thunder boomed as the wind howled through the forest."
    sfx = detect_sfx(text)
    keywords = [kw for kw, _ in sfx]
    assert "thunder" in keywords
    assert "wind" in keywords
    assert "forest" in keywords


def test_detect_sfx_none():
    """detect_sfx returns empty for plain text."""
    from jarvis.core.audiobook import detect_sfx

    sfx = detect_sfx("The quick brown fox jumps over the lazy dog.")
    assert sfx == []


def test_detect_sfx_dedup():
    """detect_sfx deduplicates keywords."""
    from jarvis.core.audiobook import detect_sfx

    text = "rain rain rain"
    sfx = detect_sfx(text)
    keywords = [kw for kw, _ in sfx]
    assert keywords.count("rain") == 1


def test_sfx_map_has_entries():
    """SFX_MAP is not empty."""
    from jarvis.core.audiobook import SFX_MAP

    assert len(SFX_MAP) > 10


@pytest.mark.skipif(
    not (Path.home() / ".local/share/jarvis/sounds").exists(),
    reason="SFX sounds not installed (only available outside Nix sandbox)"
)
def test_sounds_dir_exists():
    """SOUNDS_DIR exists after install_sfx."""
    from jarvis.core.audiobook import SOUNDS_DIR

    assert SOUNDS_DIR.exists()
    ogg_files = list(SOUNDS_DIR.rglob("*.ogg"))
    assert len(ogg_files) > 0


def test_extract_text_str_path(tmp_path):
    """extract_text accepts string paths."""
    from jarvis.core.audiobook import extract_text

    # Test with a real file
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello world")
    result = extract_text(str(test_file))
    assert "Hello world" in result
    
    # Test with non-existent file (should not crash)
    result = extract_text(str(tmp_path / "nonexistent.txt"))
    assert result == ""


def test_ocr_pdf_fallback(tmp_path):
    """_ocr_pdf handles missing pytesseract gracefully."""
    from jarvis.core.audiobook import _ocr_pdf

    # Create a minimal PDF-like file (won't be valid, but tests the fallback)
    fake_pdf = tmp_path / "fake.pdf"
    fake_pdf.write_bytes(b"%PDF-1.4 fake")
    result = _ocr_pdf(fake_pdf)
    # Should not crash, may return empty string
    assert isinstance(result, str)


# --- Chapter detection tests ---


def test_detect_chapters():
    """detect_chapters finds chapter headers."""
    from jarvis.core.audiobook import detect_chapters

    text = """Some intro text.

CAPÍTULO 1: The Beginning
It was a dark and stormy night.

CAPÍTULO 2: The Discovery
He found a mysterious artifact.
"""
    chapters = detect_chapters(text)
    assert len(chapters) == 2
    assert chapters[0]["num"] == 1
    assert chapters[1]["num"] == 2


def test_detect_chapters_english():
    """detect_chapters handles English chapter headers."""
    from jarvis.core.audiobook import detect_chapters

    text = """Chapter 1: The Beginning
Some text here.

Chapter 2: The End
More text.
"""
    chapters = detect_chapters(text)
    assert len(chapters) == 2


def test_detect_chapters_empty():
    """detect_chapters returns empty for text without chapters."""
    from jarvis.core.audiobook import detect_chapters

    chapters = detect_chapters("Just some plain text without chapters.")
    assert chapters == []


def test_extract_chapter():
    """extract_chapter returns the correct chapter text."""
    from jarvis.core.audiobook import extract_chapter

    text = """Intro text.

CAPÍTULO 1: First
First chapter content here.

CAPÍTULO 2: Second
Second chapter content here.
"""
    ch1 = extract_chapter(text, 1)
    assert "First chapter content" in ch1
    assert "Second chapter" not in ch1


def test_extract_chapter_not_found():
    """extract_chapter returns empty for non-existent chapter."""
    from jarvis.core.audiobook import extract_chapter

    text = "CAPÍTULO 1: First\nContent."
    result = extract_chapter(text, 99)
    assert result == ""


def test_list_chapters():
    """list_chapters returns chapter titles."""
    from jarvis.core.audiobook import list_chapters

    text = """CAPÍTULO 1: Carmesim
Text.

CAPÍTULO 2: Situação
More text.
"""
    titles = list_chapters(text)
    assert len(titles) == 2
    assert "CAPÍTULO 1: Carmesim" in titles[0]


def test_skip_toc():
    """skip_toc removes TOC from beginning."""
    from jarvis.core.audiobook import skip_toc

    text = """ÍNDICES
CAPA FRONTAL
CAPA COMPLETA
CAPÍTULO 1: The Beginning
Actual content here.
"""
    clean = skip_toc(text)
    assert "ÍNDICES" not in clean
    assert "CAPÍTULO 1" in clean


def test_search_book_keyword_fallback():
    """search_book falls back to keyword matching when LLM unavailable."""
    from jarvis.core.audiobook import search_book

    text = "The rain fell. Derek stood at the corner. The alchemist poured the liquid."
    results = search_book(text, "Derek", context_chars=500)
    # Should find at least one result via keyword fallback
    assert len(results) >= 1
    assert any("Derek" in r["text"] for r in results)
