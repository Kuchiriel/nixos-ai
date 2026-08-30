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
from jarvis.core.vision import VISION_TOOL, handle_capture, observe_screen
from jarvis.core.chatgpt_reader import CHATGPT_READER_TOOL, handle_chatgpt_read
from jarvis.core.multi_ai_reader import MULTI_AI_READER_TOOL, read_ai_conversation
from jarvis.core.hackmd import HACKMD_TOOLS, list_notes as hackmd_list, get_note as hackmd_get, create_note as hackmd_create, update_note as hackmd_update, sync_local_to_hackmd


import subprocess

from jarvis.core.security import command_allowed as _command_allowed, run_shell as _run_shell


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
        "name": "jarvis_observe_screen",
        "description": "Capture screenshot AND analyze it with vision AI. Returns what the model sees on screen. Use this instead of capture_screen when you need to understand the current UI state.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["full", "window"],
                    "description": "Capture mode. Default: full",
                },
                "window_title": {
                    "type": "string",
                    "description": "Window title to capture (for mode=window)",
                },
                "question": {
                    "type": "string",
                    "description": "What to analyze. Default: describe UI state, apps, errors",
                },
            },
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
    {
        "name": "jarvis_read_chatgpt",
        "description": "Read a shared ChatGPT conversation. Extracts all messages using a headless browser.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "description": "ChatGPT share URL"},
                "max_chars": {"type": "integer", "description": "Max chars to return (default: 50000)"}
            },
            "required": ["url"]
        }
    },
    {
        "name": "jarvis_remember",
        "description": "Store a fact or event in episodic memory. Use for things to remember across sessions.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "text": {"type": "string", "description": "What to remember"},
                "category": {"type": "string", "description": "Category: fact, event, decision, error"}
            },
            "required": ["text"]
        }
    },
    {
        "name": "jarvis_recall",
        "description": "Recall memories matching a query. Returns relevant past events and facts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for in memory"},
                "top_k": {"type": "integer", "description": "Max results (default: 5)"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "jarvis_lessons",
        "description": "Recall lessons learned from past errors. Use when encountering a known problem pattern.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Error pattern or problem to find lessons for"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "jarvis_vault_list",
        "description": "List notes in the persistent vault. Use to check what's stored.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "jarvis_vault_write",
        "description": "Write a note to the persistent vault. Use for important findings that should persist.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "name": {"type": "string", "description": "Note filename (without .md)"},
                "content": {"type": "string", "description": "Note content in markdown"}
            },
            "required": ["name", "content"]
        }
    },
    {
        "name": "jarvis_rag_search",
        "description": "Search the project codebase using RAG (semantic search). Returns relevant code snippets and documentation.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "What to search for in the codebase"},
                "collection": {"type": "string", "description": "Collection to search: code, memories, books (default: code)", "enum": ["code", "memories", "books"]},
                "limit": {"type": "integer", "description": "Max results (default: 5)"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "jarvis_rag_index",
        "description": "Index a directory into the RAG system. Use to make code searchable.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory to index (default: current dir)"}
            }
        }
    },
    MULTI_AI_READER_TOOL,
    *HACKMD_TOOLS,
    # Vault Sync tools
    {
        "name": "jarvis_vault_sync_obsidian",
        "description": "Sync JARVIS vault notes to Obsidian vault.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "jarvis_vault_sync_hackmd",
        "description": "Sync vault notes to HackMD.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "jarvis_vault_search_obsidian",
        "description": "Search Obsidian vault using ripgrep.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Search query"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "jarvis_vault_status",
        "description": "Get vault sync status.",
        "inputSchema": {
            "type": "object",
            "properties": {}
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

        if name == "jarvis_observe_screen":
            return observe_screen(args)

        if name == "jarvis_read_chatgpt":
            return handle_chatgpt_read(args)

        if name == "jarvis_read_ai_conversation":
            return read_ai_conversation(args.get("url", ""), args.get("max_chars", 50000))

        if name == "jarvis_hackmd_list":
            notes = hackmd_list(args.get("limit", 20))
            # HackMD API returns 'id' not 'noteId'
            return json.dumps([{"id": n.get("id") or n.get("noteId"), "title": n.get("title"), "updatedAt": n.get("updatedAt")} for n in notes], indent=2)

        if name == "jarvis_hackmd_read":
            note = hackmd_get(args.get("note_id", ""))
            return json.dumps({"title": note.get("title"), "content": note.get("content", "")[:5000]}, indent=2)

        if name == "jarvis_hackmd_write":
            note_id = args.get("note_id")
            if note_id:
                result = hackmd_update(note_id, title=args.get("title"), content=args.get("content", ""))
            else:
                result = hackmd_create(args.get("title", "Untitled"), args.get("content", ""))
            # HackMD API returns 'id' not 'noteId'
            return json.dumps({"noteId": result.get("id") or result.get("noteId"), "title": result.get("title")}, indent=2)

        if name == "jarvis_hackmd_sync":
            result = sync_local_to_hackmd(args.get("path", ""), args.get("title"))
            return json.dumps(result, indent=2)

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

        if name == "jarvis_remember":
            return _handle_remember(args)

        if name == "jarvis_recall":
            return _handle_recall(args)

        if name == "jarvis_lessons":
            return _handle_lessons(args)

        if name == "jarvis_vault_list":
            return _handle_vault_list(args)

        if name == "jarvis_vault_write":
            return _handle_vault_write(args)

        if name == "jarvis_rag_search":
            return _handle_rag_search(args)

        if name == "jarvis_rag_index":
            return _handle_rag_index(args)

        # Vault Sync tools
        if name == "jarvis_vault_sync_obsidian":
            result = _vault_sync_to_obsidian()
            return json.dumps({"synced": len(result), "files": result}, indent=2)
        
        if name == "jarvis_vault_sync_hackmd":
            result = _vault_sync_to_hackmd()
            return json.dumps({"synced": len(result), "results": result}, indent=2)
        
        if name == "jarvis_vault_search_obsidian":
            query = args.get("query", "")
            if not query:
                return "ERROR: empty query"
            result = _vault_read_from_obsidian(query)
            return json.dumps(result, indent=2)
        
        if name == "jarvis_vault_status":
            result = _vault_status()
            return json.dumps(result, indent=2)

        # Proactive Diagnostics
        if name == "jarvis_proactive_check":
            from jarvis.core.watchdog import run_proactive_diagnostics, format_alerts, get_system_summary
            alerts = run_proactive_diagnostics()
            summary = get_system_summary()
            return json.dumps({
                "alerts": format_alerts(alerts),
                "summary": summary,
                "alert_count": len(alerts),
            }, indent=2)

        if name == "jarvis_system_health":
            from jarvis.core.watchdog import get_system_summary
            return json.dumps(get_system_summary(), indent=2)

        # Security Classification
        if name == "jarvis_classify_file":
            from jarvis.core.classify import classify_file
            path = args.get("path", "")
            if not path:
                return "ERROR: empty path"
            result = classify_file(path)
            return json.dumps(result.to_dict(), indent=2)

        if name == "jarvis_classify_directory":
            from jarvis.core.classify import get_security_summary, format_security_summary
            path = args.get("path", ".")
            summary = get_security_summary(path)
            return format_security_summary(summary)

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
        # Fallback: procurar no nix store (usar subprocess sem pipes)
        try:
            import glob
            candidates = glob.glob("/nix/store/*/bin/mcp-nixos")
            if candidates:
                # Sort by version (last = newest)
                candidates.sort()
                mcp_bin = candidates[-1]
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
        return f"ERROR: mcp-nixos failed: {e}"# ═══ Memory Handlers ═══

def _handle_remember(args: dict[str, Any]) -> str:
    """Store a fact or event in episodic memory."""
    text = args.get("text", "")
    if not text:
        return "ERROR: empty text"
    category = args.get("category", "fact")
    try:
        from jarvis.core.memory import EpisodicMemory, MemoryEvent
        em = EpisodicMemory()
        event = MemoryEvent(text=text, kind=category, meta={"source": "mcp"})
        mid = em.remember(event)
        return f"Stored in memory (id={mid}): {text[:100]}..."
    except Exception as e:
        return f"ERROR: remember failed: {e}"


def _handle_recall(args: dict[str, Any]) -> str:
    """Recall memories matching a query."""
    query = args.get("query", "")
    if not query:
        return "ERROR: empty query"
    top_k = args.get("top_k", 5)
    try:
        from jarvis.core.memory import EpisodicMemory
        em = EpisodicMemory()
        results = em.recall(query, top_k=top_k)
        if not results:
            return "No memories found matching the query."
        lines = []
        for r in results:
            lines.append(f"[{r.get('kind', '?')}] {r.get('text', '')[:200]}")
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: recall failed: {e}"


def _handle_lessons(args: dict[str, Any]) -> str:
    """Recall lessons learned from past errors."""
    query = args.get("query", "")
    if not query:
        return "ERROR: empty query"
    try:
        from jarvis.core.memory import EpisodicMemory
        em = EpisodicMemory()
        result = em.lessons(query, top_k=3)
        return result or "No lessons found for this pattern."
    except Exception as e:
        return f"ERROR: lessons failed: {e}"


def _handle_vault_list(args: dict[str, Any]) -> str:
    """List notes in the persistent vault."""
    try:
        from jarvis.core.vault import MemoryVault
        mv = MemoryVault()
        notes = mv.list_notes()
        if not notes:
            return "Vault is empty."
        return "Vault notes:\n" + "\n".join(f"- {n}" for n in notes)
    except Exception as e:
        return f"ERROR: vault_list failed: {e}"


def _handle_vault_write(args: dict[str, Any]) -> str:
    """Write a note to the persistent vault."""
    name = args.get("name", "")
    content = args.get("content", "")
    if not name or not content:
        return "ERROR: name and content required"
    try:
        from jarvis.core.vault import MemoryVault
        mv = MemoryVault()
        note_path = mv.vault_dir / f"{name}.md"
        note_path.parent.mkdir(parents=True, exist_ok=True)
        note_path.write_text(content)
        return f"Note saved: {note_path}"
    except Exception as e:
        return f"ERROR: vault_write failed: {e}"


# ═══ RAG Handlers ═══

def _handle_rag_search(args: dict[str, Any]) -> str:
    """Search the codebase using RAG."""
    query = args.get("query", "")
    if not query:
        return "ERROR: empty query"
    collection = args.get("collection", "code")
    limit = args.get("limit", 5)
    try:
        from jarvis.core.rag import HybridSearch
        from jarvis.core.config import Config
        cfg = Config()
        # Override collection if specified
        if collection == "memories":
            cfg.qdrant_collection_code = cfg.qdrant_collection_memories
        elif collection == "books":
            cfg.qdrant_collection_code = cfg.qdrant_collection_books
        # Check if collection exists, create if not
        import requests
        resp = requests.get(f"{cfg.qdrant_url}/collections/{cfg.qdrant_collection_code}")
        if resp.status_code == 404:
            # Create collection with default vectors
            create_payload = {
                "vectors": {"dense": {"size": 768, "distance": "Cosine"}},
                "sparse_vectors": {"sparse": {"modifier": "Idf"}}
            }
            requests.put(f"{cfg.qdrant_url}/collections/{cfg.qdrant_collection_code}", json=create_payload)
        hs = HybridSearch(config=cfg)
        results = hs.search(query, top_k=limit)
        if not results:
            return "No results found."
        lines = []
        for r in results:
            path = r.path if hasattr(r, 'path') else 'unknown'
            score = r.score if hasattr(r, 'score') else 0
            text = r.text if hasattr(r, 'text') else ''
            lines.append(f"[{score:.2f}] {path}\n{text[:200]}\n")
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: rag_search failed: {e}"


def _handle_rag_index(args: dict[str, Any]) -> str:
    """Index a directory into the RAG system."""
    path = args.get("path", ".")
    try:
        from jarvis.core.rag import HybridIndexer
        hi = HybridIndexer()
        count = hi.index_directory(path)
        return f"Indexed {count} files from {path}"
    except Exception as e:
        error_msg = str(e)
        if "batch size" in error_msg:
            return "ERROR: Embedding server batch size too small (512 tokens). Increase --batch-size in llama-server config."
        return f"ERROR: rag_index failed: {e}"


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


# ===========================================================================
# Vault Sync Tools — ported from nightwatch/vault_sync.py
# ===========================================================================

def _vault_sync_to_obsidian() -> list[str]:
    """Sync JARVIS vault notes to Obsidian vault."""
    from pathlib import Path
    import shutil
    
    VAULT_DIR = Path.home() / "projects/nixos-ai/docs/vault"
    OBSIDIAN_VAULT = Path.home() / "vaults/nixos-ai"
    
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    OBSIDIAN_VAULT.mkdir(parents=True, exist_ok=True)
    
    written = []
    for note in VAULT_DIR.rglob("*.md"):
        dest = OBSIDIAN_VAULT / note.relative_to(VAULT_DIR)
        dest.parent.mkdir(parents=True, exist_ok=True)
        
        content = note.read_text(encoding="utf-8")
        
        # Add frontmatter if not present
        if not content.startswith("---"):
            tags = ["nixos-ai", "jarvis-vault"]
            if "nightwatch" in note.name.lower():
                tags.append("nightwatch")
            frontmatter = f"---\ntags: [{', '.join(tags)}]\nsynced: true\n---\n\n"
            content = frontmatter + content
        
        dest.write_text(content, encoding="utf-8")
        written.append(str(dest))
    
    return written


def _vault_sync_to_hackmd() -> list[dict[str, Any]]:
    """Sync vault notes to HackMD."""
    from pathlib import Path
    
    VAULT_DIR = Path.home() / "projects/nixos-ai/docs/vault"
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    
    results = []
    
    # Get existing HackMD notes
    try:
        existing_notes = hackmd_list(limit=100)
        existing = {n.get("title"): n for n in existing_notes}
    except Exception:
        existing = {}
    
    for note in VAULT_DIR.rglob("*.md"):
        title = note.stem
        content = note.read_text(encoding="utf-8")
        
        # Add vault tag
        if "---" not in content[:10]:
            content = f"---\ntags: [jarvis-vault]\n---\n\n{content}"
        
        try:
            if title in existing:
                # Update existing
                note_id = existing[title].get("id")
                if note_id:
                    hackmd_update(note_id, content=content)
                    results.append({"title": title, "action": "updated"})
            else:
                # Create new
                result = hackmd_create(title, content)
                results.append({"title": title, "action": "created", "id": result.get("id")})
        except Exception as e:
            results.append({"title": title, "action": "error", "error": str(e)})
    
    return results


def _vault_read_from_obsidian(query: str) -> list[dict[str, str]]:
    """Search Obsidian vault using ripgrep."""
    from pathlib import Path
    import subprocess
    
    OBSIDIAN_VAULT = Path.home() / "vaults/nixos-ai"
    if not OBSIDIAN_VAULT.exists():
        return []
    
    try:
        result = subprocess.run(
            ["rg", "-l", "-i", query, str(OBSIDIAN_VAULT)],
            capture_output=True, text=True, timeout=10,
        )
        return [{"path": p, "name": Path(p).stem} for p in result.stdout.splitlines()]
    except Exception:
        return []


def _vault_status() -> dict[str, Any]:
    """Get vault sync status."""
    from pathlib import Path
    
    VAULT_DIR = Path.home() / "projects/nixos-ai/docs/vault"
    OBSIDIAN_VAULT = Path.home() / "vaults/nixos-ai"
    
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    
    local_notes = list(VAULT_DIR.rglob("*.md"))
    obsidian_notes = list(OBSIDIAN_VAULT.rglob("*.md")) if OBSIDIAN_VAULT.exists() else []
    
    sync_file = VAULT_DIR / ".last_sync"
    last_sync = sync_file.read_text().strip() if sync_file.exists() else None
    
    return {
        "local_vault": str(VAULT_DIR),
        "local_vault": str(VAULT_DIR),
        "obsidian_vault": str(OBSIDIAN_VAULT),
        "local_count": len(local_notes),
        "obsidian_count": len(obsidian_notes),
        "last_sync": last_sync,
    }
