"""Unit tests for the WebUI MCP bridge (/api/mcp/tools|call)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from fastapi import HTTPException

from jarvis.webui import api as webui_api


def test_tools_list_shape():
    tools = webui_api.mcp_tools()
    assert len(tools) >= 20
    names = {t["name"] for t in tools}
    assert "jarvis_execute" in names
    assert "jarvis_rag_search" in names
    by_name = {t["name"]: t for t in tools}
    assert by_name["jarvis_execute"]["write"] is True
    assert by_name["jarvis_rag_search"]["write"] is False


def test_unknown_tool_404():
    with pytest.raises(HTTPException) as ei:
        webui_api.mcp_call("nope_tool", webui_api.McpCallRequest(arguments={}))
    assert ei.value.status_code == 404


def test_write_gate_403():
    with pytest.raises(HTTPException) as ei:
        webui_api.mcp_call(
            "jarvis_execute",
            webui_api.McpCallRequest(arguments={"cmd": "echo hi"}, approve=False),
        )
    assert ei.value.status_code == 403


def test_approved_exec_and_audit():
    webui_api._event_queues.clear()
    import queue
    q: queue.Queue = queue.Queue()
    webui_api._event_queues.append(q)
    try:
        r = webui_api.mcp_call(
            "jarvis_execute",
            webui_api.McpCallRequest(arguments={"cmd": "echo hi-mcp"}, approve=True),
        )
        assert r["isError"] is False
        assert "hi-mcp" in r["result"]
        evt = q.get_nowait()
        assert evt["type"] == "mcp_call"
        assert evt["tool"] == "jarvis_execute"
    finally:
        webui_api._event_queues.clear()


def test_read_tool_no_approval():
    r = webui_api.mcp_call(
        "jarvis_vault_list", webui_api.McpCallRequest(arguments={})
    )
    assert r["isError"] is False
