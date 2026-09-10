"""RAG de livros: índice hierárquico + busca + resume (store/LLM mockados)."""

from __future__ import annotations


class _FakeStore:
    def __init__(self):
        self.points = []
        self.collections = set()

    def ensure_collection(self, name, dim=None):
        self.collections.add(name)

    def upsert(self, name, points):
        self.points.extend(points)

    def search_hybrid(self, name, dense, sparse, **kw):
        base = self.points[:3] if self.points else [
            {"payload": {"book": "livro", "chapter": i, "title": f"c{i}",
                         "content": f"texto {i}"}} for i in range(3)]
        return [{"score": 0.9, "payload": p["payload"]
                 if "payload" in p else p} for p in base]


class _FakeLLM:
    def embed(self, text):
        return [0.1, 0.2, 0.3]


def _deps(monkeypatch):
    import jarvis.core.audiobook as A
    store = _FakeStore()
    monkeypatch.setattr("jarvis.providers.vector_store.QdrantStore",
                        lambda cfg: store)
    monkeypatch.setattr("jarvis.providers.llm.LLMClient",
                        lambda cfg: _FakeLLM())
    return A, store


def test_index_book_hierarchy(tmp_path, monkeypatch):
    import jarvis.core.audiobook as A0
    A, store = _deps(monkeypatch)
    (tmp_path / "livro.txt").write_text(
        "Capítulo 1\n\n" + "texto " * 400 + "\n\nCapítulo 2\n\n" + "mais " * 400)
    monkeypatch.setattr(A, "_find_book",
                        lambda n, d=None: tmp_path / "livro.txt")
    monkeypatch.setattr(A, "extract_text",
                        lambda p: (tmp_path / "livro.txt").read_text())
    out = A.index_book("livro", books_dir=tmp_path)
    assert out["ok"] is True
    assert out["chunks"] >= 2
    assert all(p["payload"]["book"] == "livro.txt" or "livro" in p["payload"]["book"]
               for p in store.points)
    assert all("chapter" in p["payload"] for p in store.points)


def test_search_books_filters_book(tmp_path, monkeypatch):
    A, store = _deps(monkeypatch)
    hits = A.search_books("consulta")
    assert len(hits) == 3
    assert all("chapter" in h for h in hits)


def test_resume_no_hint_uses_bookmark(tmp_path, monkeypatch):
    import jarvis.core.audiobook as A0
    A, store = _deps(monkeypatch)
    monkeypatch.setattr(A, "_load_bookmark", lambda: A0.BookmarkState(
        book="livro", book_path="x", chunk_index=7, total_chunks=100))
    out = A.resume_book("livro")
    assert out["reason"] == "bookmark"
    assert out["position"] == 7


def test_resume_without_bookmark_starts(tmp_path, monkeypatch):
    import jarvis.core.audiobook as A0
    A, store = _deps(monkeypatch)
    monkeypatch.setattr(A, "_load_bookmark", lambda: A0.BookmarkState())
    out = A.resume_book("livro")
    assert out["reason"] == "start"
    assert out["position"] == 0


def test_resume_without_active_book_errors(tmp_path, monkeypatch):
    import jarvis.core.audiobook as A0
    A, store = _deps(monkeypatch)
    monkeypatch.setattr(A, "_load_bookmark", lambda: A0.BookmarkState())
    out = A.resume_book()
    assert out["ok"] is False
