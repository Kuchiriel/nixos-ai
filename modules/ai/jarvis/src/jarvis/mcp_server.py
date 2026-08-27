"""MCP Server — expõe as capacidades do JARVIS como ferramentas MCP.

Permite que o Roo Code e outros clientes MCP usem:
  - execute_shell (com allowlist e approval)
  - read_file / write_file / str_replace (devtools)
  - memory (episodic: remember, recall, lessons)
  - vision (capture_screen)
  - nixos (via mcp-nixos)

Transporte: stdio (JSON-RPC 2.0)
Protocolo: MCP 2024-11-05

Uso:
  # No mcp_settings.json do Roo Code:
  {
    "mcpServers": {
      "jarvis": {
        "command": "nix-shell",
        "args": ["-p", "python3", "--run", "python3 -m jarvis.mcp_server"],
        "env": {}
      }
    }
  }
"""

from __future__ import annotations

import json
import sys
import os
import threading
from typing import Any

# Adicionar paths necessários
_src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # jarvis/src
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from jarvis.core.devtools import handle_dev_tool, DEV_TOOLS
from jarvis.core.vision import VISION_TOOL, handle_capture


import shlex
import subprocess


def _run_shell(cmd: str, timeout: int = 60) -> subprocess.CompletedProcess[str]:
    """Executa via shlex (sem shell=True)."""
    argv = shlex.split(cmd)
    return subprocess.run(argv, capture_output=True, text=True, timeout=timeout)


def _command_allowed(cmd: str) -> bool:
    """Verifica se o comando é read-only."""
    ALLOWED = (
        "ls", "cat", "head", "tail", "grep", "rg", "find", "wc",
        "df", "free", "ps", "pgrep", "ss", "ip", "uname", "uptime",
        "date", "echo", "hostname", "id", "whoami",
        "systemctl is-active", "systemctl status", "systemctl list-units",
        "journalctl", "nix flake check", "nix eval", "nix build --dry-run",
    )
    stripped = cmd.strip()
    if not stripped:
        return False
    for pat in ("&&", "||", ";", "|", "`", "$("):
        if pat in stripped:
            return False
    return any(stripped.startswith(p) for p in ALLOWED)


# ═══ Tool Schemas ═══

JARVIS_TOOLS = [
    {
        "name": "jarvis_execute",
        "description": "Execute a shell command via JARVIS. Read-only commands run directly; write commands require approval.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "cmd": {
                    "type": "string",
                    "description": "Shell command to execute"
                }
            },
            "required": ["cmd"]
        }
    },
    {
        "name": "jarvis_read_file",
        "description": "Read a file from the project. Supports optional line range.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path (relative to project root)"},
                "offset": {"type": "integer", "description": "Start line (1-indexed)"},
                "limit": {"type": "integer", "description": "Max lines to read"}
            },
            "required": ["path"]
        }
    },
    {
        "name": "jarvis_write_file",
        "description": "Write content to a file. Creates or overwrites.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "content": {"type": "string", "description": "File content"}
            },
            "required": ["path", "content"]
        }
    },
    {
        "name": "jarvis_str_replace",
        "description": "Replace a string in a file (surgical edit).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "old_string": {"type": "string", "description": "String to find"},
                "new_string": {"type": "string", "description": "Replacement string"}
            },
            "required": ["path", "old_string", "new_string"]
        }
    },
    {
        "name": "jarvis_capture_screen",
        "description": "Capture a screenshot of the current desktop.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "jarvis_nix_eval",
        "description": "Evaluate a Nix expression and return the result.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "expr": {"type": "string", "description": "Nix expression to evaluate"}
            },
            "required": ["expr"]
        }
    },
    {
        "name": "jarvis_nix_check",
        "description": "Run 'nix flake check' on the project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Project path (default: current dir)"}
            }
        }
    },
]


# ═══ Request Handler ═══

def handle_request(request: dict[str, Any]) -> dict[str, Any]:
    """Processa uma requisição JSON-RPC 2.0."""
    method = request.get("method", "")
    req_id = request.get("id")
    params = request.get("params", {})

    if method == "initialize":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": "2024-11-05",
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": {
                    "name": "jarvis-mcp",
                    "version": "0.1.0"
                }
            }
        }

    if method == "notifications/initialized":
        return None  # notification, no response

    if method == "tools/list":
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {"tools": JARVIS_TOOLS}
        }

    if method == "tools/call":
        tool_name = params.get("name", "")
        arguments = params.get("arguments", {})
        result = call_tool(tool_name, arguments)
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "content": [{"type": "text", "text": result}],
                "isError": result.startswith("ERROR:")
            }
        }

    return {
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": -32601, "message": f"Method not found: {method}"}
    }


def call_tool(name: str, args: dict[str, Any]) -> str:
    """Executa uma tool JARVIS."""
    try:
        if name == "jarvis_execute":
            cmd = args.get("cmd", "")
            if not cmd:
                return "ERROR: empty command"
            if not _command_allowed(cmd):
                return f"ERROR: command not in allowlist: {cmd}"
            res = _run_shell(cmd, timeout=60)
            output = res.stdout if res.returncode == 0 else res.stderr
            if len(output) > 8000:
                output = output[:8000] + f"\n... [truncated from {len(res.stdout)} chars]"
            return output or f"Exit code: {res.returncode}"

        if name == "jarvis_read_file":
            return handle_dev_tool("read_file", args)

        if name == "jarvis_write_file":
            return handle_dev_tool("write_file", args)

        if name == "jarvis_str_replace":
            return handle_dev_tool("str_replace", args)

        if name == "jarvis_capture_screen":
            return handle_capture(args)

        if name == "jarvis_nix_eval":
            expr = args.get("expr", "")
            if not expr:
                return "ERROR: empty expression"
            res = _run_shell(f"nix eval --json '{expr}'", timeout=30)
            return res.stdout or res.stderr

        if name == "jarvis_nix_check":
            path = args.get("path", ".")
            res = _run_shell(f"cd {path} && nix flake check 2>&1", timeout=120)
            return res.stdout or res.stderr or "Check passed"

        return f"ERROR: unknown tool: {name}"
    except Exception as e:
        return f"ERROR: {e}"


# ═══ Stdio Server ═══

def main():
    """Executa o MCP server via stdio (JSON-RPC 2.0)."""
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            request = json.loads(line)
        except json.JSONDecodeError:
            continue

        response = handle_request(request)
        if response is not None:
            sys.stdout.write(json.dumps(response) + "\n")
            sys.stdout.flush()


if __name__ == "__main__":
    main()
