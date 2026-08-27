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
    {
        "name": "jarvis_nix_search",
        "description": "Search NixOS packages, options, Home Manager, flakes, and more via mcp-nixos. Anti-hallucination: returns real data from nixpkgs.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "description": "Action: search, info, stats, browse, channels, flake-inputs, cache",
                    "enum": ["search", "info", "stats", "browse", "channels", "flake-inputs", "cache"]
                },
                "query": {
                    "type": "string",
                    "description": "Search term or package/option name"
                },
                "source": {
                    "type": "string",
                    "description": "Source: nixos, home-manager, darwin, nixvim, nvf, flakehub, noogle, wiki, nix-dev, nixhub",
                    "enum": ["nixos", "home-manager", "darwin", "nixvim", "nvf", "flakehub", "noogle", "wiki", "nix-dev", "nixhub"]
                },
                "type": {
                    "type": "string",
                    "description": "Type filter: packages, options, programs, package, option, flakes",
                    "enum": ["packages", "options", "programs", "package", "option", "flakes"]
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results (default: 10)"
                },
                "version": {
                    "type": "string",
                    "description": "Specific version (for cache/version queries)"
                },
                "system": {
                    "type": "string",
                    "description": "System filter (for cache queries, e.g. x86_64-linux)"
                }
            },
            "required": ["action"]
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

        if name == "jarvis_nix_search":
            return _handle_nix_search(args)

        return f"ERROR: unknown tool: {name}"
    except Exception as e:
        return f"ERROR: {e}"


def _handle_nix_search(args: dict[str, Any]) -> str:
    """Proxy para mcp-nixos — pesquisa packages/options do nixpkgs.

    Lança o binário mcp-nixos como subprocesso e comunica via JSON-RPC stdio.
    Retorna o texto formatado do resultado.
    """
    import shutil

    # Encontrar mcp-nixos no PATH ou no nix store
    mcp_bin = shutil.which("mcp-nixos")
    if not mcp_bin:
        # Fallback: procurar no nix store
        try:
            res = _run_shell(
                "find /nix/store -name mcp-nixos -type f -path '*/bin/*' 2>/dev/null | sort -V | tail -1",
                timeout=5,
            )
            mcp_bin = res.stdout.strip()
        except Exception:
            pass
    if not mcp_bin:
        return "ERROR: mcp-nixos binary not found"

    action = args.get("action", "search")
    query = args.get("query", "")
    source = args.get("source", "nixos")
    ntype = args.get("type", "packages")
    limit = args.get("limit", 10)
    version = args.get("version", "")
    system = args.get("system", "")

    # Montar chamada MCP via stdin/stdout
    request = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": "nix",
            "arguments": {
                "action": action,
                "query": query,
                "source": source,
                "type": ntype,
                "limit": limit,
            },
        },
    }
    if version:
        request["params"]["arguments"]["version"] = version
    if system:
        request["params"]["arguments"]["system"] = system

    try:
        import subprocess
        proc = subprocess.Popen(
            [mcp_bin],
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            bufsize=1,
        )
        # Initialize handshake
        init_req = {
            "jsonrpc": "2.0", "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "jarvis-mcp", "version": "0.1.0"},
            },
        }
        proc.stdin.write(json.dumps(init_req) + "\n")
        proc.stdin.flush()
        # Read init response
        init_line = proc.stdout.readline()
        # Send initialized notification
        proc.stdin.write(json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}}) + "\n")
        proc.stdin.flush()
        # Send actual request
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()
        # Read response
        response_line = proc.stdout.readline()
        proc.terminate()
        proc.wait(timeout=3)

        response = json.loads(response_line)
        result = response.get("result", {})
        content = result.get("content", [])
        texts = [c.get("text", "") for c in content if c.get("type") == "text"]
        return "\n".join(texts) if texts else json.dumps(result, indent=2)
    except subprocess.TimeoutExpired:
        return "ERROR: mcp-nixos timed out"
    except Exception as e:
        return f"ERROR: mcp-nixos failed: {e}"


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
