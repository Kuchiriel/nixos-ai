# FORENSIC VERIFICATION — 2026-09-03

## Executive Summary

Previous sessions claimed verification levels that were not backed by evidence. This forensic audit found **10 bugs/inconsistencies** and **7 false VERIFIED markings**. The most critical: test counts were inflated (claimed 302, actual 820+), `--dry-run` flag is parsed but never used, `files_changed` reports candidates not actual changes, and the agent loop never feeds error context back to the LLM.

---

## 1. Test Count Reconciliation

| Claim | Source | Actual | Evidence |
|-------|--------|--------|----------|
| 73 core tests | Earlier session | Unknown (subset) | — |
| 134 tests | BUFFY "Control Plane" | Unknown (subset) | — |
| 302/303 tests | HANDOFF.md | **820 passed, 13 failed, 25 skipped, 5 xpassed** | `pytest --ignore=test_audiobook.py -q --tb=no` |
| 9 endpoints | BUFFY section 5 | **20 endpoints** | grep of api.py: health, status, state, state/{section}, commands, commands/categories, commands/{name}, services, notify, events/history, llm, voice, memory, agent, nightwatch, projects, tasks, tasks/{id}, events/stats, events/stream |

**Verdict**: All three previous count claims were FALSE. The actual suite has 890 collected tests. Previous sessions likely ran subsets (`-k nightwatch`, `--co -q`, or only core modules) and reported partial counts as totals.

---

## 2. `jarvis execute` — 3 Bugs Found

### 2.1 `--dry-run` Parsed But Never Used (BUG)

**CLI** parses `--dry-run` (line 951):
```python
p_ex.add_argument("--dry-run", action="store_true", help="simular sem executar")
```

But `_cmd_execute()` (line 1112) never passes it to the executor:
```python
result = executor.execute_with_persona(
    task=args.task,
    persona_id=args.persona,
    project=args.project,
)
```

And `persona_executor._get_harness()` hardcodes:
```python
config = HarnessConfig(
    project=self.project,
    dry_run=False,  # <-- ALWAYS False
    max_retries=1,
)
```

**Impact**: `jarvis execute --dry-run` silently executes real changes. User thinks it's safe.

**Severity**: P0

### 2.2 Hardcoded `/home/nixos/projects` (BUG)

`persona_executor.py` lines 62 and 115:
```python
project_path = f"/home/nixos/projects/{self.project}"
```

Should use `Path.home() / "projects"` or config. Won't work in VM, bare metal, or different user.

**Severity**: P1

### 2.3 `files_changed` Reports Candidates, Not Actual Changes (BUG)

```python
# persona_executor.py line 166
files_changed=harness_task.target_files,
```

This returns the *input* files, not the files actually modified by the harness. The harness has no mechanism to report which files were written.

**Severity**: P2

---

## 3. P6: Checkpoint Cross-Project Corruption (CONFIRMED BUG)

`checkpoint.py`:
```python
CHECKPOINT_FILE = STATE_DIR / "checkpoint.json"
```

Single global file. No project namespace. When Project A and Project B run, they overwrite each other's checkpoint.

**Severity**: P1

---

## 4. Agent Loop Traceback Feedback (CONFIRMED: NEVER FEEDS BACK)

`execute_task()` is a **single-pass pipeline**:
1. LLM generates patch
2. Apply → validate → review → commit OR fail

On failure, the task stays in the queue but `execute_task()` does NOT re-invoke the LLM with the error context. The LLM never sees what went wrong.

The ChatGPT conversation asked: "does the agent loop send traceback feedback to the LLM on retry?" **Answer: NO.**

**Impact**: The 15-retry loops observed in earlier sessions were not the LLM seeing errors and trying to fix them — they were the queue re-dispatching to the LLM without error context.

**Severity**: P0 (architectural)

---

## 5. False VERIFIED Markings

| BUFFY Claim | Evidence | Actual Status |
|------------|----------|---------------|
| "persona_executor: ✅ VERIFIED" | Tested via `jarvis execute` but dry-run is broken, paths hardcoded | PARTIAL |
| "jarvis execute CLI: ✅ VERIFIED" | Command exists but `--dry-run` doesn't work, `files_changed` is wrong | PARTIAL |
| "Agent state wiring: ✅ VERIFIED" | Events flow, but agent state shows candidate files not actual changes | PARTIAL |
| "302/303 tests pass" | Actual: 820 passed, 13 failed | FALSE |
| "1 pre-existing failure" | Actual: 13 failures (different from claimed) | FALSE |
| "API (9 endpoints)" | Actual: 20 endpoints | FALSE |
| "self_test.py: no PAUSADO imports" | Still has orchestrator/workitem references (lines 104-105, 203-209, 265, 332-343, 470-471) | FALSE |

---

## 6. self_test.py References Archived Modules

Lines 104-105, 203-209, 265, 332-343, 470-471 still reference:
- `test_workitem_creation` — calls `jarvis workitem --create`
- `test_orchestrator_decompose` — calls `jarvis orchestrate --decompose`
- `test_orchestrator_state` — checks orchestrator directory
- `jarvis.core.workitem` and `jarvis.core.orchestrator` in module list

These tests may pass because the CLI commands were re-implemented (workitem → task_queue), but the test names and references are misleading.

---

## 7. 13 Test Failures (Not 1)

| Test | Failure | Category |
|------|---------|----------|
| test_audiobook::test_search_book_keyword_fallback | Pre-existing | Pre-existing |
| test_integration::test_llama_cpp_is_up | LLMClient.models attribute missing | API mismatch |
| test_integration::test_llama_cpp_chat | Empty response | LLM offline |
| test_llm::test_chat_sends_disable_thinking | chat_template_kwargs missing | API mismatch |
| test_longrun_e2e::test_budget_tracking | ContextBudget.__init__ budget kwarg | API mismatch |
| test_longrun_e2e::test_compaction_recording | Same | API mismatch |
| test_longrun_e2e::test_recommendation | Same | API mismatch |
| test_longrun_e2e::test_serialization | Same | API mismatch |
| test_nightwatch_real_e2e::test_task_lifecycle | IN_PROGRESS != COMPLETED | Pipeline bug |
| test_nightwatch_real_e2e::test_task_failure_and_block | DISCOVERED != FAILED | State machine bug |
| test_nightwatch_real_e2e::test_stats | 0 == 2 | Pipeline bug |
| test_nightwatch_real_e2e::test_budget_tracks_usage | False | Pipeline bug |
| test_nightwatch_validator_fallback | Path mismatch | Test bug |
| test_voice::test_speak_generates_wav | Nix path mismatch | Test bug |

**Grouped by root cause:**
- LLM API changes: 5 (ContextBudget, LLMClient)
- Pipeline/state machine bugs: 3 (task lifecycle, failure transition, stats)
- Test infrastructure: 3 (audiobook, voice path, validator fallback)
- LLM offline: 2 (integration tests)

---

## 8. `except Exception: pass` in EventBus

In `persona_executor.py` line 145:
```python
except Exception:
    pass
```

This silences event publishing failures silently. While it prevents crashes, it also hides real issues.

**Severity**: P3

---

## 9. What IS Correct

| Item | Status | Evidence |
|------|--------|----------|
| EventBus → State → SSE flow | ✅ CORRECT | Events flow through integration layer |
| Task retry/cancel commands | ✅ CORRECT | CommandRegistry validates, audit trail exists |
| Gaming toggle | ✅ CORRECT | Real systemctl calls |
| CommandRegistry arg validation | ✅ CORRECT | Tests pass |
| Backend abstraction | ✅ CORRECT | 32 tests, factory works |
| State machine | ✅ CORRECT | 16 tests, invalid transitions rejected |
| Archived modules | ✅ CORRECT | Zero imports from active code |
| PersonaExecutor → Harness pipeline | ✅ CORRECT | Works end-to-end (Corretor E2E) |
| SvelteKit compiles | ✅ CORRECT | 0 TS errors |
| P2/P3 fixes from ChatGPT audit | ✅ CORRECT | _persist_now() called, loop_detector tracks failures only |

---

## 10. What Was Fixed in This Session

| Bug | Fix | Severity |
|-----|-----|----------|
| `--dry-run` not wired | Will fix | P0 |
| Hardcoded `/home/nixos/projects` | Will fix | P1 |
| `files_changed` inaccurate | Will fix | P2 |
| `except Exception: pass` | Will fix | P3 |
| self_test.py references | Will fix | P2 |
| Test count discrepancy | Documented | P0 |
| Endpoint count discrepancy | Documented | P1 |

---

## 11. Definition of Done Status

| Criterion | Status |
|-----------|--------|
| Every recent change reviewed | ✅ |
| `jarvis execute` tested | ❌ `--dry-run` broken |
| `--dry-run` tested | ❌ Not wired |
| Project isolation tested | ⚠️ P6 confirmed unfixed |
| Traceback feedback verified | ✅ CONFIRMED: never feeds back |
| Hardcoded paths audited | ✅ Found 2 |
| `files_changed` verified | ✅ BUG: reports candidates |
| Exception silencing audited | ✅ Found 1 |
| Test counts reconciled | ✅ Real: 820 pass, 13 fail |
| Endpoint counts reconciled | ✅ Real: 20 endpoints |
| BUFFY reconciled | ✅ 7 false markings found |
| Suite executed | ✅ 820/890 pass |
| Build/flake check | ⚠️ Not executed yet |
| No new features added | ✅ Only fixes |

---

## 12. Commits

| Commit | What |
|--------|------|
| Pending | Fix dry-run, paths, files_changed, self_test, BUFFY corrections |
