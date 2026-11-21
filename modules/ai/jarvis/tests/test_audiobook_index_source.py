"""Tests for explicit source selection in the audiobook RAG indexer."""

from pathlib import Path


class _FakeStore:
    def __init__(self):
        self.points = []

    def ensure_collection(self, name, dim=None):
        return None

    def upsert(self, name, points):
        self.points.extend(points)


class _FakeLLM:
    def embed(self, text):
        return [0.1, 0.2, 0.3]


def test_index_book_uses_explicit_source_path(tmp_path, monkeypatch):
    import jarvis.core.audiobook as audiobook

    store = _FakeStore()
    monkeypatch.setattr(
        "jarvis.providers.vector_store.QdrantStore", lambda cfg: store
    )
    monkeypatch.setattr("jarvis.providers.llm.LLMClient", lambda cfg: _FakeLLM())

    source = tmp_path / "paper.md"
    source.write_text("digest text", encoding="utf-8")
    monkeypatch.setattr(audiobook, "extract_text", lambda path: "digest text")
    monkeypatch.setattr(
        audiobook,
        "_find_book",
        lambda name, books_dir=None: (_ for _ in ()).throw(
            AssertionError("source_path must bypass stem lookup")
        ),
    )

    result = audiobook.index_book("paper", source_path=source)

    assert result["ok"] is True
    assert result["chunks"] == 1
    assert store.points[0]["payload"]["book"] == "paper"


def test_sweep_books_indexes_digest_file_not_same_stem_pdf(tmp_path, monkeypatch):
    import jarvis.core.audiobook as audiobook

    books = tmp_path / "Books"
    papers = books / "papers"
    papers.mkdir(parents=True)
    pdf = books / "same-stem.pdf"
    digest = papers / "same-stem.md"
    pdf.write_bytes(b"%PDF-1.4 test")
    digest.write_text("digest text", encoding="utf-8")

    monkeypatch.setattr(audiobook, "BOOKS_DIR_DEFAULT", books)
    monkeypatch.setattr(audiobook, "BOOKS_INGEST_LOG", tmp_path / "books.jsonl")
    indexed_sources: list[Path] = []

    def fake_index_book(name, books_dir=None, *, source_path=None, **kwargs):
        assert source_path is not None
        indexed_sources.append(Path(source_path))
        return {"ok": True, "chunks": 1}

    monkeypatch.setattr(audiobook, "index_book", fake_index_book)

    result = audiobook.sweep_books(limit=3)

    assert result["ok"] is True
    assert pdf in indexed_sources
    assert digest in indexed_sources
