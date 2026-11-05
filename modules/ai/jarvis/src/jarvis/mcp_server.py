"""MCP Server — exposes the JARVIS capabilities as MCP tools.

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
import time
from pathlib import Path
from typing import Any

# Adicionar paths necessários
_src_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))  # jarvis/src
if _src_dir not in sys.path:
    sys.path.insert(0, _src_dir)

from jarvis.runtime.registry import ToolRegistry
from jarvis.core.vision import VISION_TOOL, handle_capture, observe_with_fallback as observe_screen
from jarvis.core.vision import observe_file as observe_file_fn
from jarvis.core.chatgpt_reader import CHATGPT_READER_TOOL, handle_chatgpt_read
from jarvis.core.multi_ai_reader import MULTI_AI_READER_TOOL, read_ai_conversation
from jarvis.core.hackmd import HACKMD_TOOLS, list_notes as hackmd_list, get_note as hackmd_get, create_note as hackmd_create, update_note as hackmd_update, sync_local_to_hackmd
from jarvis.core.make_ops import MAKE_TOOLS, handle_make


import subprocess

from jarvis.core.security import command_allowed as _command_allowed, run_shell as _run_shell


# ═══ Tool Schemas ═══

JARVIS_TOOLS = [
    {
        "name": "execute",
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
        "name": "read_file",
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
        "name": "write_file",
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
        "name": "str_replace",
        "description": "Replace a string in a file (surgical edit).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "File path"},
                "old_string": {"type": "string", "description": "String to find"},
                "new_string": {"type": "string", "description": "Replacement string"},
                "allow_multiple": {"type": "boolean", "description": "Allow replacing multiple occurrences (default false)"}
            },
            "required": ["path", "old_string", "new_string"]
        }
    },
    {
        "name": "capture_screen",
        "description": "Capture a screenshot of the current desktop.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "observe_screen",
        "description": "Capture screenshot AND analyze it (vision local → Gemini free → OCR fallback, never fails for missing vision model). Returns what is on screen. Use this instead of capture_screen when you need to understand the current UI state.",
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
                "focus_window": {
                    "type": "boolean",
                    "description": ("Focus the window BEFORE capturing (Hyprland). Always use it "
                                    "with modal=window: without focus, the capture grabs what is "
                                    "BEHIND the window. It also moves the mouse to its centre."),
                },
                "opaque": {
                    "type": "boolean",
                    "description": ("Remove the window transparency before capturing. Without it, "
                                    "grim captures the composited content underneath and the OCR/vision "
                                    "read the wrong window. Recommended with focus_window."),
                },
            },
        }
    },
    {
        "name": "observe_file",
        "description": (
            "Analyze an image FILE on disk (PNG/JPEG) with the vision "
            "cascade (local → Gemini → NVIDIA → OpenRouter → OCR). ZERO "
            "desktop interference: no viewer, no capture — unlike "
            "ver-png+observe_screen, nothing opens on the owner's screen "
            "and nothing is left behind to close. Use this for baselines, "
            "captures from tools/capture-sessao.sh, and any saved "
            "screenshot already on disk."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path of the image file to analyze",
                },
                "question": {
                    "type": "string",
                    "description": (
                        "Structured, region-by-region question. Focused "
                        "questions get reliable answers even from small "
                        "vision models."
                    ),
                },
                "budget": {
                    "type": "number",
                    "description": "Total seconds for the cascade (default 45)",
                },
            },
            "required": ["path"],
        }
    },
    {
        "name": "human_input",
        "description": (
            "WHEN you need to move the mouse, click, type or press keys on the "
            "DESKTOP like a human (game clients, native apps, anything outside "
            "the browser — use jarvis_browser for web pages). Human-like by "
            "design: Bezier mouse paths with jitter, log-normal cadence "
            "(~250ms reaction, ~90ms/keystroke with bursts + pauses), fatigue "
            "modeling. WAYLAND-native (ydotool/uinput; falls back to wtype). "
            "Actions: move (Bezier to x,y), click (x,y + button), type (text), "
            "key (keys like 'space' 'return' 'mod+m'), scroll. Pair with "
            "jarvis_observe_screen (look) + this (act) = closed loop. "
            "NOTE: actions are REAL input to the owner's desktop — say out "
            "loud what you are about to click before clicking; never type "
            "passwords/secrets. Typical script: observe → move/click a UI "
            "element → observe the result. Coordinates come from the "
            "screenshot (1920x1080) 1:1 — measure in pixels, then act."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["move", "click", "type", "key", "scroll"],
                    "description": "What the hand does",
                },
                "x": {"type": "integer", "description": "Target pixel X (move/click; screen is 1920x1080)"},
                "y": {"type": "integer", "description": "Target pixel Y (move/click)"},
                "button": {"type": "string", "enum": ["left", "right", "middle"], "description": "Mouse button (click). Default left"},
                "text": {"type": "string", "description": "Text to type with human cadence (type)"},
                "keys": {"type": "string", "description": "Space-separated keys, e.g. 'mod+m' or 'space' (key)"},
                "dy": {"type": "integer", "description": "Scroll amount in pixels, positive = down (scroll)"},
                "dry_run": {"type": "boolean", "description": "Simulate without touching the desktop (returns the path it would take). Use FIRST to validate coordinates"},
            },
            "required": ["action"],
        },
    },
    {
        "name": "game",
        "description": (
            "WHEN you need to interact with a GAME window on Hyprland: focus "
            "by title (safe — keys NEVER go to the wrong window), press keys "
            "(wtype only; the ydotool key daemon STICKS the user's real key "
            "down-state — incident 10/10), type text with chat-state checks, "
            "click at game coordinates, OCR-locate UI elements, and "
            "prep_observe: REAL fullscreen (mode 0) + focus + walk 2 tiles "
            "to clear the fullscreen render staleness (black/duplicated "
            "sprites until the map moves). For the otclient sandbox: launch "
            "via tools/observe-game.sh in the otclient repo, then call "
            "jarvis_game with action=prep_observe."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string",
                           "enum": ["state", "focus", "key", "type", "click",
                                    "locate", "click_element", "chat_state",
                                    "ensure_chat", "chat_command",
                                    "prep_observe"]},
                "window_title": {"type": "string", "default": "OTClient"},
                "key": {"type": "string"},
                "text": {"type": "string"},
                "element": {"type": "string"},
                "button": {"type": "string"},
                "walk": {"type": "boolean", "default": True}
            },
            "required": ["action"]
        }
    },
    {
        "name": "browser",
        "description": ("WHEN you need to interact with any web page: read, click, fill forms, "
                        "drive menus, or operate the owner's logged-in browser (attach). "
                        "Actions: open, click, fill, press, scroll, extract, wait, attach, "
                        "click_text, menu, shadow, wait_text. Mutations need approval."),
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "Browser action"},
                "url": {"type": "string", "description": "URL (open) or CDP url (attach)"},
                "selector": {"type": "string", "description": "CSS selector (or shadow host)"},
                "text": {"type": "string", "description": "Text (fill/click_text/wait_text/shadow inner)"},
                "key": {"type": "string", "description": "Key for press"},
                "dy": {"type": "integer", "description": "Scroll pixels"},
                "items": {"type": "array", "items": {"type": "string"}, "description": "Menu path"},
                "timeout": {"type": "integer", "description": "Wait ms"},
            },
            "required": ["action"]
        }
    },
    {
        "name": "nix_eval",
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
        "name": "nix_check",
        "description": "Run 'nix flake check' on the project.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Project path (default: current dir)"}
            }
        }
    },
    {
        "name": "nix_search",
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
        "name": "read_chatgpt",
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
        "name": "remember",
        "description": "Store one durable fact/event/decision/error so future sessions and nightwatch can see it. WHEN: at task end, before switching topics, or the moment a non-obvious decision/verdict is made. WHEN NOT: transient chat-only details; secrets (store the NAME only). category=fact|event|decision|error. Returns the memory id.",
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
        "name": "rehydrate",
        "description": (
            "REHYDRATE — the one-call rescue: pinned guards + queue top + latest "
            "HANDOFF + memories/lessons for your task + RAG hits + roster. Call it "
            "FIRST in a new session, right after a compaction, or when a problem "
            "looks like a repeat ('we solved this already'); cheaper than redoing "
            "the diagnosis. WHEN NOT: mid-task with context — for one question use "
            "recall/rag_search/lessons. Do NOT repeat it for the same task: the 2nd "
            "call returns a pointer (loop-breaker). Returns text, no state change."
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "task": {"type": "string", "description": "What you are about to do (the subject to rehydrate)"},
                "limit": {"type": "integer", "description": "Max RAG hits per collection (default: 5)"},
                "include": {
                    "type": "string",
                    "description": "Blocks (default all): queue,handoff,memories,lessons,rag,books,roster",
                },
            },
            "required": ["task"],
        },
    },
    {
        "name": "recall",
        "description": "Search episodic memory for past facts/decisions/errors about a topic. WHEN: before acting on a subject, before asking the human what was decided, before re-deriving a verdict. WHEN NOT: you need code/doc passages (rag_search) or a full session rescue (rehydrate). Returns up to top_k lines; empty means no prior memory — say so and proceed.",
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
        "name": "lessons",
        "description": "Past failures and their fixes (the 'do not repeat this' memory). WHEN (mandatory): a command/test/build FAILED, you are about to RETRY the same thing, or you start unfamiliar/risky work (reboot, kernel/driver, migration, DB). Query with the error text or the action, not the topic. WHEN NOT: happy path. Returns up to 3 lessons; empty means no recorded trap.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Error pattern or problem to find lessons for"}
            },
            "required": ["query"]
        }
    },
    {
        "name": "vault_list",
        "description": "List notes in the persistent vault. Use to check what's stored.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "vault_write",
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
        "name": "rag_search",
        "description": "Semantic search over indexed code/docs/books. WHEN: you do NOT know where something lives or how it is implemented (discovery) — run this BEFORE grepping blindly. WHEN NOT: you already know the path (read it) or you need exact string matching (grep). If the collection is empty, rag_index the dir first. Returns file+line hits.",
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
        "name": "persona",
        "description": "List/select JARVIS personas (roles with tools, policies, model). Call FIRST when a task needs a specialized framing (audit, review, research, implementation). Returns persona details including allowed tools and handoff protocol.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "action": {"type": "string", "description": "list, show, or select (auto-pick by task text)"},
                "persona_id": {"type": "string", "description": "persona id for show (optional)"},
                "task": {"type": "string", "description": "task text for select (optional)"}
            },
            "required": ["action"]
        }
    },
    {
            "name": "rag_index",
            "description": "Index a directory into the RAG collections (code + auto-sweep of Books papers). WHEN: rag_search returned nothing for a tree you are working in, or after large file moves/renames. WHEN NOT: a one-off question about a known file (read it). Returns counts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Directory to index (default: current dir)"}
            }
        }
    },
    {
        "name": "web_search",
        "description": "Search the internet via Tavily. Use for current events, library docs, and anything outside the codebase.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "Question or search terms"},
                "limit": {"type": "integer", "description": "Max results (default: 5)"}
            },
            "required": ["query"]
        }
    },
    {**MULTI_AI_READER_TOOL, "name": MULTI_AI_READER_TOOL["name"].removeprefix("jarvis_")},
    *({**t, "name": t["name"].removeprefix("jarvis_")} for t in HACKMD_TOOLS),
    *({**t, "name": t["name"].removeprefix("jarvis_")} for t in MAKE_TOOLS),
    # Vault Sync tools
    {
        "name": "vault_sync_obsidian",
        "description": "Sync JARVIS vault notes to Obsidian vault.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "vault_sync_hackmd",
        "description": "Sync vault notes to HackMD.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "vault_search_obsidian",
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
        "name": "vault_status",
        "description": "Get vault sync status.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "coord_post",
        "description": "Publish an agent claim/status on the coordination bus "
                       "(a GitHub issue with a coord-json block). Use BEFORE editing "
                       "files: state which files you will touch (files) and what you "
                       "will do (intent). kinds: claim|status|blocked|done|handoff.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "kind": {
                    "type": "string",
                    "description": "claim (vou mexer) | status (progresso) | blocked "
                                   "(travei) | done (terminei) | handoff (passo a bola)",
                    "enum": list(("claim", "status", "blocked", "done", "handoff")),
                },
                "agent": {
                    "type": "string",
                    "description": "Agent identity (default: COORD_AGENT env or jarvis@host)"
                },
                "lane": {"type": "string", "description": "Lane/workstream name"},
                "files": {
                    "type": "string",
                    "description": "Comma-separated file globs this agent will touch "
                                   "(e.g. 'backtest/*,AGENTS.md'). Required for claims: "
                                   "scope overlap is how collisions get detected."
                },
                "intent": {"type": "string", "description": "What you are about to do"},
                "pr": {"type": "integer", "description": "Related PR number"},
                "note": {"type": "string", "description": "Extra note"},
            },
            "required": ["kind"],
        }
    },
    {
        "name": "coord_read",
        "description": "Read the coordination bus: every agent's current claim, "
                       "scope collisions, stale claims and open PRs. Call this before "
                       "starting work and at each milestone.",
        "inputSchema": {
            "type": "object",
            "properties": {}
        }
    },
    {
        "name": "coord_check",
        "description": "Check whether a file scope collides with another agent's active "
                       "claim on the coordination bus. Returns an explicit COLISÃO "
                       "verdict — resolve it before editing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent": {"type": "string", "description": "Agent identity (default: this agent)"},
                "files": {"type": "string", "description": "Comma-separated file globs to check"},
            }
        }
    },
    {
        "name": "coord_roster",
        "description": "List the local agent roster: codename, name, lane, state and the "
                       "one-line context each agent is working on. Read this to know who "
                       "is doing what before starting.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "coord_whoami",
        "description": "Show this agent's card: codename, lane, repo, claimed files and "
                       "current context phrase.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent": {"type": "string", "description": "Roster name (default: this agent)"}
            }
        }
    },
    {
        "name": "coord_set_context",
        "description": "Update this agent's one-line context phrase. Change it whenever "
                       "the subject changes, so peers can tell what you are doing.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "context": {"type": "string", "description": "One line about what you are doing now"},
                "agent": {"type": "string", "description": "Roster name (default: this agent)"}
            },
            "required": ["context"],
        }
    },
    {
        "name": "coord_msg",
        "description": "Send a message to a peer agent by codename or roster name. "
                       "note=True notifies without running their turn; note=False asks "
                       "them to act.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "to": {"type": "string", "description": "Codinome or roster name"},
                "message": {"type": "string", "description": "Message text"},
                "note": {"type": "boolean", "description": "Notify without running their turn (default true)"},
            },
            "required": ["to", "message"],
        }
    },
    {
        "name": "coord_peers",
        "description": "List Tailscale peers reachable from this machine (name, tailnet IP, "
                       "OS, online state) — who you can talk to directly.",
        "inputSchema": {"type": "object", "properties": {}}
    },
    {
        "name": "coord_pending",
        "description": "Return ONLY what is addressed to this agent: messages whose 'to' "
                       "matches your codename or lane, plus claims by other agents whose "
                       "file scope overlaps yours. Incremental via 'since' (feed it the "
                       "bus_updated_at from coord_read). This is the poll endpoint the "
                       "watcher uses to stay in sync without human prompts.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "agent": {"type": "string", "description": "Your roster name (default: COORD_AGENT)"},
                "codename": {"type": "string", "description": "Your human codename (e.g. Onca)"},
                "lane": {"type": "string", "description": "Your lane (lane-wide addressing)"},
                "files": {"type": "string", "description": "Comma-separated globs you own"},
                "since": {"type": "string", "description": "Cursor: only items newer than this timestamp"},
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


# ─── Vault Helper Functions ───────────────────────────────────────────────

def _vault_sync_to_obsidian() -> list[str]:
    """Sync JARVIS vault notes to Obsidian vault."""
    from pathlib import Path
    import shutil
    
    VAULT_DIR = Path.home() / "vaults/projects/nixos-ai"
    OBSIDIAN_VAULT = Path.home() / "vaults/projects"
    
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
    
    VAULT_DIR = Path.home() / "vaults/projects/nixos-ai"
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    
    results = []
    
    try:
        existing_notes = hackmd_list(limit=100)
        existing = {n.get("title"): n for n in existing_notes}
    except Exception:
        existing = {}
    
    for note in VAULT_DIR.rglob("*.md"):
        title = note.stem
        content = note.read_text(encoding="utf-8")
        
        if "---" not in content[:10]:
            content = f"---\ntags: [jarvis-vault]\n---\n\n{content}"
        
        try:
            if title in existing:
                note_id = existing[title].get("id")
                if note_id:
                    hackmd_update(note_id, content=content)
                    results.append({"title": title, "action": "updated"})
            else:
                result = hackmd_create(title, content)
                results.append({"title": title, "action": "created", "id": result.get("id")})
        except Exception as e:
            results.append({"title": title, "action": "error", "error": str(e)})
    
    return results


def _vault_read_from_obsidian(query: str) -> list[dict[str, str]]:
    """Search Obsidian vault using ripgrep (fixed-string, sem regex).

    Vault via JARVIS_OBSIDIAN_VAULT (default ~/vaults/projects) — before
    hardcoded. Failures become [{"error": ...}] observável em vez de []
    silent (it could not tell "no results" from "vault missing").
    """
    from pathlib import Path
    import os
    import subprocess

    OBSIDIAN_VAULT = Path(
        os.environ.get("JARVIS_OBSIDIAN_VAULT", str(Path.home() / "vaults/projects"))
    ).expanduser()
    if not OBSIDIAN_VAULT.exists():
        return [{"error": f"obsidian vault not found: {OBSIDIAN_VAULT}"}]

    try:
        result = subprocess.run(
            ["rg", "-l", "-i", "-F", query, str(OBSIDIAN_VAULT)],
            capture_output=True, text=True, timeout=10,
        )
        return [{"path": p, "name": Path(p).stem} for p in result.stdout.splitlines()]
    except Exception as e:
        return [{"error": f"ripgrep failed: {e}"}]


def _vault_status() -> dict[str, Any]:
    """Get vault sync status."""
    from pathlib import Path
    
    VAULT_DIR = Path.home() / "vaults/projects/nixos-ai"
    OBSIDIAN_VAULT = Path.home() / "vaults/projects"
    
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    
    local_notes = list(VAULT_DIR.rglob("*.md"))
    obsidian_notes = list(OBSIDIAN_VAULT.rglob("*.md")) if OBSIDIAN_VAULT.exists() else []
    
    sync_file = VAULT_DIR / ".last_sync"
    last_sync = sync_file.read_text().strip() if sync_file.exists() else None
    
    return {
        "local_vault": str(VAULT_DIR),
        "obsidian_vault": str(OBSIDIAN_VAULT),
        "local_count": len(local_notes),
        "obsidian_count": len(obsidian_notes),
        "last_sync": last_sync,
    }


def _mcp_mutation_policy() -> str:
    """Mutation policy via MCP (approval gap closed 21/09, authorised):
    auto = current behaviour (the local MCP client is already authenticated);
    deny = mutations require approval (deny with a message, like the Agent).
    Env JARVIS_MCP_MUTATION. Default auto = sem quebra."""
    return os.environ.get("JARVIS_MCP_MUTATION", "auto").lower()


def _mcp_audit(name: str, args: dict[str, Any], rc: int | None) -> None:
    """Best-effort audit of MCP mutations (parity with Agent._log_audit)."""
    try:
        from pathlib import Path as _P
        from jarvis.core.paths import ensure_state_dir
        log = _P(ensure_state_dir()) / "mcp-audit.jsonl"
        with open(log, "a", encoding="utf-8") as f:
            f.write(json.dumps({"ts": __import__("time").time(), "tool": name,
                                "args": str(args)[:300], "rc": rc}) + "\n")
    except Exception:
        pass


def _guarded_mutation(name: str, args: dict[str, Any], fn) -> str:
    if _mcp_mutation_policy() == "deny":
        _mcp_audit(name, args, None)
        return (f"ERROR: {name} needs approval "
                f"(JARVIS_MCP_MUTATION=deny). Path stays inside project jail.")
    try:
        out = fn()
    except Exception as e:
        _mcp_audit(name, args, -1)
        return f"ERROR: {e}"
    _mcp_audit(name, args, 0 if not str(out).startswith("ERROR") else 1)
    return out


def _transport_registry() -> ToolRegistry:
    """Singleton lazy do registry (transporte MCP → nomes/args canônicos)."""
    global _TRANSPORT_REGISTRY
    try:
        _TRANSPORT_REGISTRY
    except NameError:
        _TRANSPORT_REGISTRY = None
    if _TRANSPORT_REGISTRY is None:
        _TRANSPORT_REGISTRY = ToolRegistry.build_default()
    return _TRANSPORT_REGISTRY


def call_tool(name: str, args: dict[str, Any]) -> str:
    """Executes a JARVIS tool.

    Name policy (2026-11-02): the MCP server key is `jarvis`, and opencode
    exposes every MCP tool as `<server-key>_<tool-name>`
    (packages/opencode/src/mcp/catalog.ts). The tools are therefore
    REGISTERED with their canonical names (`recall`, `remember`,
    `rehydrate`, ...) so the exposed name is `jarvis_recall` — matching the
    docs and the injected harness rule, with no doubled prefix. The legacy
    `jarvis_*` names stay accepted here for one deprecation cycle.
    """
    if not name.startswith("jarvis_"):
        name = "jarvis_" + name
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
            _mcp_audit(name, args, res.returncode)
            return output or f"Exit code: {res.returncode}"

        if name == "jarvis_persona":
            from jarvis.core.persona import PersonaRegistry
            reg = PersonaRegistry()
            action = args.get("action", "list")
            if action == "list":
                return reg.summary()
            if action == "show":
                p = reg.get(args.get("persona_id", ""))
                if not p:
                    return "ERROR: persona desconhecida"
                return json.dumps(p.to_dict(), indent=2, ensure_ascii=False, default=str)
            if action == "select":
                p = reg.select_for_task(args.get("task", ""))
                if not p:
                    return "ERROR: nenhuma persona"
                return json.dumps({"selected": p.id, "role": p.role,
                                   "tools": p.tools,
                                   "handoff": "save the context to a file and delegate; "
                                    "the next persona reads the file (saves context)"},
                                  indent=2, ensure_ascii=False, default=str)
            return "ERROR: action inválida (list|show|select)"

        if name in ("jarvis_read_file", "jarvis_write_file",
                      "jarvis_str_replace"):
            # Generic transport via the registry (resolve + declared
            # executor). F2 resurrected str_replace here; the dispatch
            # elimina os branches manuais (F2+).
            reg = _transport_registry()
            if name == "jarvis_read_file":
                out = reg.dispatch(name, args)
                return out if out is not None else f"ERROR: unknown tool: {name}"
            _canon, _targs = reg.resolve(name, args)
            return _guarded_mutation(
                name, _targs,
                lambda: reg.dispatch(name, args)
                or f"ERROR: unknown tool: {name}")

        if name == "jarvis_capture_screen":
            return handle_capture(args)

        if name == "jarvis_observe_screen":
            return observe_screen(args)
        if name == "jarvis_observe_file":
            return observe_file_fn(args)

        if name == "jarvis_human_input":
            from jarvis.core.humanize import human_input
            return human_input(args)

        if name == "jarvis_game":
            from jarvis.core.gameinput import handle as game_handle
            return game_handle(args)

        if name == "jarvis_browser":
            from jarvis.core.browser import handle_browser
            return handle_browser(args)

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

        if name.startswith("jarvis_make_"):
            # handle_make still speaks the legacy prefixed names (its module is
            # owned by another lane); the MCP surface is canonical.
            return handle_make(name, args)

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

        if name == "jarvis_rehydrate":
            return _handle_rehydrate(args)

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

        if name == "jarvis_web_search":
            from jarvis.core.websearch import web_search
            query = args.get("query", "")
            try:
                max_results = int(args.get("limit", args.get("max_results", 5)) or 5)
            except (TypeError, ValueError):
                max_results = 5
            return web_search(query, max_results=max_results)

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
        
        if name in ("jarvis_coord_post", "coord_post"):
            def _do_coord_post() -> str:
                from jarvis.core.coord import post
                files = args.get("files", "")
                if isinstance(files, list):
                    files = ",".join(str(f) for f in files)
                pr = args.get("pr")
                return post(
                    kind=args.get("kind", "claim"),
                    agent=args.get("agent") or None,
                    lane=args.get("lane", ""),
                    files=files,
                    intent=args.get("intent", ""),
                    pr=int(pr) if str(pr or "").strip().isdigit() else None,
                    note=args.get("note", ""),
                    head=args.get("head", ""),
                )
            return _guarded_mutation(name, args, _do_coord_post)

        if name in ("jarvis_coord_read", "coord_read"):
            try:
                from jarvis.core.coord import read as coord_read
                return coord_read()
            except Exception as e:
                return f"ERROR: coord_read failed: {e}"

        if name in ("jarvis_coord_check", "coord_check"):
            try:
                from jarvis.core.coord import check as coord_check
                files = args.get("files", "")
                if isinstance(files, list):
                    files = ",".join(str(f) for f in files)
                return coord_check(agent=args.get("agent") or None, files=files)
            except Exception as e:
                return f"ERROR: coord_check failed: {e}"

        if name in ("jarvis_coord_roster", "coord_roster"):
            try:
                from jarvis.core.coord_roster import roster_text
                return roster_text()
            except Exception as e:
                return f"ERROR: coord_roster failed: {e}"

        if name in ("jarvis_coord_whoami", "coord_whoami"):
            try:
                from jarvis.core.coord_roster import whoami
                return whoami(args.get("agent") or None)
            except Exception as e:
                return f"ERROR: coord_whoami failed: {e}"

        if name in ("jarvis_coord_set_context", "coord_set_context"):
            def _do_set_context() -> str:
                from jarvis.core.coord_roster import set_context
                return set_context(args.get("context", ""), args.get("agent") or None)
            return _guarded_mutation(name, args, _do_set_context)

        if name in ("jarvis_coord_msg", "coord_msg"):
            def _do_coord_msg() -> str:
                from jarvis.core.coord_roster import send_message
                note = args.get("note", True)
                if isinstance(note, str):
                    note = note.strip().lower() not in ("false", "0", "no")
                return send_message(args.get("to", ""), args.get("message", ""), note=note)
            return _guarded_mutation(name, args, _do_coord_msg)

        if name in ("jarvis_coord_pending", "coord_pending"):
            try:
                from jarvis.core.coord import pending
                files = args.get("files", "")
                if isinstance(files, list):
                    files = ",".join(str(f) for f in files)
                items = pending(
                    agent=args.get("agent") or None,
                    codename=args.get("codename") or None,
                    lane=args.get("lane") or None,
                    files=files,
                    since=args.get("since") or None,
                )
                if not items:
                    return "coord_pending: nada endereçado a você neste escopo."
                out = []
                for item in items:
                    out.append(
                        f"- [{item.get('kind')}] de {item.get('agent')}"
                        f"{' → ' + str(item.get('to')) if item.get('to') else ''}"
                        f" · {item.get('lane') or '—'}"
                        f" · {str(item.get('intent') or item.get('note') or '')[:200]}"
                        f" · {item.get('ts')}"
                    )
                return "coord_pending:\n" + "\n".join(out)
            except Exception as e:
                return f"ERROR: coord_pending failed: {e}"

        if name in ("jarvis_coord_peers", "coord_peers"):
            try:
                from jarvis.core.coord_roster import peers
                return peers()
            except Exception as e:
                return f"ERROR: coord_peers failed: {e}"

        if name == "jarvis_vault_status":
            result = _vault_status()
            return json.dumps(result, indent=2)

        # Shadow tools REMOVIDOS (eliminação 21/09): jarvis_proactive_check,
        # jarvis_system_health, jarvis_classify_file/directory eram chamáveis
        # mas invisíveis em tools/list, sem testes e sem chamadores fora
        # daqui (E6: superfície menor = menos entropia). Módulos watchdog/
        # classify seguem vivos p/ uso interno (classify_directory usa
        # classify_file). Re-announce via JARVIS_TOOLS if they are ever exposed.
        return f"ERROR: unknown tool: {name}"
    except Exception as e:
        return f"ERROR: {e}"


def _handle_nix_search(args: dict[str, Any]) -> str:
    """Proxy para mcp-nixos — pesquisa packages/options do nixpkgs.

    Launches the mcp-nixos binary as a subprocess and talks over JSON-RPC stdio.
    Returns the formatted result text.
    """
    import shutil

    # Encontrar mcp-nixos no PATH ou no nix store
    mcp_bin = shutil.which("mcp-nixos")
    if not mcp_bin:
        # Fallback: search the nix store (use subprocess without pipes)
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

    # Build the MCP call over stdin/stdout
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


# ═══ REHYDRATE (R1 — 02/11) ═══
# The "rescue" in 1 call. Research rules (docs/REHYDRATACAO-E-COORDENACAO.md):
#  - REVERSIBLE: returns the ORIGINAL (never a summary of it) plus the path;
#  - QUERY-CONDITIONED: memories/lessons/RAG filtered by the request;
#  - TRIAGE BY TYPE: the exact pinned guardrails on top (never summarized),
#    atomic HANDOFF, resumable logs/episodic content;
#  - 1 call, compact output (context is a finite resource: 2510.05381).
# State of the rescue loop-breaker (see _handle_rehydrate).
# Sliding window of COMPLETE rescues: up to 3 per window; the 4th returns
# only the pointer. Budget per window (not per task) because the measured loop
# variava o texto do task (4-5 paraphrases para a mesma intenção).
_REHYDRATE_CALLS: list[float] = []
_REHYDRATE_SEEN: dict[str, float] = {}
_REHYDRATE_LOCK = threading.Lock()

# LANGUAGE: English on purpose. This text is injected into the model's
# context — small local models (bonsai) do not read pt-BR, and a rule the
# model cannot read does not exist (owner directive, 02/11).
# Keep it byte-identical to PINNED_GUARDS in the opencode plugin
# (home-manager/files/opencode/plugins/memory.js): the same rules, pinned in
# two places, must not drift.
REHYDRATE_GUARDS = """## GUARDS (pinned — never summarize, never rewrite)
- First tool of the session = `jarvis_rehydrate(task="...")` (opencode exposes
  MCP tools as `<server-key>_<tool>`: server "jarvis" + tool "rehydrate").
  When a problem looks like a repeat, this is where you recover the state.
- Coordination: `claim` before speaking →
  `scripts/agent-roster.py claim --name <n> --lane <lane> --repo <repo> --files <globs>`.
  Two claims with overlapping files are refused (explicit boundaries).
- Delivery: `scripts/agent-msg.sh --to <name> "text"` (the target runs) ·
  `--note "text"` (enters the session, does NOT run, zero tokens) ·
  `--cancel <id>` (aborts the target turn).
  Never use wtype/focus: it blocks the human's typing.
- Wake: `agents-watcher.sh` wakes via the API and filters by repo/lane.
- Memory: `remember` at task end / topic switch; a decision valid for more
  than one session → memory + note; secrets → names only."""


def _rehydrate_queue(max_lines: int = 22, clip: int = 600) -> str:
    """Top of the queue (blackboard) — the most recent block, clipped.

    clip: a checkpoint summary is ONE line and can be 6k+ chars; without a
    per-line cap it becomes the context bomb the loop-breaker exists to avoid.
    """
    path = os.environ.get("AGENTS_QUEUE", str(Path.home() / "projects" / "AGENTS-QUEUE.md"))
    try:
        text = Path(path).read_text(encoding="utf-8", errors="ignore")
    except Exception as e:
        return f"(queue unreadable: {e})"
    lines = text.splitlines()
    # cuts at the next checkpoint header (the top one is the current one)
    for i, ln in enumerate(lines[1:], start=1):
        if ln.startswith("## ") and "CHECKPOINT" in ln:
            lines = lines[:i]
            break
    body = "\n".join(ln[:clip] for ln in lines[:max_lines]).rstrip()
    return f"(fonte: {path})\n{body}"


def _rehydrate_handoff(max_lines: int = 8) -> str:
    """Most recent HANDOFF — ATOMIC chunk (the original, not a summary).

    COMPACT on purpose (measured on 02/11):
    - the whole block (1843 chars) made the weak model loop on
      tool calls (204k tokens de input acumulados);
    - WORSE: the first lines of the HANDOFF are the opencode template
      ("## Objective / ## Important Details / ## Next Move") e o 4B o
      and the 4B IMITATED it: 91 turns writing in the same format (176k tokens).
       Hence: 8 lines (title + summary) + the path of the original. The agent reads
    the file when it needs to (R1: reversible = the original on the path, not a summary).
    """
    try:
        from jarvis.core.vault import MemoryVault

        mv = MemoryVault()
        notes = [n for n in mv.list_notes() if n.startswith("HANDOFF")]
        if not notes:
            return "(sem HANDOFF no vault)"
        vault = Path.home() / ".local/state/jarvis/vault"

        def _mtime(n: str) -> float:
            try:
                return (vault / n).stat().st_mtime
            except OSError:
                return 0.0

        # mtime first, name as tie-break: "HANDOFF-sprites-1010" sorts after
        # "HANDOFF-2026-..." lexicographically and was being served as the
        # "latest" anchor; equal mtimes (or a fake vault) still pick the newer
        # name deterministically.
        notes.sort(key=lambda n: (_mtime(n), n), reverse=True)
        name = notes[0]
        body = mv.read_note(name)
    except Exception as e:
        return f"(vault unreadable: {e})"
    path = str(Path.home() / ".local/state/jarvis/vault" / (name if name.endswith(".md") else name + ".md"))
    lines = body.splitlines()
    clipped = len(lines) > max_lines
    body = "\n".join(lines[:max_lines])
    tail = "\n(... rest of the file — read the path above for the original)" if clipped else ""
    return f"(fonte: {path})\n{body}{tail}"


def _rehydrate_memories(task: str, top_k: int = 5) -> str:
    try:
        from jarvis.core.memory import EpisodicMemory

        em = EpisodicMemory()
        results = em.recall(task, top_k=top_k)
    except Exception as e:
        return f"(memory unavailable: {e})"
    if not results:
        return "(nenhuma memória para este pedido)"
    return "\n".join(f"[{r.get('kind', '?')}] {r.get('text', '')[:260]}" for r in results)


def _rehydrate_lessons(task: str) -> str:
    try:
        from jarvis.core.memory import EpisodicMemory

        em = EpisodicMemory()
        out = em.lessons(task, top_k=3)
    except Exception as e:
        return f"(lessons unavailable: {e})"
    return out or "(no lesson for this pattern)"


def _rehydrate_roster() -> str:
    """Roster: who is alive and in which lane (the coordination truth)."""
    script = os.environ.get(
        "AGENTS_ROSTER_PY", str(Path.home() / "projects" / "nixos-ai" / "scripts" / "agent-roster.py")
    )
    if not Path(script).exists():
        return "(agent-roster.py not found)"
    try:
        out = subprocess.run(
            [sys.executable, script, "list", "--json"],
            capture_output=True, text=True, timeout=25,
        ).stdout
        data = json.loads(out or "{}")
    except Exception as e:
        return f"(roster unavailable: {e})"
    agents = [a for a in data.get("agents", []) if a.get("state") == "live"]
    if not agents:
        return "(nenhum agente com claim vivo — coordene por --broadcast ou faça claim)"
    lines = []
    for a in agents:
        lines.append(
            f"- {a.get('name')}: lane={a.get('lane') or '-'} repo={a.get('repo') or '-'} "
            f"files={','.join(a.get('files') or []) or '-'} "
            f"sessao={a.get('session') or '-'} busy={'sim' if a.get('busy') else 'nao'}"
        )
    tasks = data.get("tasks") or []
    if tasks:
        lines.append("tarefas: " + "; ".join(
            f"{t.get('id')}[{t.get('status')}] {t.get('title')}" for t in tasks[:6]))
    return "\n".join(lines)


def _rehydrate_state(max_lines: int = 12) -> str:
    """Compact, deterministic session state for harness injection.

    No embeddings and no RAG: queue + handoff + recent lessons + roster are
    plain reads, so the plugin can call this at session start without paying
    an embedding round-trip. The deep rescue (memories/RAG) stays on-demand in
    _handle_rehydrate.
    """
    blocks = [
        "## QUEUE (top)",
        _rehydrate_queue(max_lines=10, clip=280),
        "## HANDOFF (latest)",
        _rehydrate_handoff(6),
    ]
    try:
        from jarvis.core.memory import KIND_ERROR, KIND_LESSON, EpisodicMemory

        em = EpisodicMemory()
        recent = [
            e for e in em.recent(limit=40)
            if e.get("kind") in (KIND_LESSON, KIND_ERROR)
        ]
        if recent:
            blocks += [
                "## RECENT LESSONS (do not repeat)",
                "\n".join(f"- {str(e.get('text', ''))[:200]}" for e in recent[:3]),
            ]
    except Exception as e:  # noqa: BLE001
        blocks += ["## RECENT LESSONS", f"(unavailable: {e})"]
    blocks += ["## ROSTER", _rehydrate_roster()]
    return "\n\n".join(blocks)


def _handle_rehydrate(args: dict[str, Any]) -> str:
    """Rehydrates the session: 1 call, compact output, original content."""
    task = (args.get("task") or "").strip()
    if not task:
        return "ERROR: rehydrate needs 'task' (what you are about to do)"
    # LOOP-BREAKER (02/11): measured with the local 4B model — it called the
    # tool in a loop (20-24 calls, 293k input tokens) because on every call the
    # whole block came back into the context. Budget: up to N COMPLETE rescues
    # per sliding window; the next one returns a short pointer (the full
    # result is ALREADY in the context).
    agora = time.time()
    try:
        janela = float(os.environ.get("JARVIS_REHYDRATE_COOLDOWN_S", "120"))
    except (TypeError, ValueError):
        janela = 120.0
    try:
        max_completos = int(os.environ.get("JARVIS_REHYDRATE_MAX_CALLS", "3"))
    except (TypeError, ValueError):
        max_completos = 3
    chave = task.strip().lower()[:120]
    with _REHYDRATE_LOCK:
        _REHYDRATE_CALLS[:] = [t for t in _REHYDRATE_CALLS if agora - t < janela]
        for k in [k for k, t in _REHYDRATE_SEEN.items() if agora - t >= janela]:
            _REHYDRATE_SEEN.pop(k, None)
        repetido = janela > 0 and chave in _REHYDRATE_SEEN
        excedeu = janela > 0 and len(_REHYDRATE_CALLS) >= max_completos
        if not excedeu and not repetido:
            _REHYDRATE_CALLS.append(agora)
            _REHYDRATE_SEEN[chave] = agora
    if repetido:
        return (
            "## RESCUE ALREADY DONE FOR THIS REQUEST\n"
            "The same request was already rescued in this window — the result "
            "is in this session's context. Do not repeat it (each repetition "
            "pushes the whole block back into the context)."
        )
    if excedeu:
        return (
            "## RESCUE ALREADY DONE (window budget)\n"
            "You already made %d full rescues in this window — the result is "
            "in this session's context. Use it, do not call again (repeating "
            "burns context: 293k input tokens in a measured loop)." % max_completos
        )
    try:
        limit = int(args.get("limit", 3) or 3)
    except (TypeError, ValueError):
        limit = 5
    wanted = {p.strip() for p in (args.get("include") or "").split(",") if p.strip()}
    blocks: list[str] = []

    blocks.append(REHYDRATE_GUARDS)
    if not wanted or "queue" in wanted:
        blocks.append("## QUEUE (top — the real current state)\n" + _rehydrate_queue())
    if not wanted or "handoff" in wanted:
        blocks.append("## HANDOFF (most recent — atomic)\n" + _rehydrate_handoff())
    if not wanted or "memories" in wanted:
        blocks.append(f"## MEMORIES (request: {task})\n" + _rehydrate_memories(task, limit))
    if not wanted or "lessons" in wanted:
        blocks.append(f"## LESSONS (same request)\n" + _rehydrate_lessons(task))
    if not wanted or "rag" in wanted:
        blocks.append("## RAG code/docs\n" + _handle_rag_search(
            {"query": task, "collection": "code", "limit": limit}))
    if "books" in wanted:
        blocks.append("## RAG books/papers\n" + _handle_rag_search(
            {"query": task, "collection": "books", "limit": limit}))
    if not wanted or "roster" in wanted:
        blocks.append("## ROSTER (who is alive)\n" + _rehydrate_roster())

    blocks.append(
        "## END OF RESCUE\n"
        "One call only. The remaining detail is at the paths above — read the "
        "file if you need it (do not repeat this tool)."
    )
    return "\n\n".join(blocks)


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
        from pathlib import PurePath
        from jarvis.core.vault import MemoryVault
        # Audit P1-5: basename only, no traversal (../, absolute, subdirs)
        safe_name = PurePath(name).name
        if not safe_name or safe_name in (".", "..") or "\\" in name or "/" in name:
            return "ERROR: invalid note name (subdirs/traversal not allowed)"
        mv = MemoryVault()
        from jarvis.core import vault_cipher

        note_path = vault_cipher.note_path(mv.vault_dir, f"{safe_name}.md")
        vault_cipher.write_text(note_path, content)
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
        from jarvis.providers.vector_store import QdrantStore, VectorStoreError
        cfg = Config()
        # Override collection if specified (Config is frozen: replace, never assign)
        import dataclasses
        if collection == "memories":
            cfg = dataclasses.replace(cfg, qdrant_collection_code=cfg.qdrant_collection_memories)
        elif collection == "books":
            cfg = dataclasses.replace(cfg, qdrant_collection_code=cfg.qdrant_collection_books)
        # Audit P1-4: do NOT create/ensure the collection on a READ (hidden mutation).
        # Missing collection -> explicit error pointing at the indexing tool.
        hs = HybridSearch(config=cfg)
        try:
            results = hs.search(query, top_k=limit)
        except VectorStoreError as e:
            if "404" in str(e):
                return (f"Collection '{cfg.qdrant_collection_code}' does not exist yet. "
                        "Run jarvis_rag_index first (e.g. the repo path).")
            raise
        if not results:
            return "No results found."
        lines = []
        for r in results:
            pl = getattr(r, "payload", {}) or {}
            # code tem path; books tem book+chapter; memories tem kind
            path = pl.get("path") or pl.get("book") or pl.get("kind") or "unknown"
            if pl.get("chapter") is not None:
                path = f"{path} (cap. {pl['chapter']})"
            score = getattr(r, "score", 0)
            # HybridHit has no .text: the content lives in the payload (bug in the
            # old handler — hasattr(r, 'text') was always False)
            text = str(pl.get("content") or pl.get("title") or "")
            lines.append(f"[{score:.2f}] {path}\n{text[:200]}\n")
        return "\n".join(lines)
    except Exception as e:
        return f"ERROR: rag_search failed: {e}"


def _handle_rag_index(args: dict[str, Any]) -> str:
    """Index a directory into the RAG system (code + auto-sweep Books)."""
    path = args.get("path", ".")
    try:
        from jarvis.core.rag import HybridIndexer
        hi = HybridIndexer()
        count = hi.index_directory(path)
        out = f"Indexed {count} files from {path}"
    except Exception as e:
        error_msg = str(e)
        if "batch size" in error_msg:
            return "ERROR: Embedding server batch size too small (512 tokens). Increase --batch-size in llama-server config."
        return f"ERROR: rag_index failed: {e}"
    # Books coupling (owner 19/09): ONE call covers code+books —
    # varredura idempotente de PDFs/notas novos, sem script manual.
    try:
        from jarvis.core.audiobook import sweep_books
        sw = sweep_books()
        if sw.get("new"):
            out += f"; books: {', '.join(sw['new'])}"
        if sw.get("pending"):
            out += f"; books pending: {sw['pending']} (re-run index)"
    except Exception as e:
        out += f"; books sweep skipped: {e}"
    return out


# ═══ Stdio Server ═══
def main():
    """Runs the MCP server over stdio (JSON-RPC 2.0)."""
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

