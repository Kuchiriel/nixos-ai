# BUFFY.md — Agent Profile for Codebuff (Mimo 2.5)

> This file is read by Buffy when working on the nixos-ai project.
> It provides context about all available JARVIS features, MCP tools,
> project structure, and operational rules.

## Quick Reference — JARVIS MCP Tools

When Roo Dev or the REPL calls JARVIS, these tools are available:

| Tool | Description | Usage |
|------|-------------|-------|
| `jarvis_execute` | Shell commands (read-only direct, write needs approval) | `ls`, `find`, `git`, `nix` |
| `jarvis_read_file` | Read file with optional offset/limit | Economizes context |
| `jarvis_write_file` | Write/overwrite file | Creates new files |
| `jarvis_str_replace` | Surgical string replacement in file | Preferred for edits |
| `jarvis_capture_screen` | Take screenshot of desktop | Debug UI issues |
| `jarvis_observe_screen` | Screenshot + vision AI analysis | Understand what's on screen |
| `jarvis_nix_eval` | Evaluate Nix expressions | Test configs before rebuild |
| `jarvis_nix_check` | Run `nix flake check` | Validate flake |
| `jarvis_nix_search` | Search NixOS packages/options/flakes | Find packages |
| `jarvis_read_chatgpt` | Read shared ChatGPT conversations | Get context from conversations |
| `jarvis_read_ai_conversation` | Read shared AI conversations (ChatGPT/Gemini/Claude) | Multi-platform |
| `jarvis_remember` | Store episodic memory (cross-session) | Facts, events, decisions |
| `jarvis_recall` | Recall memories matching query | Search past events |
| `jarvis_lessons` | Recall lessons from past errors | Avoid repeated mistakes |
| `jarvis_vault_list` | List persistent vault notes | Check stored knowledge |
| `jarvis_vault_write` | Write to persistent vault | Important findings |
| `jarvis_rag_search` | Semantic code search (RAG) | Find relevant code |
| `jarvis_rag_index` | Index directory into RAG system | Make code searchable |
| `jarvis_hackmd_list` | List recent HackMD notes | Documentation |
| `jarvis_hackmd_read` | Read HackMD note by ID | Read docs |
| `jarvis_hackmd_write` | Create/update HackMD note | Write docs |
| `jarvis_hackmd_sync` | Sync local file to HackMD | Backup/sync docs |

## Project Structure

```
~/projects/                    # Monorepo root (all projects)
├── nixos-ai/                  # Main project (THIS REPO)
│   ├── modules/ai/jarvis/     # Python code (core, providers, mcp)
│   │   ├── src/jarvis/        # Source code
│   │   │   ├── core/          # Business logic
│   │   │   ├── cli/           # CLI (dev.py, main.py)
│   │   │   ├── providers/     # LLM, MCP, Telegram, RAG
│   │   │   └── mcp_server.py  # MCP server entrypoint
│   │   └── tests/             # Tests (pytest)
│   ├── modules/services/      # NixOS modules (llama-cpp, qdrant)
│   ├── home-manager/modules/  # User configs (waybar, hyprland, rofi)
│   ├── hosts/nitro-v15/       # Host config
│   ├── nightwatch/             # Nightwatch harness (autonomous agent)
│   ├── docs/                   # Documentation
│   ├── scripts/                # Build/validation scripts
│   ├── flake.nix               # Nix flake
│   ├── AGENTS.md               # Agent instructions (Linux Foundation format)
│   ├── .roomodes               # Roo Code custom modes
│   └── .jarvismodes            # Jarvis REPL custom modes
├── llama.cpp/                  # llama.cpp source
├── guia-renamer-pro/           # File renamer with tkinter
├── nixpkgs/                    # Nixpkgs fork
└── shared/                     # Shared resources
```

## Hardware

- **Laptop**: Acer Nitro V15
- **GPU**: NVIDIA RTX 4050 (6GB VRAM)
- **RAM**: 32GB
- **OS**: NixOS (declarative, flake-based)
- **Display**: 1920x1080@144Hz, LG Display

## Running Services

| Service | Port | Description |
|---------|------|-------------|
| llama-server | 8080 | Qwen3.6-35B-A3B Q4_K_M (MoE, 32K ctx) |
| embeddings | 8081 | nomic-embed-text-v2-moe |
| rerank | 8082 | bge-reranker-v2-m3 |
| qdrant | 6333 | Vector database for RAG |

## Operational Rules

### Commands
```bash
# Tests (ALWAYS use nix develop, NOT nix-shell)
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q --tb=short

# Build
git add -A && nix build .#jarvis --no-link && nix flake check

# Rebuild system
./rebuild-host.sh    # HOST — NEVER nixos-rebuild directly!

# Clean
./clean.sh
```

### Do
- Run tests before committing
- `git add -A` before build (flake only sees tracked files)
- Commit messages in PT-BR with verb (`feat:`/`fix:`/`chore:`/`docs:`)
- Use `str_replace` for surgical edits (not full file rewrites)
- Use `head`/`tail`/`sed` for large files (context is scarce — 32K tokens)

### Don't
- Use `nixos-rebuild` directly (use rebuild-host.sh)
- Edit files in `/nix/store/`
- Reiniciar o LLM durante sessão ativa
- Read entire large files (use offset/limit)
- Let tool output exceed 50 lines (summarize)

### Context Management (32K tokens)
- System prompt: ~4-6K tokens
- Effective budget: ~26-28K for conversation + tools
- Tool outputs consume context fast
- Condensing occurs when context > 70% of budget
- Use `jarvis_read_file` with offset/limit to economize

## JARVIS Feature Map

### Core
- `agent.py` — Multi-turn LLM agent with tool calling
- `config.py` — Configuration management
- `router.py` — Intent routing (code/question/command)
- `eventbus.py` — Pub/sub event system
- `memory.py` — Episodic memory (remember/recall)
- `vault.py` — Persistent knowledge vault
- `rag.py` — RAG (Retrieval Augmented Generation)

### Voice Pipeline
- `voice.py` — TTS (Kokoro) + STT (faster-whisper)
- `vision.py` — Vision analysis (Qwen-VL)
- `triggers.py` — Wake word / trigger detection

### Developer Tools
- `devtools.py` — File operations (read/write/str_replace)
- `dev.py` — Interactive REPL (jarvis dev)
- `ast_guard.py` — AST-based code safety
- `ast_cache.py` — AST caching for performance

### Infrastructure
- `hackmd.py` — HackMD integration
- `chatgpt_reader.py` — Read shared ChatGPT conversations
- `multi_ai_reader.py` — Multi-platform conversation reader
- `feedback.py` — Waybar status + notifications
- `gaming.py` — Gaming mode (service management)
- `idle.py` — Idle mode (background improvements)
- `heal.py` — Self-healing mode
- `doctor.py` — System diagnostics

### Nightwatch (Autonomous Agent)
- `nightwatch/harness.py` — Main orchestrator
- `nightwatch/patcher.py` — Structured patch generation
- `nightwatch/safe_editor.py` — Atomic writes with validation
- `nightwatch/validator.py` — Syntax/import/test validation
- `nightwatch/evaluator.py` — Independent code review
- `nightwatch/checkpoint.py` — Recovery/persistence
- `nightwatch/task_queue.py` — Task state machine
- `nightwatch/safety.py` — Protected paths
- `nightwatch/loop_detector.py` — Anti-loop detection
- `nightwatch/context_budget.py` — Context management

## Git History Context

Recent commits show work on:
- Icon fixes (brain, GPU chip)
- Nightwatch structured patches (replacing legacy full-file)
- Audiobook reader (EPUB/PDF/TTS with PT-BR voices)
- Gaming mode fixes
- Waybar improvements
- Wakeword service
- HackMD integration

## Monorepo Notes

- `~/projects/` is a monorepo with shared `.git`
- Each subdirectory is a separate project
- JARVIS features span multiple projects
- RAG indexes should cover all projects
- Nightwatch can work across projects (multi-project support)
