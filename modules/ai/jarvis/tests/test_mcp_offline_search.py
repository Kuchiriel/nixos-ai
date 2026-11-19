"""A tool `offline_search` no MCP (corpus offline de sobrevivência).

O corpus offline (N.O.M.A.D/Kiwix: remédios, água, abrigo) foi montado para
o ramo **offline da voz** — que fala pelo MCP. Sem estar no ToolRegistry
canônico, a tool existia no `dev.py` e **não** aparecia no MCP: o agente que
fala não conseguia alcançar o corpus.

Os testes são herméticos: o corpus pode ou não estar indexado na máquina, e
a resposta válida é sempre texto (nunca exceção).
"""

from __future__ import annotations

import pytest


@pytest.fixture()
def M():
    from jarvis import mcp_server as m
    return m


def test_tool_is_registered_canonical(M):
    """Nome canônico (sem prefixo): exposto como jarvis_offline_search."""
    nomes = [t["name"] for t in M.JARVIS_TOOLS]
    assert "offline_search" in nomes
    assert "jarvis_offline_search" not in nomes  # nada de prefixo dobrado


def test_schema_documents_the_offline_contract(M):
    schema = next(t for t in M.JARVIS_TOOLS if t["name"] == "offline_search")
    assert schema["inputSchema"]["required"] == ["query"]
    desc = schema["description"].lower()
    assert "offline" in desc and "do not invent" in desc


def test_dispatch_reaches_the_core_helper(M, monkeypatch):
    """O dispatch do MCP chama o helper core (fonte única com o dev.py)."""
    from jarvis.core import offline

    seen = {}

    def fake(query, max_results=5):
        seen["query"] = query
        seen["max_results"] = max_results
        return "Source: offline survival corpus (works without internet)."

    monkeypatch.setattr(offline, "offline_search", fake)
    out = M.call_tool("offline_search", {"query": "purify water", "max_results": 3})
    assert out.startswith("Source: offline survival corpus")
    assert seen == {"query": "purify water", "max_results": 3}


def test_legacy_name_accepted_one_cycle(M, monkeypatch):
    """O nome legado `jarvis_offline_search` ainda é aceito (1 ciclo)."""
    from jarvis.core import offline

    monkeypatch.setattr(offline, "offline_search",
                        lambda query, max_results=5: "OK")
    assert M.call_tool("jarvis_offline_search", {"query": "x"}) == "OK"


def test_helper_never_raises_and_reports_missing_source(monkeypatch):
    """Sem corpus indexado, a resposta é 'NO OFFLINE SOURCE' — nunca exceção."""
    from jarvis.core import offline

    class _Empty:
        def search(self, *_a, **_k):
            return []

    monkeypatch.setattr(
        "jarvis.core.rag.HybridSearch", lambda *_a, **_k: _Empty(), raising=False
    )
    out = offline.offline_search("anything")
    assert out.startswith("NO OFFLINE SOURCE") or out.startswith("ERROR:")


def test_helper_clamps_max_results(monkeypatch):
    """max_results é limitado a 1..10 (o corpus é local, não um crawler)."""
    from jarvis.core import offline

    seen = {}

    class _Fake:
        def search(self, query, top_k=5, collection=None):
            seen["top_k"] = top_k
            seen["collection"] = collection
            return []

    # FTS roda primeiro; forcar fallback para exercitar o clamping do top_k
    import jarvis.core.offline_fts as ofts
    monkeypatch.setattr(ofts, "corpus_path", lambda *a, **k: None)
    monkeypatch.setattr(offline, "_dense_top_score", lambda *a, **k: 1.0)
    monkeypatch.setattr(
        "jarvis.core.rag.HybridSearch", lambda *_a, **_k: _Fake(), raising=False
    )
    offline.offline_search("q", max_results=99)
    assert seen["top_k"] == 10
    # 0/None é falsy -> default 5 (semântica original do dev.py, preservada)
    offline.offline_search("q", max_results=0)
    assert seen["top_k"] == 5
    offline.offline_search("q", max_results=3)
    assert seen["top_k"] == 3


def test_registry_maps_the_legacy_alias_and_the_capability():
    """O registry canônico conhece o alias e marca a tool como read-only."""
    from jarvis.runtime import registry as R

    assert R._CANONICAL_ALIASES.get("jarvis_offline_search") == "offline_search"
    cap, mut, appr = R._TOOL_POLICY["offline_search"]
    assert cap == "knowledge.retrieve"
    assert mut is False and appr == "none"
