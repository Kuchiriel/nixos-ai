"""Smoke tests for duplex meta-tool `do` routing (deterministic, hermetic).

These guard the CLI-parity/meta-routing paths added for voice: capability
discovery and MCP calls must route via jarvis-cli, while devtools `tool`
behavior remains intact. All external effects are mocked.
"""
import importlib.util
import json
import sys
from pathlib import Path

import pytest


def _load_duplex():
    for parent in Path(__file__).resolve().parents:
        path = parent / "scripts" / "duplex-voice.py"
        if path.is_file():
            break
    else:
        pytest.skip("scripts/duplex-voice.py não encontrado", allow_module_level=True)
    spec = importlib.util.spec_from_file_location("duplex_voice_do_router", path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules["duplex_voice_do_router"] = mod
    try:
        spec.loader.exec_module(mod)  # type: ignore[union-attr]
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"duplex-voice.py não importável: {exc}", allow_module_level=True)
    return mod


@pytest.fixture()
def dv(monkeypatch):
    mod = _load_duplex()
    calls = []

    def fake_cli(args, timeout=25):
        calls.append(("cli", list(args), timeout))
        return f"CLI_OK {' '.join(map(str, args[:2]))}"

    monkeypatch.setattr(mod, "_jarvis_cli", fake_cli)
    monkeypatch.setattr(mod, "call_tool_safe", lambda name, args: mod.call_tool(name, args))

    orig = mod.call_tool

    def safe(name, args):
        calls.append(("tool", name, dict(args or {})))
        if name == "do":
            return orig(name, args)
        if name == "get_time":
            return "12:34 de 11/11/2026"
        if name == "status":
            return "status: active"
        return f"TOOL_{name}"

    monkeypatch.setattr(mod, "call_tool", safe)
    mod._test_calls = calls
    return mod


def _cli_calls(dv):
    return [c for c in dv._test_calls if c[0] == "cli"]


def test_tools_routes_to_cli_json(dv):
    out = dv.call_tool("do", {"action": "tools", "input": ""})
    assert "CLI_OK tools --json" in out
    assert _cli_calls(dv)[0][1][:2] == ["tools", "--json"]


def test_tools_search_routes_with_query(dv):
    out = dv.call_tool("do", {"action": "tools-search", "input": "session resume"})
    assert "CLI_OK tools-search session" in out
    cli = _cli_calls(dv)[0]
    assert cli[1][0] == "tools-search"
    assert cli[1][1] == "session resume"
    assert cli[1][2] == "--json"


def test_tools_search_aliases(dv):
    dv.call_tool("do", {"action": "search_tools", "input": "memory recall"})
    assert _cli_calls(dv)[0][1] == ["tools-search", "memory recall", "--json"]


def test_tools_search_requires_query(dv):
    out = dv.call_tool("do", {"action": "tools-search", "input": ""})
    assert "ERRO" in out
    assert _cli_calls(dv) == []


def test_mcp_tools_call_routes_to_cli_tool(dv):
    out = dv.call_tool("do", {"action": "tools-call", "input": 'tools_search {"query":"time"}'})
    assert "CLI_OK tool tools_search" in out
    cli = _cli_calls(dv)[0]
    assert cli[1][0] == "tool"
    assert cli[1][1] == "tools_search"
    assert json.loads(cli[1][2]) == {"query": "time"}


def test_mcp_tools_call_wraps_non_json(dv):
    dv.call_tool("do", {"action": "mcp", "input": "tools_search notjson"})
    cli = _cli_calls(dv)[0]
    assert cli[1][1] == "tools_search"
    assert json.loads(cli[1][2]) == {"input": "notjson"}


def test_mcp_tools_call_requires_args(dv):
    out = dv.call_tool("do", {"action": "tools-call", "input": ""})
    assert "ERRO" in out
    assert _cli_calls(dv) == []


def test_devtools_tool_action_preserved(dv, monkeypatch):
    # action "tool" must keep devtools dispatch (not MCP meta-routing)
    import types
    seen = {}

    def fake_hdt(name, args):
        seen["name"] = name
        seen["args"] = args
        return "DEVTOOL_OK"

    mod = types.ModuleType("jarvis.core.devtools")
    mod.handle_dev_tool = fake_hdt
    monkeypatch.setitem(sys.modules, "jarvis.core.devtools", mod)
    out = dv.call_tool("do", {"action": "tool", "input": 'semantic_search {"query":"session"}'})
    assert out == "DEVTOOL_OK"
    assert seen["name"] == "semantic_search"
    assert seen["args"]["query"] == "session"
    assert _cli_calls(dv) == []


def test_session_resume_shapes(dv):
    dv.call_tool("do", {"action": "session_resume", "input": "ses_abc123"})
    dv.call_tool("do", {"action": "session-resume", "input": "~/projects/nixos-ai"})
    dv.call_tool("do", {"action": "resume_session", "input": "fix voice gate"})
    clis = _cli_calls(dv)
    assert clis[0][1][0] == "session-resume"
    assert json.loads(clis[0][1][1])["session_id"] == "ses_abc123"
    assert "directory" in json.loads(clis[1][1][1])
    assert json.loads(clis[2][1][1]) == {"query": "fix voice gate"}


def test_rehydrate_and_jarvis_route(dv):
    dv.call_tool("do", {"action": "rehydrate", "input": "continuar"})
    dv.call_tool("do", {"action": "jarvis", "input": "tools --json"})
    clis = _cli_calls(dv)
    assert clis[0][1][0] == "rehydrate"
    assert json.loads(clis[0][1][1]) == {"task": "continuar"}
    assert clis[1][1] == ["tools", "--json"]


def test_unknown_action_returns_explicit_message(dv):
    out = dv.call_tool("do", {"action": "acao_que_nao_existe", "input": ""})
    assert "desconhecida" in out.lower()
