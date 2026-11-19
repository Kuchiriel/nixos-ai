"""Corpus offline de sobrevivência (fase A do N.O.M.A.D) — rota e tool.

Duas garantias:
  1. a decisão de rota (voz) é PURA e testável sem rede;
  2. a tool `offline_search` existe no harness (`jarvis dev`), com a
     descrição explícita e o caminho da fonte no retorno.
"""
from __future__ import annotations

import jarvis.cli.dev as dev
from jarvis.core.rag import OFFLINE_COLLECTION, offline_route_reason

# ---------------------------------------------------------------------------
# decisão de rota (função pura — sem rede, sem I/O)
# ---------------------------------------------------------------------------

def test_offline_route_catches_survival_keywords() -> None:
    assert offline_route_reason("como purificar água em casa?") == "água"
    assert offline_route_reason("o que fazer em caso de veneno?") == "veneno"
    assert offline_route_reason("primeiros socorros para queimadura") == (
        "primeiros socorros")
    assert offline_route_reason("first aid for a burn") == "first aid"
    assert offline_route_reason("como sobreviver a um blackout") == "blackout"
    assert offline_route_reason("water treatment boil") == "water"
    assert offline_route_reason("poison control ingestion") == "poison"
    assert offline_route_reason("shelter after the flood") == "shelter"


def test_offline_route_ignores_code_questions() -> None:
    assert offline_route_reason("qual script roda o water treatment?") is None
    assert offline_route_reason("em qual commit do repo mudou o rag?") is None
    assert offline_route_reason("leia o paper arxiv sobre RAG") is None
    assert offline_route_reason("") is None


def test_offline_collection_is_its_own_collection() -> None:
    assert OFFLINE_COLLECTION == "offline_survival"
    assert OFFLINE_COLLECTION not in ("code_index", "memories", "books", "vault")


# ---------------------------------------------------------------------------
# tool do harness
# ---------------------------------------------------------------------------

def test_offline_search_tool_is_registered_with_source_path() -> None:
    tools = dev._get_tools(None)
    names = [t["function"]["name"] for t in tools]
    assert "offline_search" in names

    tool = next(t for t in tools if t["function"]["name"] == "offline_search")
    fn = tool["function"]
    desc = fn["description"].lower()
    assert "offline" in desc
    assert "survival" in desc
    assert "source file" in desc

    params = fn["parameters"]
    assert set(params["properties"]) == {"query", "max_results"}
    assert params["required"] == ["query"]
    assert params["properties"]["max_results"]["type"] == "integer"


class _FakeHit:
    def __init__(self, path: str, content: str, score: float = 0.42) -> None:
        self.path = path
        self.score = score
        self.payload = {"path": path, "content": content}


class _FakeSearch:
    def __init__(self, hits: list[_FakeHit]) -> None:
        self._hits = hits
        self.calls: list[dict] = []

    def search(self, query: str, **kwargs):
        self.calls.append({"query": query, **kwargs})
        return self._hits


def test_offline_search_handler_names_the_source_file(monkeypatch) -> None:
    # (19/11) offline_search lives in jarvis.core.offline since c514a1ba;
    # patching rag.HybridSearch made the test hit the REAL corpus and assert
    # a fake path — a false failure that masked the real contract.
    # (19/11) offline_search tries the local FTS corpus FIRST; to test the
    # HybridSearch fallback contract we must force FTS to return no hits.
    # The function imports HybridSearch from jarvis.core.rag INSIDE its body.
    import jarvis.core.offline as offline
    import jarvis.core.offline_fts as ofts
    import jarvis.core.rag as rag

    monkeypatch.setattr(ofts, "corpus_path", lambda *a, **k: None)
    monkeypatch.setattr(offline, "_dense_top_score", lambda *a, **k: 1.0)
    fake = _FakeSearch([_FakeHit("data/offline/kiwix-water-x.md", "boil the water")])
    monkeypatch.setattr(rag, "HybridSearch", lambda config=None: fake)

    out, diff = dev._execute_tool_call("offline_search",
                                       {"query": "água", "max_results": 2})
    assert diff is None
    assert "data/offline/kiwix-water-x.md" in out
    assert "boil the water" in out
    assert fake.calls[0]["collection"] == OFFLINE_COLLECTION
    assert fake.calls[0]["top_k"] == 2


def test_offline_search_handler_says_when_corpus_has_no_source(monkeypatch) -> None:
    import jarvis.core.rag as rag

    monkeypatch.setattr(rag, "HybridSearch", lambda config=None: _FakeSearch([]))

    out, diff = dev._execute_tool_call("offline_search", {"query": "nada disso"})
    assert diff is None
    assert "NO OFFLINE SOURCE" in out
