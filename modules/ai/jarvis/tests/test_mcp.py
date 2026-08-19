"""Testes do cliente MCP stdio (providers/mcp.py) com servidor fake."""

import json
import sys

from jarvis.providers.mcp import (
    MCPClient,
    MCPError,
    from_function_call,
    parse_command,
    to_function_tools,
)

FAKE_SERVER = r"""
import json, sys

def respond(msg):
    sys.stdout.write(json.dumps(msg) + "\n")
    sys.stdout.flush()

for line in sys.stdin:
    line = line.strip()
    if not line:
        continue
    try:
        req = json.loads(line)
    except json.JSONDecodeError:
        continue
    if req.get("method") == "initialize":
        respond({"jsonrpc": "2.0", "id": req["id"], "result": {
            "protocolVersion": "2024-11-05",
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "fake", "version": "1.0"},
        }})
    elif req.get("method") == "tools/list":
        respond({"jsonrpc": "2.0", "id": req["id"], "result": {
            "tools": [{
                "name": "echo_tool",
                "description": "Echo a string",
                "inputSchema": {
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            }]
        }})
    elif req.get("method") == "tools/call":
        name = req["params"]["name"]
        args = req["params"]["arguments"]
        if name == "echo_tool":
            respond({"jsonrpc": "2.0", "id": req["id"], "result": {
                "content": [{"type": "text", "text": f"echo: {args.get('text', '')}"}]
            }})
        else:
            respond({"jsonrpc": "2.0", "id": req["id"], "result": {
                "content": [{"type": "text", "text": f"unknown: {name}"}],
                "isError": True,
            }})
    # notifications: sem resposta
"""


def _write_fake_server(tmp_path) -> str:
    path = tmp_path / "fake_mcp.py"
    path.write_text(FAKE_SERVER)
    return str(path)


def test_handshake_and_list_tools(tmp_path) -> None:
    server = _write_fake_server(tmp_path)
    with MCPClient(sys.executable, [server]) as client:
        tools = client.list_tools()
        assert len(tools) == 1
        assert tools[0]["name"] == "echo_tool"


def test_call_tool(tmp_path) -> None:
    server = _write_fake_server(tmp_path)
    with MCPClient(sys.executable, [server]) as client:
        out = client.call_tool("echo_tool", {"text": "hello"})
        assert out == "echo: hello"


def test_call_unknown_tool_raises(tmp_path) -> None:
    server = _write_fake_server(tmp_path)
    with MCPClient(sys.executable, [server]) as client:
        try:
            client.call_tool("nope", {})
            assert False, "deveria lançar MCPError"
        except MCPError:
            pass


def test_parse_command() -> None:
    cmd, args = parse_command("/nix/store/xxx/bin/mcp-nixos")
    assert cmd.endswith("mcp-nixos")
    assert args == []
    cmd, args = parse_command("nix run github:utensils/mcp-nixos --")
    assert cmd == "nix"
    assert args == ["run", "github:utensils/mcp-nixos", "--"]


def test_to_function_tools() -> None:
    mcp_tools = [{
        "name": "nix",
        "description": "Query NixOS",
        "inputSchema": {"type": "object", "properties": {"q": {"type": "string"}}},
    }]
    tools = to_function_tools(mcp_tools)
    assert tools[0]["type"] == "function"
    assert tools[0]["function"]["name"] == "nix"
    assert tools[0]["function"]["parameters"]["properties"]["q"]["type"] == "string"


def test_from_function_call() -> None:
    assert from_function_call("nix", '{"action": "search"}') == {"action": "search"}
    assert from_function_call("nix", "") == {}
    assert from_function_call("nix", "not-json") == {}
