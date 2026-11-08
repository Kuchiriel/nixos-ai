# Recon MCP tools safety (@general subagent)

- **sessão:** `ses_f3f3c6a8fffeXTOOzxN9v1Oux7`
- **quando:** 2026-09-20 21:40 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 13 (exportadas: 6)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

In /home/nixos/projects/nixos-ai, reconstruct the MCP TOOL SURFACE + SAFETY/OBSERVABILITY stack as it exists TODAY (repo is source of truth). Code in modules/ai/jarvis/src/jarvis/. Cover: MCP servers exposed (mcp_server.py, mcp/ dir if present, tests/test_mcp*.py): full tool list with one-line purpose each, especially knowledge tools (rag search, memory recall, lessons, vault, books, self-knowledge); tool disclosure policy (strict_tools, progressive disclosure, where implemented); safety (core/security.py: command allowlist, run_shell, safe editor, approval flow); observability (telemetry, traces, payload_summary, logging, eventbus). Report: exact tool inventory, overlapping/duplicated surfaces, which "mandatory" policies are actually enforced in code vs prose, tests per area, silent-failure risks. Return a compact structured map. Do NOT modify anything. Research only.

---

## · ?

Mapping today's MCP, safety and observability surface — pulling the live implementation as source of truth.

---

## · ?

Core tools and safety mapped — now digging into disclosure policy, knowledge backends and test coverage.

---

## · ?

33 MCP tools inventoried — now checking approval gates, telemetry and silent-failure risks.

---

## · ?

Test counts gathered — verifying the last safety wiring details.

---

## · ?

# JARVIS MCP tool surface + safety/observability — map as of TODAY (`nixos-ai`, code = truth)

No `mcp/` dir exists. Single server: `modules/ai/jarvis/src/jarvis/mcp_server.py` (1021 lines). Research only, nothing modified.

## 1. Exact tool inventory — `JARVIS_TOOLS` = **33 declared**

| # | Tool | One-line purpose |
|---|------|------------------|
| 1 | `jarvis_execute` | Shell via `security.run_shell` (allowlist-gated, 60s, trunc 8k) |
| 2 | `jarvis_read_file` | Read w/ offset/limit → `devtools.handle_dev_tool` |
| 3 | `jarvis_write_file` | Create/overwrite → `handle_dev_tool` (**no approval check here**) |
| 4 | `jarvis_str_replace` | Surgical edit → `handle_dev_tool` (**no approval check here**) |
| 5 | `jarvis_capture_screen` | Screenshot |
| 6 | `jarvis_observe_screen` | Screenshot + vision-AI analysis |
| 7 | `jarvis_browser` | Web read/click/fill/attach (mutations need approval — always denied over MCP, see §4) |
| 8 | `jarvis_nix_eval` | `nix eval --json '<expr>'` (interpolated into shell string) |
| 9 | `jarvis_nix_check` | `nix flake check` on path (interpolated) |
| 10 | `jarvis_nix_search` | Subprocess proxy to external `mcp-nixos` binary via stdio handshake |
| 11 | `jarvis_read_chatgpt` | Shared ChatGPT URL → messages (headless browser) |
| 12 | `jarvis_remember` | Store fact/event/decision/error → `EpisodicMemory` |
| 13 | `jarvis_recall` | Recall memories by query (`top_k`) |
| 14 | `jarvis_lessons` | Past-failure lessons for error pattern |
| 15 | `jarvis_vault_list` | List `MemoryVault` notes |
| 16 | `jarvis_vault_write` | Write vault note (basename-only, no traversal — enforced) |
| 17 | `jarvis_rag_search` | Hybrid RAG over `code`/`memories`/`books` collections (explicit 404→"run index first") |
| 18 | `jarvis_persona` | list/show/select role personas |
| 19 | `jarvis_rag_index` | `HybridIndexer.index_directory` + auto `sweep_books()` coupling |
| 20 | `jarvis_web_search` | Tavily web search |
| 21 | `jarvis_read_ai_conversation` | Any AI share URL (ChatGPT/Gemini/Claude auto-detect) |
| 22–25 | `jarvis_hackmd_{list,read,write,sync}` | HackMD notes CRUD + local→HackMD sync (from `core/hackmd.py`) |
| 26–29 | `jarvis_make_{scenarios,scenario_get,executions,run}` | Make.com blueprints; `run` hard-requires `confirm=true` (enforced, `make_ops.py:124`) |
| 30–33 | `jarvis_vault_sync_obsidian`, `..._sync_hackmd`, `..._search_obsidian`, `..._status` | Vault bridges (rg fixed-string search; missing-vault returns observable `[{error}]`, not `[]`) |

**Shadow surface (handled in `call_tool` but NOT in `JARVIS_TOOLS`, invisible to `tools/list`): 4 tools** — `jarvis_proactive_check`, `jarvis_system_health` (both → `core/watchdog.py`), `jarvis_classify_file`, `jarvis_classify_directory` (both → `core/classify.py`). Callable but undiscoverable.

## 2. Overlapping / duplicated surfaces (3 schemas, not 1)

- **MCP surface** (33 declared + 4 shadow): flat JSON-Schema, `tools/list` dumps everything, no gating.
- **`DEV_TOOLS`** (`core/devtools.py`, OpenAI-function format): `read_file, write_file, str_replace, sanitize_secrets, build_json_dataset, semantic_search, list_directory, code_search, run_tests, run_linter` (+`jarvis_command`; `execute_shell` deliberately excluded — "one canonical shell definition", `devtools.py:1285`).
- **Agent runtime schema** (`core/agent.py:2773–2950`): `read_file, list_directory, write_file, str_replace, build_json_dataset, sanitize_secrets, book_search, book_resume, synthesize_command` + `execute_shell` **only if `mcp_servers` configured**. MCP-only tools (memory/vault/rag/persona/hackmd/make) are NOT in the agent loop schema — agent reaches them via `execute_shell jarvis …` CLI or MCP client, not native calls. `book_search/book_resume` exist ONLY here, never in MCP. `execute_shell` exists in both but with different names/semantics (`execute_shell{cmd}` vs `jarvis_execute{cmd}`).

## 3. Knowledge tools — backends

- `remember/recall/lessons` → `core/memory.py: EpisodicMemory` (remember/recall/lessons). `clear()` requires `confirm=True` in code.
- `vault_*` → `core/vault.py: MemoryVault` (`~/vaults/projects/nixos-ai`); search via `rg -F` on `JARVIS_OBSIDIAN_VAULT` (default `~/vaults/projects`).
- `rag_search/index` → `core/rag.py: HybridSearch/HybridIndexer` + `providers/vector_store.py QdrantStore`; collections from `core/config.py` (`code` default, `memories`, `books` via `dataclasses.replace` — Config frozen, never mutated). Read path never creates collections (P1-4 fix).
- `books` = Qdrant `books` collection + `core/audiobook.py` (`search_books`, `index_book`, `sweep_books` idempotent PDF sweep auto-chained in `rag_index`).
- `self-knowledge` = **not a tool**: idle-timer tasks (`core/idle.py`, `cli/main.py:366`) + `core/eval_rag.py` NixOS section + `knowledge_schema.py` collection map. Prose-only surface.

## 4. Tool disclosure policy — where it really lives

- `strict_tools` (`agent.py:107` `_strict_default` + `:2958`): opt-in **by tier** — `speed`/`fast` (bonsai/Qwen3-4B) default ON, reasoning/cloud OFF; registry-unreadable → OFF. When ON and no `role=="tool"` yet: system gets signature block, `tools=None` + grammar `extra`, model JSON converted via `_strict_to_response`. **Agent loop only; MCP server ignores it.**
- Progressive disclosure (**Agent loop only; MCP `tools/list` always returns all 33**): `book_search/book_resume` ← `BOOK_TASK_HINTS` keyword gate (`agent.py:352`, fail-open fallback still dispatches); `build_json_dataset` ← `_data_task_offered`; `sanitize_secrets` ← `_secret_task_offered`; `synthesize_command` ← `_synth_offered(bar_repeat|artifact_repeat|echo_banned)`.
- "MANDATORY recall/lessons/remember" = **description prose only** in MCP. Actually enforced: `TOOL_USE_DISCIPLINE` injected into system prompt always (`agent.py:1054`); `lessons(prompt)` **auto-injected** per turn (`agent.py:1130` — the primary mechanism per H1 notes); `recall` is never auto-called.

## 5. Safety (`core/security.py` = single source of truth)

- Allowlist `DEFAULT_ALLOWED_PREFIXES` (read-only: ls/cat/grep/rg/find/git-log|status|diff/nix-eval|flake-check/curl -sf…); `DANGEROUS_CHAINING` (`&& || ` $() ${ \n`), `DANGEROUS_COMMANDS` (rm/chmod/chown/dd/mkfs); `;`-split per-part check; `validate_pipes` restricts post-`|` to `SAFE_PIPE_TARGETS`; `_strip_quoted` exempts in-quote operators (backtick still always blocked); `python3 <file>` allowed only in-project/`/tmp`/`/build`, no `-c`/`-m`/flags (`_python_file_allowed`); `strip_redundant_chmod_run` fuses `chmod +x && ./x`; GBNF `SYNTH_GRAMMARS` (grep/jqread/date/chmod) + `echo_to_json` soft→binding ban.
- `run_shell`: `shlex` (no `shell=True`), `~`/`$VAR` per-token expansion, unbalanced quotes → rc 127 (never raises), `start_new_session` + `killpg` tree-kill on timeout.
- Safe editor: `write_file/str_replace` → `nightwatch/safe_editor.py: SafeEditor.apply_edit` (atomic + AST/python-nix-json validation + structural-integrity + `.bak`). Project jail `_safe_path` (+`/tmp /build /etc/jarvis`); `write=True` blocks `.env/*secret*/*token*/*credential*/*.key/*.pem` and immutable pre-existing `.log/.csv/.db/.parquet` inputs; `.sh` auto-`+x`.
- **Approval gap (verified in code)**: Agent loop enforces `self.approve + human_approve(cmd)` for shell-off-allowlist and for `write_file/str_replace` (`agent.py:1594,2020,2089` + `_log_audit`), denial = honest `ERROR … needs approval`. **MCP `call_tool` enforces none of this**: `jarvis_execute` only checks `_command_allowed` (deny, no approve path); `write/str_replace` go straight to `handle_dev_tool`. `handle_browser(approve=False)` default ⇒ mutations always return "needs --approve". Only `make_run`'s `confirm=true` is enforced on the MCP path.

## 6. Observability

- `core/logging.py: Logger` — JSONL per module (`{ts,iso,module,event,level,detail}`), dir `JARVIS_STATE_DIR/logs` else `~/.local/state/jarvis/logs`; rotate 10 MB × keep 3; `read_events`/`compute_metrics` for `jarvis metrics`. **Silencer: `JARVIS_JSONL=0` or uid 0 (host default) disables all JSONL; `OSError` on emit swallowed.**
- `core/context_budget.py: SessionTelemetry` — per-call `{model,backend,prompt/completion/cached,tps,ttft,latency,sys/tools/msgs_chars,stage}`; `render()` window bar, `payload_summary()` avg chars sys/tools/msgs; calls capped at 2000. Fed by `providers/llm.py:_record_telemetry` and agent payload annotation (`agent.py:2989`, best-effort `try/except: pass`).
- Audit: `agent.py:937 _log_audit` → JSONL `{timestamp,cmd,exit_code,allowed,approved,result_truncated}`; write failures → `logger.error` only.
- `core/eventbus.py` — sync+async bus, per-subscriber retry(3)+timeout(30s), DLQ capped 1000 (+`dlq_dropped` counter), `stats{published,delivered,failed,dlq_*}`; async-handler-in-sync-dispatch with running loop → DLQ (no longer silent); `QueueFull` → DLQ.
- Loop guards: `ToolValidator`, `LoopDetector`, `completion.py` (trailing-error/artifact-exists/anti-false_done, echo-JSON escalation), `_truncate_history_for_send` (12k budget, keep-last-2, 500 floor — send-copy only, stored history intact).

## 7. Tests per area (`def test` counts)

`test_agent` 114 · `test_devtools` 56 · `test_persona` 32 · `test_mcp_tools_e2e` 21 (integration, skipped in nix sandbox) · `test_eventbus` 19 · `test_rag` 18 · `test_memory` 13 · `test_logging` 13 · `test_security` 9 · `test_hackmd` 8 · `test_mcp` (client) 6 · `test_vault` 6 · `test_book_rag` 5 · `test_make_ops` 5 · `test_mcp_vault_search` 2. No dedicated `test_mcp_server.py` for `JARVIS_TOOLS`/`call_tool` dispatch surface itself.

## 8. Silent-failure risks (code-verified)

1. MCP stdio `main()` swallows `JSONDecodeError` (`continue`) — malformed frames vanish.
2. Approval denials over MCP look like allowlist misses (`ERROR: command not in allowlist`) — caller can't tell "needs human" from "forbidden" (agent path distinguishes).
3. `jarvis_nix_eval/nix_check` interpolate `expr`/`path` into a shell string before `run_shell`'s shlex split — quoting-sensitive; failure surfaces as rc 127 text, no schema error.
4. `_handle_nix_search` failure modes return `ERROR:` strings (binary-missing, timeout, handshake) — observable but indistinguishable shape from real results without `isError` check by client.
5. `rag_index` books-sweep failure is appended to success string (`"; books sweep skipped: …"`) — easy to misread as success.
6. Output truncation (`execute` 8k, `run_shell_dict` 5k, audit `TOOL_OUTPUT_MAX_CHARS`) is marked, but `hackmd_read` hard-caps content at 5000 chars silently inside JSON.
7. Host runs as root ⇒ JSONL logging auto-disabled ⇒ forensics gap unless `JARVIS_JSONL=1`.

---

