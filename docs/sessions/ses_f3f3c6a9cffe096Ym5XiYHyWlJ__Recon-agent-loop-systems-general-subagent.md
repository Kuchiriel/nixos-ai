# Recon agent loop systems (@general subagent)

- **sessão:** `ses_f3f3c6a9cffe096Ym5XiYHyWlJ`
- **quando:** 2026-09-20 21:40 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 14 (exportadas: 5)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

In /home/nixos/projects/nixos-ai, reconstruct the AGENT EXECUTION stack as it exists TODAY (repo is source of truth). Code in modules/ai/jarvis/src/jarvis/. Cover: Core Agent loop (core/agent.py: turn structure, model calls, tool dispatch, retries, timeouts, completion, memory/RAG/lessons insertion points), context assembly (context_budget.py, what layers go into the prompt and token accounting), completion/verification (core/completion.py, validators, world checks), model routing (core/model_registry.py, models.nix routing, select_model), CLI/dev loop (cli/, two-loop separation vs core loop), benchmark infra (core/eval_harness.py, core/benchmark.py, benchmarks/ dir, tests/test_eval_harness.py). For EACH report: source file + key functions/symbols, who calls it, what is enforced vs advisory (prompt-only policy vs executable gate), tests, known failure modes. Return a compact structured map. Do NOT modify anything. Research only.

---

## · ?

Reconstructing your agent execution stack from the repo — mapping the loop, context, routing, and verification.

---

## · ?

Core loop, context budget, and completion mapped — now digging into routing, CLI separation, and benchmarks.

---

## · ?

Benchmark tests and model tiers mapped — now pulling the security gates, router, and dev-loop details.

---

## · ?

# AGENT EXECUTION STACK — nixos-ai TODAY (repo = source of truth)

Base: `modules/ai/jarvis/src/jarvis/`. Nix source: `modules/ai/models.nix:routing` → `registryJson` → `/etc/jarvis/model-registry.json` (`JARVIS_MODEL_REGISTRY` override).

## 1. Core Agent loop — `core/agent.py` (~3020 lines)

**Key symbols:** `Agent.__init__`, `Agent.run(prompt)->AgentResult`, `Agent._get_llm_response`, `Agent._finalize`, `Agent._repair_malformed_tool_args`, `Agent._draft_plan`, `Agent._ensure_routed_model`, `Agent._try_api_cascade/_stuck_or_cascade`, `Agent._strict_extra/_strict_signatures/_strict_to_response`, `Agent._exec_read_file/_exec_list/_exec_write/_exec_book/_parallel_read_batch/_grammar_json_rewrite`, module helpers `_unexecuted_script_note/_unread_refs_note/_placeholder_script_note/_partial_coverage_note/_secret_worked_example/_check_run_json_artifacts/_missing_binary_hint`, `extract_fallback_tool_call(s)`, `_normalize_tool_call/_extract_json_object/_truncate_history_for_send`, `detect_profile/_registry_tier_profile/_ctx_derived_max_tokens/_strict_default`, `TOOL_USE_DISCIPLINE`, `BOOK_TASK_HINTS`, `MAX_TURNS=8` (`JARVIS_AGENT_MAX_TURNS`), `MAX_TIME_S=600` (`JARVIS_AGENT_MAX_TIME_S`), `TOOL_OUTPUT_MAX_CHARS=8000`, `AgentResult{commands_run/denied, final_response, turns, verified, verdict VERIFIED|UNVERIFIED|STUCK|FAILED, evidence, missing, steps, plan, api_fallback/api_model, messages}`.
**Turn structure (per `run` iteration):** wall-clock check → `_get_llm_response` → `_repair_malformed_tool_args` + `finish_reason==length` streak → append response → `turn_budget` account + overflow-stop → fallback tool-call parse (`<tool_call>`/fenced/bare JSON, plural xLAM list ≤3) → no-call branch = `check_completion` + ≤2 `verify_turns` with typed `STATE(no_tool_call)` nudge → `LoopDetector.check` → dispatch (`execute_shell|read_file|list_directory|write_file|str_replace|sanitize_secrets|build_json_dataset|book_*|synthesize_command`) → `_check_run_json_artifacts` → `validator.validate` → record step → `error_seen` 2x-nudge/3x-STUCK → end-of-turn notes (COVERAGE, worked-example, trunc note, unexecuted/unread/placeholder, PROGRESS-CHECK turns 5/11, DONE_SANITIZE break) → loop end: empty-final→forced STUCK, else `_finalize`.
**Model calls:** only via `LLMClient.chat_with_tools` (`_get_llm_response`), profile from `detect_profile`, `role="orchestrator"`, strict mode = `response_format json_schema{tool,arguments}` only pre-first-tool-result + signatures appended once to system msg. Telemetry chars (`sys/tools/msgs`) stamped on `session_telemetry.last`.
**Tool dispatch:** reads parallel iff whole turn is >1 `read_file` (`ThreadPoolExecutor ≤3`, 60s each, order-preserving, `contextvars` copy); everything else serial. `execute_shell` only offered if `mcp_servers` non-empty; `book_*` gated by prompt keywords; `build_json_dataset`/`sanitize_secrets`/`synthesize_command` progressively disclosed (data/secret-task/bar-repeat/artifact-repeat/echo-ban).
**Retries/timeouts (all harness, not model):** `run_shell` 60s (timeout→observation `exit -1`, tree-kill via `killpg`); parallel-read 60s slot; `ensure_model` lock 330s / load+poll 300s; LLM timeout from `Config.llm_timeout`; run wall-clock 600s→honest STUCK; same `(name+args)` error 2x→typed redirect, 3x→STUCK-or-cascade; loop warnings 2 consecutive→STUCK-or-cascade; malformed-args-only turns 3 consecutive→STUCK; `length` 3 consecutive→prose-plan escalation; API cascade exactly 1×/run, fresh `system+prompt` only, only on 3 STUCK paths (loop-ABORT/FORCE_ANSWER, 2 ignored warnings, 3× same error), only if env key present.
**Memory/RAG/lessons insertion points:** `memory.lessons(prompt,top_k=3)` → `system_content += AVOID…` (agent.py:1128); `memory.remember_lesson(task/error/fix)` on shell `exit!=0` (agent.py:1583); `ModelPolicy.framing_for` → `MODEL FRAMING`; `UserProfile.build_context_block` → `USER PREFERENCES`; env block (OS/Python/CWD/USER); `_draft_plan` anchor as user msg. No RAG/`HybridSearch` call inside `Agent` — RAG lives one layer up (`router.handle_rag`, `dev.py rag_search/semantic_search`).
**Who calls it:** `cli/main.py:_cmd_agent`, `core/router.py:handle_agent` (`ask`→agent route, voice pipeline), benchmarks via `handle_agent`, tests.
**Enforced vs advisory:** ENFORCED (code gates that deny/stop): allowlist+chaining/pipe/python-file gates (`security.command_allowed`, `has_chaining_operators`), placeholder `<TOKEN>` bars (cmd/path), `.sh`-clobber-via-shell bar, invalid-`.json`-with-zero-producers prefix gate, run-what-you-wrote re-edit bar, move-forward re-polish bar, 4000-char code/data write cap, absolute-container-path poison bar, echo-to-JSON ban (post 2nd artifact-repeat, monotonic), write approval jail (`approve+human_approve`, else deny), completion `_finalize` verdict (DONE requires evidence), STUCK forcings above, budget-overflow stop. ADVISORY (prompt/observation text only, model may ignore): `TOOL_USE_DISCIPLINE`, secret/data/task framings, all `STATE()/COVERAGE/PROGRESS-CHECK/WORKED EXAMPLE` nudges, `validator` warnings (appended `[validation: …]`, `valid=True` always), `LoopDetector` messages, `_anchor_lines` preservation.
**Tests:** `tests/test_agent.py`, `test_completion.py`, `test_validator.py`, `test_loop_detector.py`, `test_model_policy.py`, `test_context_drift` (bans hardcoded sizes).
**Known failure modes:** small-model read-first/write-avoidance + variance dominates (0/9 world-exact B-arm); truncated giant writes→malformed args; placeholder/dummy scripts with exit 0; runtime-generated invalid `.json` invisible to write-gates (caught only by artifact-check/completion); chaining-ban vs fused `chmod && ./` idiom (carve-out only strict form); container-absolute paths; `&&`-less two-call discipline ignored; verification budget (2 turns) exhausted→UNVERIFIED; silent empty finish→forced STUCK.

## 2. Context assembly — `core/context_budget.py` + `core/tokens.py` + `core/provider_registry.py`

**Key symbols:** `ContextBudget{max_tokens=32000,reserved=2000,warn 0.80,compact 0.85, add_message/estimate_tokens/record_actual/record_actual_for_text/sync_from_slots/truncate_tool_outputs/compress_history/should_compact/get_recommendation/get_stats/to_dict/from_dict}`, `SessionTelemetry/TelemetryCall{record,window_bar,render,payload_summary}`, `ContextSnapshot`, `query_server_context_size` (/props→registry `_registry_ctx`→0), `CHARS_PER_TOKEN=4`, `TOOL_OUTPUT_PRIORITY/TRUNCATE_LIMITS`, `_anchor_lines` regex (verdicts/paths/`/home/nixos/…` never dropped).
**Layers into prompt (Agent):** `You are JARVIS` + `TOOL_USE_DISCIPLINE` + `TASK MODE: SECRET-SANITIZATION` (iff secret-task) + persona addition (explicit `persona_id!=jarvis` always; implicit only forensic/audio/audit tasks — H2) + `USER PREFERENCES` + `ENVIRONMENT` + `AVOID (past errors): lessons` + `MODEL FRAMING` + user prompt + optional anchored plan. (Dev loop instead: `repo_map + memory_context + agent_context(AGENTS.md-nearest-first ≤3KB/file + pinned ≤8K) + persona_block + discipline`; plus `SYSTEM PATHS` allowlist in repo map.)
**Token accounting:** estimate via `tokens.py` single interface (calibrated by real `usage.prompt_tokens` via `record_actual_for_text`); real server numbers (`usage/timings/slots`) in `SessionTelemetry`; per-prompt fresh `turn_budget` seeded from shared budget's `max_tokens` (avoids /props re-query + cross-prompt leak); send-path uses `_truncate_history_for_send` copy (`_HIST_TOOL_BUDGET=12000, KEEP_LAST=2, FLOOR=500`, tool-role only, never mutates stored history); per-tool `content[:8000]`; dev loop separate: `_estimate_tokens`, `_trim_messages(20, user-boundary-safe)`, `_compact_session`, auto-compact at 70%→50% of server `n_ctx`.
**Who calls it:** `Agent.run` (turn_budget) + `_ensure_routed_model` (re-create on switch), `dev.py` (`_compact_session/_trim_messages/_call_llm` telemetry), `/stats`, metrics.
**Enforced vs advisory:** ENFORCED: overflow→stop-with-note; send-copy truncation; output caps. ADVISORY: `get_budget_warning/get_recommendation/should_compact` strings, anchor preservation, compaction summaries.
**Tests:** context-budget/estimate tests, `test_context_drift` (no hardcoded sizes outside source), telemetry render tests.
**Failure modes:** `/props n_ctx=0` when unloaded→registry fallback or stale budget (fixed per §23); msgs 51%+ payload growth (dedup pointer for identical re-reads); tiny-model degradation past threshold; anchor regex misses novel verdict formats.

## 3. Completion / verification — `core/completion.py` (+ `core/devtools.py` jail)

**Key symbols:** `check_completion(messages,project_root)->CompletionVerdict{VERIFIED|UNVERIFIED|STUCK|FAILED,evidence,missing}`, `_finalize` (Agent), `missing_deliverables` (reused mid-run PROGRESS-CHECK), `classify_error` (transient|policy|missing|bad-request|failed|ok), `_successful_calls` (non-ERROR tool results; `book_*` excluded), `_claimed_artifacts/_claimed_contents/_claimed_change/_claimed_content_change/_claimed_noop/_denied_but_observed/_pending_recovery_notes`, `_residual_secret_in_file/_residual_secret_paths`, `_shell_write_paths` (redirect/tee), `_mutating_shell`, `_PLACEHOLDER_VALUES/_PLACEHOLDER_TOKEN`, `_HANDOFF/_NOOP_CLAIM/_CHANGE_VERBS`, per-type checks: `.py` AST-parse, `.parquet` PAR1 header, `.sh` exec-bit + must-have-run + `chmod`-separate, `recover.json` must-touch-sqlite, root `*.json` parse + placeholder-value scan + missing-quote diagnosis.
**Rules (P0, structural, no NLP intent):** zero successful tools→UNVERIFIED; trailing tool error→miss; open `STATE(unexecuted_script/unread_refs)`→never VERIFIED; claimed artifact without write/redirect/deterministic-tool output→miss; claimed content without read/write grounding→miss; claimed modification without mutating action→miss; content-change claim without successful content-write→miss; bare-number write unseen in observations→miss; residual secret shapes→miss; noop/handoff ending with no substance→UNVERIFIED; else VERIFIED+`sem erro final; artefatos verificados`.
**Who calls it:** `Agent._finalize` (every exit), no-call branch mid-loop, `missing_deliverables` at turns 5/11, `dev.py` does NOT call it (see §5).
**Enforced vs advisory:** ENFORCED: verdict fields on `AgentResult` (`verified` bool drives `ux_driver --world-check`, rc honesty); pre-execution write/shell bars listed in §1. ADVISORY: `missing[]` strings are hints, not blocks — loop may continue until budgets.
**Tests:** `tests/test_completion.py` (trailing-error, missing-artifact, AST-fail, zero-ground-truth, noop/handoff, placeholder-JSON, parquet, unexecuted-sh, secret-residual).
**Failure modes:** vacuous-pass (valid syntax, placeholder semantics — mitigated by value scan); shell-generated artifacts bypass write-gates until artifact-check/completion; suffix-match grounding (`nota.txt` vs `trabalho/nota.txt`) can over-credit; single top-level `*.json` scan misses subdir outputs; numeric-epsilon (`1e-9`) false-miss on rounded values.

## 4. Model routing — `core/model_registry.py` + `core/model_policy.py::select_model` + `core/model_lifecycle.py` + `models.nix:routing`

**Registry:** `ModelRegistry.load(path=env>default>fallback).get(id)`; validates `version==1`, non-empty `models`, per-model `capabilities[]`, `default∈models`. Live rows: `bonsai{speed,ctx 49152,8B,2400MB,needsWrapper llama-prism-wrapper}` (default, serves :8080), `jarvis-fast{fast,ctx 49152,4B,2600MB}`, `jarvis-strong{reasoning,ctx 32768,35B,4600MB,mmproj-CPU}`; `maxResident=1` (6GB VRAM). `_FALLBACK` mirrors structure only (parity tests flag content drift).
**Selection:** `select_model(requirements{capabilities,tier,stage→tier,local_only})` — capabilities HARD (`ModelRouteError`, never silent downgrade), tier SOFT (cheapest eligible + `reason{tier_fallback}`); `_TIER_RANK speed<fast<reasoning`. `Agent._ensure_routed_model` (only if `model_requirements` set) → `ensure_model` (flock-serialized, noop-if-active, re-check under lock, `POST /models/load`, phased timeouts, `SwitchReport`) → swap `config.llm_model`+`LLMClient` + fresh `ContextBudget`. Per-turn profile: `_registry_tier_profile` wins over param-count regex (`detect_profile`); `max_tokens=ctx//12` (~8%), reasoning pinned 768; `strict_tools` default True for speed/fast (H-strict), False otherwise/registry-absent.
**API cascade (not local routing):** `_api_layer_for(prompt)→classify|docs|batch|dev`; `cascade_for(layer)` ordered `(provider,model,base_url,env_key)` (openrouter/zen/nvidia); `cascade_key_present`; 1 attempt/run (see §1).
**Who calls it:** `Agent` (`_ensure_routed_model`, `_draft_plan` planner routing, `_try_api_cascade`), `dev.py::_detect_profile/_query_server_context_size`, router/voice, `hwprofile`.
**Enforced vs advisory:** ENFORCED: registry validation errors, capability hard-fail, ensure errors propagate, tier-fallback logged in reason, lock serialization. ADVISORY: `ModelPolicy.select_tier/STAGE_TIER_MAP/WORKFLOW_TIER_MAP` (VRAM downgrade hints), `MODEL_FRAMINGS/framing_for` prompt text, stage→tier legacy map.
**Tests:** `tests/test_model_policy.py` (capability-hard, tier-soft, stage map, cascade order/key gating), registry parity tests.
**Failure modes:** registry JSON absent→fallback (wrong ctx/VRAM); single-resident flips thrash A/B runs (lock serializes but slow); param-count fallback mis-tiers non-registry ids (e.g. cloud); `default` change without decision breaks product (§21); dead/free-tier API slugs (opencode lesson: `openrouter/free`).

## 5. CLI / dev loop — `cli/main.py` + `cli/dev.py` (two loops ≠ core loop)

**`cli/main.py`:** thin argparse; `_cmd_agent` (builds `Agent(cfg,approve,audit,mcp_servers{EpisodicMemory best-effort})`, prints response+run/denied lists, rc=2 if any denied) and `_cmd_ask` (`route_request`→`handle_fastpath|doctor|nixos|rag|read|agent`, cheapest-first, `out[_route]` stamped). No loop logic here.
**`cli/dev.py` (second, independent loop):** `dev_repl` (persistent REPL: `/quit|clear|compact|status|map|add|drop|undo|model|stats|recall|lessons|vault|architect|reasoning|modes|debug|help`, prompt_toolkit paste-safe, `_persist_session/_resume_session`, yolo/approve-all) and `dev_once(task,…,max_turns=10,transcript)` → both drive `_run_agent_loop(messages,tools,profile,max_turns=30,reasoning)` + `_call_llm` (own `LLMClient` wrapper, debug dump) + `_execute_tool_call→handle_dev_tool` (21 tools incl. `semantic_search/rag_search/rag_index/nix_*/browser/capture/vision/memory/vault/web_search/read_chatgpt`, file tools with AST-guard/backup/fuzzy, `_auto_commit` Aider-style). Own guards: `LoopDetector` (ABORT→`return False`), auto-compact 70%→50%, `_validated_output` (validator warnings ≤6 appended), approval prompts for shell/browser-mutations.
**Separation vs core loop:** core `Agent.run` = evidence-gated autonomous run (verdict, audit JSONL, STUCK honesty, world checks, single-shot); dev loop = interactive session (success = pure-text reply, NO `completion.py` verdict, NO `AgentResult`, own history trim/compact/persist, richer tool surface). They share only `TOOL_USE_DISCIPLINE`, `LoopDetector`, `ToolValidator`, `LLMClient`, `EpisodicMemory`.
**Enforced vs advisory:** dev ENFORCED: approval gates, loop-ABORT, compact, jail in devtools. Dev ADVISORY: validator hints, repo-map/memory context, persona/mode text.
**Tests:** dev REPL/loop tests, `_trim_messages` orphan-tool test, transcript-shape tests.
**Failure modes:** dev loop can return rc=0 on unverified text (no completion gate); two profiles can disagree (`_detect_profile` vs `detect_profile`); session-resume can restore stale system prompt (re-stamped on load); auto-commit can surprise git state.

## 6. Benchmark infra — `core/eval_harness.py` + `core/benchmark.py` + `benchmarks/` + `tests/test_eval_harness.py`

**`core/eval_harness.py`:** `TaskTemplate{id,description,prompt,setup/teardown(shlex-split, no shell),success_criteria{exit_code,output_contains/_not_contains,file_exists,file_contains?,world_check,max_turns,max_time_s},timeout 120}`, `TrajectoryStep`, `EvalResult{success,criteria_met,trajectory,turns,time,tool_calls,tokens_in/out,error}`, `EvalHarness(results_dir){run_task(agent_fn→{response,tools_called,turns,…}),compare(conditions×tasks→{success_rate,avg_turns/time/tool_calls/tokens_in/out,tasks[]}),save_results(JSONL),summary()}`, `JARVIS_EVAL_TASKS` incl. `tb-hello-world` (file_exists + `world_check: grep -qx 'Hello, world!'`, teardown rm). `world_check` = external `shlex.split` command, exit 0 = pass (proves world, not LLM word). `compare` = controlled A/B (same tasks, N pipelines; caller holds model/env/timeout equal).
**`core/benchmark.py`:** cascade-latency bench: `ROUTE_CASES{fastpath 200ms,doctor 500ms,nixos 1500ms,rag 1500ms,agent 30000ms}`, `run_benchmark/bench_report/main_benchmark(--top-k,--json)`, `BenchResult{route,query,ms,meta_ms,ok→OK|LENTO|ERROR}`; never-throws per-route. Complements `core/eval_rag.py` (NDCG/Recall@k) and `core/regression.py` (bench+eval vs baseline, `--offline` CI mode).
**`benchmarks/experiment_tracker.py`:** `ExperimentTracker.start_experiment/record_run/compare` — model/backend/HW-temp/clock/power/VRAM + tg/pp throughput + reproducibility meta (llama/prism/bonsai backends).
**Tests (`tests/test_eval_harness.py`):** run success/fail/tools/exception/save/summary/trajectory; `TestWorldState` (pass, LLM-lie→world vetoes despite `output_contains`, malformed `args_preview`→`{raw}`, tokens passthrough); `TestCompare` (per-condition isolation, token aggregation); `TestTbHelloWorld` (exact-content pass, wrong-content `file_exists✓/world✗→fail` — terminus-2 mode); plus browser-dispatch regression (§17).
**Who calls it:** `jarvis benchmark|eval-rag|regression`, idle worker (`eval-rag` daily), H1/H2/H3 + A/B studies, CI.
**Enforced vs advisory:** ENFORCED: `success=all(criteria)` (world_check can veto text-match — anti-false-green); shlex (no shell) setup/teardown/world commands. ADVISORY: latency metas, token-efficiency tiebreak notes, experiment comparisons.
**Known failure modes:** n=1/arm variance decides nothing (H1 INCONCLUSIVE→needs n≥5/arm via `compare`); rc=0≠world-state (fixed by `--world-check`); malformed LLM args previously false-failed (now `{raw}`); `/tmp` collisions across arms; GPU-pin stalls counted in time but not attributed.

---

