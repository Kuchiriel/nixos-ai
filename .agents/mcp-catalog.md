# MCP catalog — what each tool is for, when to call it, how it is named

> Source of truth: `modules/ai/jarvis/src/jarvis/mcp_server.py` (`JARVIS_TOOLS` +
> `HACKMD_TOOLS` + `MAKE_TOOLS` = **37 tools**). Re-derive the list after adding a
> tool: `grep -c '"inputSchema"' modules/ai/jarvis/src/jarvis/mcp_server.py`.

## Naming (the #1 source of wasted calls)

- opencode exposes the jarvis server's tools as **`jarvis_<tool>`** (server key
  `jarvis`). `jarvis_rehydrate`, not `rehydrate`. A doubled prefix
  (`jarvis_jarvis_*`) is the same tool — harmless, but a sign you read an old doc.
- The CLI is the **same env and the same handlers**:
  `scripts/jarvis-cli.sh <tool> '<json-args>'` (see
  [`dados-e-memoria.md`](dados-e-memoria.md)). MCP handler keys are fixed:
  `rag_index`→`path`, `vault_write`→`name`(+`content`), `rag_search`→`query`/
  `collection`/`limit`, `remember`→`text`+`category`, `recall`/`lessons`→`query`.
  Wrong key = argument silently ignored.

## Hydration / memory — the family that decides everything else

| Tool | WHAT it returns | WHEN (mandatory) | WHEN NOT |
|---|---|---|---|
| `jarvis_rehydrate(task=…)` | 1 call: pinned guards + queue top + latest HANDOFF + memories + lessons + RAG hits + roster | **1st tool of a new session**, right after a compaction, or when the problem *looks like a repeat* | mid-task with the context in hand (use `recall`/`rag_search`); **never call it twice** for the same task (loop-breaker) |
| `jarvis_recall(query, top_k=5)` | episodic memory: past facts/decisions/errors | before acting on a subject; before asking the human what was decided | you need code/doc passages (`rag_search`) or a full session rescue (`rehydrate`) |
| `jarvis_lessons(query)` | ≤3 past traps + their fixes | **mandatory** when a command/test/build FAILED, before retrying the same thing, or before risky work (reboot, migration, DB) | happy path |
| `jarvis_rag_search(query, collection=code\|memories\|books, limit=5)` | semantic hits (file+line) over indexed trees | you do NOT know where something lives — **before grepping blindly**; unfamiliar territory → one parallel batch of `recall` + `rag_search` | you already know the path (read it); exact string match (grep) |
| `jarvis_rag_index(path=…)` | re-indexes a directory into `code` (+ papers into `books`) | the collection is empty, or after large moves/renames | a one-off question about a known file |
| `jarvis_remember(text, category=fact\|event\|decision\|error)` | durable memory + nightwatch visibility | task end, topic switch, or the moment a non-obvious decision/verdict is made | transient chat-only detail; secrets (store the NAME only) |
| `jarvis_vault_write(name, content)` / `jarvis_vault_list()` / `jarvis_vault_status()` | persistent, git-synced notes | resume pointers, handoffs, durable findings | anything that fits `remember` |
| `jarvis_vault_search_obsidian(query)` / `jarvis_vault_sync_obsidian` / `jarvis_vault_sync_hackmd` | vault search + sync | explicit vault work | routine memory (use `recall`/`remember`) |

Order that matters: **rehydrate → recall → rag_search → act → lessons (on failure)
→ remember (at the end)**. The `memory.js` plugin injects this router into every
opencode system prompt (state first, rules last) — the table above is the same
contract for every other harness (CLI, Roo, external agents).

## Files, desktop, browser

| Tool | WHEN |
|---|---|
| `jarvis_read_file(path, offset?, limit?)` / `jarvis_write_file` / `jarvis_str_replace` | file IO with line ranges (prefer `offset/limit` over dumping) |
| `jarvis_execute(cmd)` | shell command (read-only runs directly; writes need approval) |
| `jarvis_observe_screen` | understand the CURRENT UI (vision local → Gemini free → OCR) — prefer over `jarvis_capture_screen` |
| `jarvis_observe_file(path)` | analyze an image already on disk; **zero desktop interference** (no viewer, nothing left open) |
| `jarvis_capture_screen` | raw screenshot only (when you must crop/measure pixels yourself) |
| `jarvis_human_input(action=move\|click\|type\|key\|scroll)` | act on the desktop like a human; pair observe→act; dry-run first for coordinates |
| `jarvis_game(action=…)` | interact with a GAME window on Hyprland (focus by title; `prep_observe` first) |
| `jarvis_browser(action=…)` | any web page: read/click/fill/press; mutations need approval |
| `jarvis_read_ai_conversation(url)` | read a shared ChatGPT/Gemini/Claude conversation |

## Nix, web, personas, ops

| Tool | WHEN |
|---|---|
| `jarvis_nix_search(action, …)` | real nixpkgs/options data (anti-hallucination) before writing Nix |
| `jarvis_nix_eval(expr)` / `jarvis_nix_check(path)` | evaluate / `nix flake check` the project |
| `jarvis_web_search(query, limit)` | current events, library docs, anything outside the codebase |
| `jarvis_persona(action=select, task=…)` | **call first** when a task needs specialized framing (audit, review, research) |
| `jarvis_hackmd_list/read/write/sync` | HackMD notes as shared markdown |
| `jarvis_make_scenarios/run/scenario_get/executions` | Make.com automation (team `750102`) |

## Other servers (not jarvis)

| Server | Exposes | Who uses it | State |
|---|---|---|---|
| nixos-mcp (`vscode-roo.nix`) | `nix`, `nix_versions` (read-only) | Roo + JARVIS (`jarvis_nix_search`) | ATIVO |
| tavily-search | `tavily_search`, `tavily_extract` | Roo only | **morto p/ opencode** — use `jarvis_web_search` |
| context7 | library docs | Roo only | **morto p/ opencode** |
| playwright | browser automation | Roo only | removido do opencode de propósito (redundante com `jarvis_browser`) |
| github | repo ops | nobody (disabled sem token) | MORTO |
| WebUI bridge (`webui/api.py`) | re-expõe JARVIS_TOOLS via HTTP | nenhum cliente | sem consumidor |

Triggers: mcp, tavily, context7, browser, nix search, vault, rag, github,
rehydrate, recall, lessons, remember, roster.
