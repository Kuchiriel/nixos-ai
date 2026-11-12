"""Ponteiro de saida de tool (12/11) — orcamento de contexto, nao janela do modelo.

MEDICAO que originou isto: no historico real da sessao, 20,7 MB de 31,6 MB
(65%) eram partes de tool, e cada turno reenviava ~2,4 MB ao provider
(429/503 do free tier). Truncar perde dado; a saida inteira vai para um
arquivo de estado e o modelo recebe inicio + caminho (arXiv 2511.22729).

A janela do modelo NAO e' tocada por este codigo — ele so decide o que entra
no contexto por turno.
"""

from __future__ import annotations

import json

import pytest

try:
    from jarvis import mcp_server as m
except Exception as exc:  # pragma: no cover - sandbox sem deps do core
    pytest.skip(f"jarvis.mcp_server indisponivel: {exc}", allow_module_level=True)


@pytest.fixture()
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("JARVIS_TOOL_OUTPUT_POINTER_CHARS", "1000")
    monkeypatch.setenv("HOME", str(tmp_path))
    return tmp_path


def test_small_output_passes_through(env):
    text = "ok: pequeno"
    assert m._pointerize_tool_output("execute", text) == text


def test_large_output_goes_to_file_and_keeps_head(env):
    text = "A" * 4000 + "FIM"
    out = m._pointerize_tool_output("execute", text)

    assert out.startswith("A" * 100)
    assert "saida completa" in out and "read_file" in out
    assert "FIM" not in out, "corpo inteiro nao pode entrar no contexto"

    pointer = [p.rstrip(";,)") for p in out.split() if p.startswith(str(env))]
    assert pointer, f"ponteiro ausente em: {out[-160:]}"
    saved = open(pointer[0], encoding="utf-8").read()
    assert saved == text, "arquivo de estado tem que guardar a saida inteira"


def test_zero_limit_disables_pointer(env, monkeypatch):
    monkeypatch.setenv("JARVIS_TOOL_OUTPUT_POINTER_CHARS", "0")
    text = "B" * 5000
    assert m._pointerize_tool_output("execute", text) == text


def test_invalid_limit_falls_back_to_default(env, monkeypatch):
    monkeypatch.setenv("JARVIS_TOOL_OUTPUT_POINTER_CHARS", "nao-e-numero")
    assert m._tool_output_pointer_limit() == m._TOOL_OUTPUT_POINTER_CHARS_DEFAULT


def test_error_prefix_preserved_so_isError_still_works(env):
    text = "ERROR: " + "C" * 2000
    out = m._pointerize_tool_output("execute", text)
    assert out.startswith("ERROR: ")


def test_protocol_tools_call_uses_pointer(env, monkeypatch):
    """O caminho real do MCP (tools/call) tem que aplicar o ponteiro."""
    monkeypatch.setattr(m, "call_tool", lambda name, args: "D" * 3000)
    resp = m.handle_request({
        "jsonrpc": "2.0", "id": 7, "method": "tools/call",
        "params": {"name": "execute", "arguments": {"cmd": "true"}},
    })
    payload = resp["result"]["content"][0]["text"]
    assert len(payload) < 3000
    assert "saida completa" in payload
    assert resp["result"]["isError"] is False


def test_tools_call_meta_also_pointerizes(env, monkeypatch):
    monkeypatch.setattr(m, "call_tool", lambda name, args: json.dumps({"blob": "E" * 4000}))
    out = m._meta_call({"name": "rag_search", "args": {"query": "x"}})
    assert "saida completa" in out
    assert len(out) < 4000
