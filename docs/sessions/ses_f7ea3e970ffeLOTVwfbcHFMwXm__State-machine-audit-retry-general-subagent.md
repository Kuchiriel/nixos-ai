# State machine audit retry (@general subagent)

- **sessão:** `ses_f7ea3e970ffeLOTVwfbcHFMwXm`
- **quando:** 2026-09-08 14:11 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 16 (exportadas: 6)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

In /home/nixos/projects/nixos-ai (read-only, NO edits), audit STATE MACHINES in modules/ai/jarvis/src/jarvis/: (1) Session lifecycle (create/use/close/recreate — session classes, what persists, leaks: subscriptions, tools, project root, persona, telemetry); (2) Agent run states; (3) Tool call states + cancellation (does cancel reach subprocess?); (4) LLM request states + retry/timeout/breaker semantics; (5) asyncio.create_task without owner/await/cancel (task leaks); (6) EventBus delivery semantics + subscriber death/slow subscriber; (7) datetime.now/time.time usage — wall clock vs monotonic for durations. For EACH: file:line + verdict (OK / SUSPECT:reason / BUG:reason). Max 90 lines. Do NOT fix.

---

## · ?

Auditing session, agent, and tool state machines — read-only sweep for leaks and hangs.

---

## · ?

Initial patterns mapped — now digging into lifecycle, cancellation, and clock usage.

---

## · ?

Core flows charted — now verifying cancellation paths and timing sources.

---

## · ?

Almost complete — pulling final evidence on sessions, timeouts, and subscribers.

---

## · ?

AUDIT — `modules/ai/jarvis/src/jarvis/` (read-only, no fixes)

(1) Session lifecycle
- `providers/llm.py:226` + `llm_llama_cpp.py:342` + `llm_prismml.py:243` close `requests.Session` — OK.
- `core/agent.py:258-293` creates `LLMClient` (`:271`) but `Agent` has no `close/shutdown/__exit__` — SUSPECT:pool/session leak on recreate.
- `core/agent.py:211,604` imports `MCPClient` but never `start()/close()`; `mcp_servers` only builds tool schemas — SUSPECT:dead lifecycle / orphan proc if ever started elsewhere.
- `core/persona_executor.py:61-82` caches `Harness` in `_harness`, never closed; `:71-73` `set_project_root()` mutates global env, never restored — BUG:project-root/persona/harness persists across projects (bypasses `use_project_root` ctxvar in `core/paths.py:80` — OK).
- `core/context_budget.py:106-124` `SessionTelemetry.calls.append` unbounded, no cap/clear — SUSPECT:telemetry leak per session.
- `cli/dev.py:341-348` `SessionTelemetry` singleton lazy — OK (intentional), but never reset between `dev_once` — SUSPECT:cross-task token bleed.

(2) Agent run states
- `core/agent.py:382-403` turn loop `MAX_TURNS=8 (:217)`, overflow→break with final_response fallback — OK.
- `core/agent.py:420-430` `loop_detector ABORT/FORCE_ANSWER→break`, 2×warn→break, `reset() :368` per prompt — OK.
- `core/agent.py:470,489` `run_shell()` raises `TimeoutExpired`; no `try` in loop (only audit `IOError :309`) — BUG:tool timeout aborts whole `run()` unhandled, no `final_response`/state save.
- `core/agent.py:312` `run()` sync, no `cancel()`/`stop_event`/`KeyboardInterrupt` hook — SUSPECT:no cooperative abort.
- `cli/dev.py:1811-1908` `_run_agent_loop(max_turns=30)`: LLM exc→`return False` (drops turn state), max_turns→`False` — OK (terminal), same no-cancel — SUSPECT.

(3) Tool call states + cancellation
- `core/security.py:122-130` `run_shell`: blocking `subprocess.run(timeout=60)`; cancel never kills proc — BUG:cancel doesn't reach subprocess.
- `webui/api.py:852-870` `task_cancel` only `task.abandon()+_save()+SSE`; no handle to running harness/tool proc — BUG:logical-only cancel.
- `providers/mcp.py:119-143` `call_tool/_request` 60s poll loop, no cancel flag/event; `close() :82-92` terminate→wait(3)→kill — OK for lifecycle, SUSPECT for in-flight call (blocked thread uninterruptible).
- `mcp_server.py:720-758` `Popen+terminate/wait(3)/kill` on TimeoutExpired — OK.
- `cli/dev.py:1086-1130` `_execute_tool_call` `subprocess.run(timeout 30/120)` no cancel token — SUSPECT:same as run_shell.

(4) LLM request states + retry/timeout/breaker
- `providers/llm.py:78-150` CLOSED/OPEN/HALF_OPEN + `threading.Lock`, `monotonic` — OK.
- `providers/llm.py:413-465` `chat_stream/achat_stream`: `before_call` inflight=1, but early consumer abandon (generator GC/break) skips `record_success/failure` → `half_open_in_flight` stuck — BUG:breaker pinned in HALF_OPEN.
- `providers/llm.py:481-487` `embed()` bypasses `before_call/record_*` — SUSPECT:breaker blind spot.
- `providers/llm.py:354-359,391-396` error classify by `"timeout"/"connection" in str(exc)` not status — SUSPECT:fragile; `_classify_error_response :153` (status-based) unused on this path.
- `providers/llm_llama_cpp.py:43-54` + `llm_prismml.py:40-52` urllib3 `Retry total=3, forcelist 429/500/502/503/504, POST allowed` — SUSPECT:retries non-idempotent chat POST; 400-overflow correctly excluded — OK.
- `providers/llm.py:232-247` health cache TTL 2s `monotonic` — OK. `chat_with_tools :376` breaker-gated — OK.

(5) `asyncio.create_task` leaks
- `core/eventbus.py:208` `start()` task stored in `_tasks`, `stop() :210-220` `wait_for(5)+cancel+clear` — OK.
- `core/eventbus.py:287-288` `create_task(_deliver_async)` + `gather(*tasks, return_exceptions=True)` awaited — OK (owned).
- No other `create_task/ensure_future` in `jarvis/` (only eventbus) — OK. `core/multi_ai_reader.py:132` `browser.close()` — OK.

(6) EventBus delivery + subscribers
- `core/eventbus.py:247-272` per-sub task isolation + `wait_for(timeout_s)` + DLQ — OK; slow parallel sub doesn't block (`:287`) — OK; `ordered=True :289` sequential after parallel — OK (slow ordered blocks by design).
- `core/eventbus.py:179` `_dispatch_sync` calls `sub.handler(event)` without `iscoroutine` check (async path `:256` has it) — BUG:async subscriber silently dropped in sync/CLI mode.
- `core/eventbus.py:266` `except Exception` — `CancelledError(BaseException)` propagates through `gather(return_exceptions=True)` cancel semantics — SUSPECT:cancel of one sub can poison batch.
- `core/eventbus.py:99,185,233,264` `_dlq: list` unbounded append, no cap — SUSPECT:DLQ leak.
- `control_plane/integration.py:62-114,369` + `plane.py:71` permanent `subscribe(cp-*)`, no idempotency; re-`setup()` duplicates handlers — BUG:subscriber leak/double-delivery. `webui/api.py:922-943` SSE subscribe/unsubscribe — OK.
- `control_plane/state.py:195-208` `_notify` swallows handler exc, iterates live list (mutation during notify unguarded) — SUSPECT:skip/dupe on concurrent unsub.

(7) Wall vs monotonic clock
- Durations on `monotonic`: `llm.py:342,377,414,447`, backends `llm_llama_cpp.py:107`, `llm_prismml.py:108`, `eval_harness.py:111`, `benchmark.py:51 perf_counter`, `regression.py:59 perf_counter` — OK.
- Durations on wall `time.time()`: `core/circuit_breaker.py:274,289,334,347,373` latency+`elapsed`, `control_plane/commands.py:213-225`, `core/health_monitor.py:100-106`, `core/voice.py:594-752` (`_t_*` deltas), `core/watchdog.py:383-425`, `core/heal.py:235-236` deadline loop, `core/idle.py:200` — SUSPECT:NTP/step skew; use `monotonic`.
- Timestamps on `time.time()` (`Event.ts :40`, `api.py:116,226`, audit `:298`) — OK (wall correct for stamps).
- `core/emotion.py:71,86` `datetime.now(timezone.utc)` — OK. `core/hackmd.py:141`, `core/user_profile.py:154` naive `datetime.now()` — SUSPECT:tz-naive ordering.

---

