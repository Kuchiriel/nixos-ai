# BUFFY.md — Agent Profile for Codebuff (Mimo 2.5)

> This file is read by Buffy when working on the nixos-ai project.
> It provides context about all available JARVIS features, MCP tools,
> project structure, and operational rules.
>
> **CLI WRAPPER**: Use `scripts/jarvis-cli.sh` to call any JARVIS tool.
> Example: `./scripts/jarvis-cli.sh read <file> 0 50`

## ⚠️ DEclarative First Rule

**ALL configuration files MUST be created via NixOS modules or home-manager.**

- Use `home.file` for user config files
- Use `xdg.configFile` for XDG config
- Use `pkgs.writeShellScriptBin` for scripts
- Use `systemd.user.services` for user services
- Use `systemd.services` for system services

**DO NOT** create files manually (mkdir, touch, echo > file).
**DO NOT** edit ~/.config/ directly.
**DO NOT** use pip/npm install globally.
**DO NOT** create scripts outside of Nix derivations.

## Quick Reference — JARVIS CLI Wrapper

**Use `scripts/jarvis-cli.sh` to call JARVIS tools from this agent.**

```bash
# Read a file (with offset/limit to save context)
./scripts/jarvis-cli.sh read <file> 0 50

# Execute shell command (read-only safe)
./scripts/jarvis-cli.sh shell "ls -la"

# Search NixOS packages
./scripts/jarvis-cli.sh nix-search "waybar"

# Read shared ChatGPT conversation
./scripts/jarvis-cli.sh chatgpt "https://chatgpt.com/share/..."

# Store/recall memory
./scripts/jarvis-cli.sh remember "fact to remember"
./scripts/jarvis-cli.sh recall "query"

# System status
./scripts/jarvis-cli.sh status
```

## Quick Reference — JARVIS MCP Tools

When Roo Dev or the REPL calls JARVIS, these tools are available:

| Tool | CLI Command | Description |
|------|------------|-------------|
| `jarvis_execute` | `shell <cmd>` | Shell commands |
| `jarvis_read_file` | `read <file> [offset] [limit]` | Read file |
| `jarvis_write_file` | `write <file> <content>` | Write file |
| `jarvis_str_replace` | `replace <file> <old> <new>` | Surgical edit |
| `jarvis_capture_screen` | `screen` | Screenshot |
| `jarvis_observe_screen` | `observe` | Screenshot + vision |
| `jarvis_nix_eval` | `nix-eval <expr>` | Evaluate Nix |
| `jarvis_nix_check` | `nix-check` | Flake check |
| `jarvis_nix_search` | `nix-search <query>` | Search packages |
| `jarvis_read_chatgpt` | `chatgpt <url>` | Read ChatGPT |
| `jarvis_read_ai_conversation` | `chatgpt <url>` | Multi-platform |
| `jarvis_remember` | `remember <fact>` | Store memory |
| `jarvis_recall` | `recall <query>` | Recall memory |
| `jarvis_lessons` | `lessons <query>` | Past errors |
| `jarvis_vault_list` | `vault-list` | List vault |
| `jarvis_vault_write` | `vault-write <title> <content>` | Write vault |
| `jarvis_rag_search` | `rag-search <query>` | Semantic search |
| `jarvis_rag_index` | `rag-index <dir>` | Index for RAG |
| `jarvis_hackmd_list` | `hackmd-list` | List notes |
| `jarvis_hackmd_read` | `hackmd-read <id>` | Read note |
| `jarvis_hackmd_write` | `hackmd-write <title> <content>` | Write note |
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

### Declarative First (NixOS/home.file)

**ALL changes MUST be declarative via NixOS modules or home-manager.**

- Configuration files → `home.file` or `xdg.configFile`
- Services → `systemd.user.services` or `systemd.services`
- Packages → `home.packages` or `environment.systemPackages`
- Scripts → `pkgs.writeScriptBin` or `pkgs.writeShellScriptBin`
- Timers → `systemd.user.timers`

**DO NOT**:
- Create files manually outside of Nix
- Edit `~/.config/` directly
- Use `mkdir` or `touch` for config files
- Install packages with `pip` or `npm` globally

**Exception**: `/tmp` for testing, state files in `~/.local/state/`

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

## JARVIS E2E Stress Test Results

### Test: Sync Documentation to HackMD

**Task**: Use JARVIS MCP tools to sync all .md files to HackMD

**Result**: ✅ SUCCESS

**Issues Found & Fixed**:
1. HackMD API returns `id` not `noteId` — fixed field mapping
2. `hackmd-sync` command missing from CLI wrapper — added it

**Files Synced**:
- README.md → `DZBDZ7hQTi2eKXazPE6MBA`
- AGENTS.md → `c6lqbvuETJGL8E7zYvif7Q`
- HANDOFF.md → `l_FhXk1ORE6VM4gFG6S1tw`
- TODO-MISSAO.md → `0ye2PffXR7aeCXSjH25Gvg`
- PLATFORM-AUDIT-2026-08-30.md → `gtGOKXLWTvOaGNv26GnCBg`

### Conclusions

1. **JARVIS MCP tools work** — but had bugs that needed fixing
2. **HackMD integration is functional** — can create, list, read, write notes
3. **CLI wrapper is useful** — simplifies calling JARVIS tools from terminal
4. **Bug discovery is the value** — E2E testing found real issues

### JARVIS vs MCU vs MiMo Code Comparison

**Critical Gaps Identified**:

1. **Context Window**: 32K vs 260K+ (8x smaller)
2. **Persistent Memory**: Session-based vs cross-session
3. **Subagent System**: Single-threaded vs parallel execution
4. **Task Tracking**: Flat vs hierarchical

**Recommendations**:
1. Increase context to 64K or 128K
2. Implement checkpoint system
3. Add MEMORY.md equivalent
4. Implement subagent system
5. Add hierarchical task tracking

**Key Insight**: The gap is not in the model, but in the **infrastructure around the model**.

### Mermaid Diagrams Created

1. `docs/ARCHITECTURE.mmd` — Full system architecture
2. `docs/JARVIS-COMPARISON.mmd` — MCU vs Our JARVIS vs MiMo Code
3. `docs/SELF-IMPROVEMENT-LOOP.mmd` — Agent self-improvement cycle

**Render in**: Obsidian, GitHub, mermaid.live

### Self-Improvement Loop (Addy Osmani Technique)

Based on "Ralph Wiggum" technique:
1. Pick task from prd.json
2. Implement task
3. Validate (tests, type checks)
4. Commit if pass
5. Log progress
6. Update AGENTS.md with learnings
7. Checkpoint state
8. Repeat

**Key Insight**: Each iteration is isolated (fresh context), but knowledge persists via:
- AGENTS.md (long-term knowledge)
- progress.txt (chronological log)
- prd.json (task state)
- Git History (code changes)

### Next Steps

1. Implement self-improvement loop for JARVIS
2. Create prd.json with tasks
3. Test JARVIS tools more (RAG, remember, recall)
4. Set up Obsidian vault
