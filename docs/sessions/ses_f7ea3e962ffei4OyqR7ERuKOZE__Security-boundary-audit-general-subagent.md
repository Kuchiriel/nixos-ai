# Security boundary audit (@general subagent)

- **sessão:** `ses_f7ea3e962ffei4OyqR7ERuKOZE`
- **quando:** 2026-09-08 14:11 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 9 (exportadas: 5)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

In /home/nixos/projects/nixos-ai (read-only, NO edits), audit SECURITY boundaries in modules/ai/jarvis/src/jarvis/: (1) Does ALL external-provider-bound content pass through ContentSafetyFilter/security policy? Find every path that sends user/model content to LLM providers, Tavily, HackMD, Telegram — check each passes the choke point (grep ContentSafetyFilter, safety, filter); (2) Destructive operations (rm/delete/git reset/git clean/overwrite/systemctl stop) — do they pass policy/confirmation/scope/project boundary? (grep run_command, execute, approval, Risk); (3) subprocess/shell=True/os.system/Popen with user-controlled input — injection risks (list file:line + whether input validated); (4) Permission consistency: CLI vs Agent vs MCP vs Tool vs Project — paths allowing what others deny; (5) privacy provider_registry consumers (who reads it? zero?); (6) Tool availability leak: does the model receive tools it shouldn't (check tool filtering by project/context); (7) Context contamination: module-level singletons/caches/global env shared across sessions/projects. file:line + verdict each. Max 90 lines. Do NOT fix.

---

## · ?

Auditing every external boundary — tracing provider, shell, and policy paths.

---

## · ?

First sweep shows the choke point only covers two paths — now checking the bypass routes.

---

## · ?

Core policy mapped — now verifying shell execution, destructive ops, and cross-session leaks.

---

## · ?

SECURITY BOUNDARY AUDIT — `modules/ai/jarvis/src/jarvis/` (read-only, no fixes)

(1) EXTERNAL EGRESS — ContentSafetyFilter choke point:
- `core/circuit_breaker.py:102,192,254,320` — `ContentSafetyFilter/is_safe` gates `_try_fallback` + OPEN path — VERDICT: PASS (only gated path).
- `core/provider_registry.py:178,185,199` — `route()` hard gate `SECRET/CONF/NON-PUBLIC→local only` — VERDICT: DEAD CODE, zero importers (grep: no `from provider_registry import` outside file) — FAIL.
- `providers/llm.py:337,364,379` `chat/chat_with_tools` → `backend.chat` direct — no `is_safe` — FAIL bypass.
- `providers/llm_llama_cpp.py:95` + `llm_prismml.py:96` `chat()` httpx/requests direct — no filter — FAIL bypass.
- `webui/api.py:361,367` `chat()` → `client.chat` direct, never `CircuitBreaker.execute` — FAIL bypass.
- `core/websearch.py:26,42` `web_search(query)` → `requests.post TAVILY_ENDPOINT` raw query — no filter — FAIL leak (user+vault context exfil).
- `core/hackmd.py:67,82,109,139,146` `create/update/sync/nightwatch/knowledge` → `requests.{post,patch,get}` raw file/vault content — no filter — FAIL leak.
- `providers/telegram.py:42,56,135` `_post/send_message/approver` + `control_plane/notifications.py:123` `_send_telegram` + `core/watchdog.py:114` `notify_telegram` + `core/vault.py:132`/`heal.py:129,158`/`idle.py:231` — raw alerts/cmds to Telegram cloud — no filter — FAIL leak.
- `core/vision.py:303` `requests.post` vision LLM — appears local URL — VERDICT: PASS-if-local, WARN if remotable.
- `core/multi_ai_reader.py:53,84` `requests.get(url)` user URL fetch — ingress, no egress gate — WARN SSRF.

(2) DESTRUCTIVE OPS — policy/confirmation/scope:
- `core/security.py:22` `DANGEROUS_COMMANDS=(rm,chmod,chown,dd,mkfs)` defined but `command_allowed():91` never checks it — relies solely on allowlist prefix — VERDICT: FAIL dead guard (works only by omission).
- `core/security.py:35` `DEFAULT_ALLOWED_PREFIXES` omits `git reset/clean/rm/systemctl stop` — non-allowlisted → needs approval — PASS by default-deny.
- `core/devtools.py:409,418` `execute_shell` → `command_allowed+run_shell_dict` — PASS; `devtools.py:580,621,666,700,975,1195,1218` `subprocess.run(cmd_parts)` fixed `jarvis/pytest/nix` argv, `args.split()` user args — WARN arg-injection (no shell but flag injection).
- `core/agent.py:462,489` `command_allowed` + approver gate + `commands_denied` audit — PASS; bypassed by `cli/dev.py:1968,2421,2465` `yolo→approve=True` auto-approve all — FAIL open bypass.
- `mcp_server.py:514` `_command_allowed` gate — PASS; but `mcp_server.py:569,574` f-string `nix eval '{expr}'` / `cd {path} && nix flake check` via shlex (no shell, `&&` literal) + `expandvars` — WARN injection/breakage.
- `control_plane/commands.py:184` `MEDIUM/HIGH requires confirmed` — PASS logic; `webui/api.py:169` + `mcp_server` + `cli/main.py:1352` `confirmed/approve` is client-supplied bool — FAIL forgeable (no server second factor).
- `control_plane/systemd_adapter.py:155,219` + `core/heal.py:39` `ALLOWLIST+cooldown+restart-only` — PASS.
- `core/hackmd.py:99` `delete_note()` exists, unexposed in MCP but directly callable — WARN no policy.
- `core/devtools.py:44` `_safe_path` project containment for file tools — PASS where used; shell tools use `os.chdir(project)` not jail — FAIL scope escape via `../` + absolute paths in shell.

(3) SUBPROCESS / SHELL INJECTION (user-controlled?):
- `core/self_test.py:132,134` `subprocess.run(f"jarvis {cmd}", shell=True)` — FAIL critical if `cmd` influenced.
- `providers/mcp.py:62` `Popen(cmd,args)` from `parse_command(binary)` — WARN if binary user-supplied, no allowlist shown.
- `core/security.py:129` `run_shell: shlex.split+expandvars/expanduser, no shell` — PASS (all agent/dev/mcp/router callers inherit).
- `core/doctor.py:127,149,191,288,298` / `heal.py:104,239` / `hwdetect.py:76,93,99` / `vision.py:55,87,96,126,147,165` / `feedback.py:65,127,156` / `voice.py:511,606` / `voice_clone.py:96,147` / `vault.py:80` / `cli/main.py:298,314` — fixed argv lists, timeouts — PASS validated.
- `core/evidence.py:118,258,271,285` + `workspace.py:242` + `persona_executor.py:182` `subprocess.run` — args not traced to allowlist — WARN needs per-line review.
- `mcp_server.py:720` `Popen(mcp-nixos…)` fixed binary discovery — PASS.

(4) PERMISSION CONSISTENCY CLI vs Agent vs MCP vs Tool vs Project:
- `core/persona.py:18,357` `PersonaPolicy(can_write/can_execute/can_commit/can_deploy)` never enforced; `filter_tools` maps only `tools[]→CAPABILITY_TOOLS`, ignores policies — FAIL.
- `persona.py:100` `cto: can_write=False` but `tools=[shell]` → `execute_shell` writes/deletes anyway — FAIL allows-what-denied.
- `persona.py:223,243` `qa/security: can_write=False+can_execute=True` — shell = arbitrary write — FAIL incoherent.
- `persona.py:321` `devops: can_deploy=True`, no deploy gate anywhere — FAIL vacuous.
- `cli/dev.py:1632` `filter_tools` applied only in REPL `_get_tools`; `core/agent.py:322` injects persona prompt but tool schema path unclear; `mcp_server.py:53` `JARVIS_TOOLS` unfiltered; `webui/api.py:177` `MCP_WRITE_TOOLS` ≠ `CAPABILITY_TOOLS` ≠ agent allowlist — three taxonomies — FAIL leak.
- `providers/telegram.py:129,167` chat_id allowlist only, no persona/project check — WARN privilege flattening.

(5) PRIVACY provider_registry CONSUMERS: grep `provider_registry|route_for_persona|REGISTRY` → only defined, never imported — zero consumers — FAIL privacy routing unenforced; only `circuit_breaker` regex gate live.

(6) TOOL AVAILABILITY LEAK: `persona.py:359` `tools==[]` (jarvis default) = all tools; callers forgetting `filter_tools` (agent, MCP, WebUI, Telegram `handle_message:165`) hand model full set incl. `hackmd_write/vault_sync/execute` — FAIL; no per-project/context tool scoping (`workspace.py:304` context read-only, not enforced).

(7) CONTEXT CONTAMINATION singletons/global env:
- `core/eventbus.py:305,308` `global _bus/get_bus()` — FAIL cross-session/project event bleed (+ `commands.py:303`, `state.py:222`, `notifications.py:370`, `system_adapter.py:363` same pattern).
- `core/intents.py:171` `global _classifier`, `core/tokens.py:43` `global _est_total/_real_total`, `providers/llm.py:206` `_health_cache`, `llm_llama_cpp.py:93` `_info_cache` — WARN cross-session calibration/health bleed.
- `webui/api.py:286,290` HTTP handler mutates `os.environ[JARVIS_LLM_*,TAVILY_API_KEY]` process-global — FAIL critical session leak.
- `webui/api.py:732,758` `projects_list._cache/_cache_ts` function-attr 60s shared — WARN stale cross-user.
- `core/paths.py:31` `contextvar` — PASS; but `cli/dev.py:1964,1966` `set_project_root+os.chdir` process-global cwd — FAIL project escape/contamination.

---

