# 🖥️ REPL Guide

> How to use `jarvis dev` effectively.

## Quick Start

```bash
# Start REPL in current directory
jarvis dev

# Start in specific project
jarvis dev --project ~/projects/nixos-ai

# Auto-approve all commands (careful!)
jarvis dev --yolo

# Resume last session
jarvis dev --continue

# Run single task and exit
jarvis dev --once "fix the bug in main.py"
```

## Slash Commands

| Command | Description |
|---------|-------------|
| `/help` | Show all commands |
| `/status` | Backend status and latency |
| `/clear` | Clear context (fresh start) |
| `/compact` | Compress context manually |
| `/map` | Refresh repo map |
| `/model` | Show current model |
| `/recall` | Search episodic memory |
| `/lessons` | Search learned lessons |
| `/vault` | List persistent notes |
| `/reasoning` | Show/set reasoning level |
| `/reasoning low` | Low reasoning (faster) |
| `/reasoning med` | Medium reasoning (default) |
| `/reasoning high` | High reasoning (slower) |
| `/modes` | List available modes |
| `/mode code` | Switch to code mode |
| `/mode architect` | Switch to architect mode |
| `/mode nightwatch` | Switch to nightwatch mode |
| `/mode organizer` | Switch to organizer mode |
| `/mode research` | Switch to research mode |
| `/architect` | Plan then execute |
| `/debug` | Toggle debug output |
| `/quit` | Exit REPL |

## Tools (20 available)

### File Operations
- `read_file(path, offset?, limit?)` — Read with line numbers
- `write_file(path, content)` — Create/overwrite file
- `str_replace(path, old, new)` — Surgical edit (old must be exact)
- `list_directory(path, max_depth?)` — List directory contents

### Shell
- `execute_shell(cmd)` — Run bash command (pipes and ; supported)

### Search
- `semantic_search(query, top_k)` — Semantic code search
- `rag_search(query)` — RAG codebase search
- `rag_index(path?)` — Index directory into RAG

### Vision
- `capture_screen()` — Take screenshot
- `observe_screen(mode?, question?)` — Screenshot + AI analysis

### NixOS
- `nix_eval(expr)` — Evaluate Nix expression
- `nix_check()` — Run `nix flake check`
- `nix_search(query)` — Search nixpkgs

### Memory
- `remember(text, category?)` — Store in episodic memory
- `recall(query)` — Search memories
- `lessons(query)` — Find learned lessons
- `vault_list()` — List persistent notes
- `vault_write(name, content)` — Write persistent note

### Web
- `read_chatgpt(url)` — Read shared ChatGPT conversation

## Output Limits (IMPORTANT)

The model has 32K context. System prompt takes ~15-20K. **You have ~12K for conversation.**

| Command | Limit | Why |
|---------|-------|-----|
| `find` | max 30 results | `-maxdepth 2 \| head -30` |
| `ls` | NO recursive | Never use `-R` |
| `git log` | max 10 lines | `git log --oneline -10` |
| `cat` | FORBIDDEN | Use `head`, `tail`, `sed` |
| `grep` | max 20 results | `-m 20` or `\| head -20` |
| Any output >50 lines | Summarize | Convert to bullet points |

## Best Practices

1. **Always `read_file` before `str_replace`** — Get exact content first
2. **Use `wc -l` before reading** — Know file size
3. **Test after editing** — Run relevant tests
4. **Commit after testing** — Atomic commits
5. **Use modes** — Switch to appropriate mode for task type
