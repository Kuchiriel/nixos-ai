"""A tool rag_search do harness nao pode usar r.text (HybridHit nao tem)."""
from jarvis.cli import dev


class _FakeHit:
    def __init__(self, score, path, payload):
        self.score = score
        self.path = path
        self.payload = payload


def test_rag_search_uses_payload(monkeypatch):
    import jarvis.core.rag as rag_mod

    class _FakeSearch:
        def __init__(self, config=None):
            pass

        def search(self, query, top_k=5):
            return [_FakeHit(0.5, "a/b.py", {"content": "conteudo util"})]

    monkeypatch.setattr(rag_mod, "HybridSearch", _FakeSearch)
    out, _ = dev._execute_tool_call("rag_search", {"query": "x"})
    assert "conteudo util" in out
    assert "a/b.py" in out
