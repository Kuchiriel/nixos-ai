"""Make MCP tools: sem key avisa; run exige confirm; registradas."""


def test_make_no_key(monkeypatch) -> None:
    from jarvis.core import make_ops as M
    monkeypatch.delenv("MAKE_API_KEY", raising=False)
    assert "ausente" in M.handle_make("jarvis_make_scenarios", {})


def test_make_run_needs_confirm() -> None:
    from jarvis.core import make_ops as M
    out = M.handle_make("jarvis_make_run", {"scenario_id": 1})
    assert out.startswith("ERROR") and "confirm=true" in out


def test_make_tools_registered() -> None:
    from jarvis import mcp_server as S
    names = [t["name"] for t in S.JARVIS_TOOLS]
    for n in ("jarvis_make_scenarios", "jarvis_make_scenario_get",
              "jarvis_make_executions", "jarvis_make_run"):
        assert n in names


def test_make_call_dispatch(monkeypatch) -> None:
    from jarvis import mcp_server as S
    monkeypatch.delenv("MAKE_API_KEY", raising=False)
    assert "ausente" in S.call_tool("jarvis_make_scenarios", {})


def test_make_summarize() -> None:
    from jarvis.core.make_ops import _summarize_scenarios
    out = _summarize_scenarios([{"id": 1, "name": "X", "isActive": True}])
    assert "1 | X | ATIVO" in out
