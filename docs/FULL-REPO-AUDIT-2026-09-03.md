# FULL REPOSITORY AUDIT — 2026-09-03

## 1. Executive Diagnosis

The nixos-ai repository is a NixOS-based AI agent platform with 171 Python files, 88 Nix files, 19 Svelte components, and 296 TypeScript files. After the consolidation (9 modules archived), the codebase is significantly cleaner but still has structural gaps.

**Critical finding**: The `persona_executor.py` module — the intended entry point for autonomous multi-persona execution — has **zero imports** from anywhere in the codebase. There is no CLI command to invoke it. The autonomous pipeline exists in code but cannot be triggered.

**Overall status**: The Control Plane (events, state, commands, notifications, API, SSE) is functional. The agent pipeline (persona → harness → LLM → validate → commit) works when invoked directly. But the two are not fully connected — there's no CLI command that runs a persona through the full pipeline.

---

## 2. Inventory

| Category | Count | Notes |
|----------|-------|-------|
| Python files | 171 | ~60 core, rest tests/scripts |
| Nix files | 88 | modules, services, home-manager, flake |
| Svelte components | 19 | WebUI frontend |
| TypeScript files | 296 | SvelteKit generated + custom |
| Markdown files | 172 | docs, audits, architecture |
| Test files | ~60 | pytest |
| Archived modules | 9+1 | in archive/core/ |

---

## 3. Dead Code Analysis

| Module | Status | Reason |
|--------|--------|--------|
| `persona_executor.py` | ⚠️ DISCONNECTED | 0 imports, no CLI command, but has real logic |
| `busy.py` | ✅ alive | imported by voice.py |
| `evidence.py` | ✅ alive | imported by CLI |
| `self_test.py` | ✅ alive | imported by CLI |
| All archived modules | ✅ archived | orchestrator, workitem, subagent, context, agent_loop, ast_guard, ast_cache, learning, vision_analyzer |

---

## 4. Security Findings

| ID | Severity | Finding | File:Line | Status |
|----|----------|---------|-----------|--------|
| S1 | P3 | `shell=True` in self_test.py | self_test.py:132 | Acceptable — test harness, args from code not user |
| S2 | P2 | No hardcoded dangerous paths found | — | CLEAN |
| S3 | P2 | No `os.system` calls | — | CLEAN |
| S4 | P2 | No command injection vectors in control_plane | — | CLEAN |

---

## 5. Architecture Gaps

### 5.1 persona_executor — DISCONNECTED (P1)

**Problem**: `persona_executor.py` is the intended entry point for autonomous multi-persona execution. It has:
- Persona selection logic
- Task creation
- Harness invocation
- Event publishing
- State updates

But **nothing imports it**. There's no CLI command like `jarvis execute --persona backend_engineer --project Corretor`.

**Impact**: The autonomous pipeline cannot be triggered from the CLI. The only way to run it is by calling `run_nightwatch()` which uses the harness directly, bypassing persona selection.

**Fix needed**: Add a CLI command `jarvis execute` that wires persona_executor into the CLI.

### 5.2 Checkpoint per-project (P6 from ChatGPT audit)

**Problem**: `checkpoint.json` and `mission_state.json` are single objects. When working on multiple projects, they overwrite each other.

**Impact**: Project A's checkpoint can be lost when Project B runs.

**Fix needed**: Namespace checkpoint/mission_state by project.

### 5.3 Agent loop traceback feedback (UNVERIFIED)

**Question from ChatGPT**: Does the agent loop send traceback feedback to the LLM on retry? If the LLM sees the same error 15 times and still can't fix it, is it a model capacity limit or a loop bug?

**Status**: Never verified. The harness does pass error context, but the quality of that context was not tested.

---

## 6. Control Plane Audit

| Component | Status | Evidence |
|-----------|--------|----------|
| EventBus | ✅ VERIFIED | 73 tests pass, SSE works |
| EventBus unsubscribe | ✅ VERIFIED | UUID-based, cleanup in finally |
| StateStore | ✅ VERIFIED | Reads/writes correctly |
| CommandRegistry | ✅ VERIFIED | Arg validation works |
| NotificationManager | ✅ VERIFIED | All 6 channels have real implementations |
| SystemdAdapter | ✅ VERIFIED | Real systemctl calls |
| API (20 endpoints) | ✅ VERIFIED | All return 200 |
| SSE stream | ✅ VERIFIED | Init + heartbeats + events |
| Agent state | ✅ VERIFIED | Harness events → State Store |
| Tasks | ✅ VERIFIED | Persistent queue, retry/cancel |

---

## 7. WebUI Audit

| Page | Exists | Real Data | Actions | SSE | Status |
|------|--------|-----------|---------|-----|--------|
| Dashboard | ✅ | ✅ Agent status | ❌ | ✅ | PARTIAL |
| Activity | ✅ | ✅ Event history | ❌ | ✅ | PARTIAL |
| Agent | ✅ | ✅ Active task/persona | ❌ | ✅ | PARTIAL |
| Tasks | ✅ | ✅ Persistent queue | ✅ Retry/Cancel | ✅ | VERIFIED |
| Projects | ✅ | ⚠️ Workspace discovery | ❌ | ❌ | PARTIAL |
| Services | ✅ | ✅ Real systemctl | ✅ Start/Stop | ❌ | PARTIAL |
| LLM | ✅ | ⚠️ Health check only | ❌ | ❌ | PARTIAL |
| Voice | ✅ | ⚠️ State only | ❌ | ❌ | PARTIAL |
| Memory | ✅ | ⚠️ Qdrant status | ❌ | ❌ | PARTIAL |
| Commands | ✅ | ✅ Real registry | ✅ Execute | ❌ | VERIFIED |
| Nightwatch | ✅ | ⚠️ Status only | ❌ | ❌ | PARTIAL |
| System | ✅ | ✅ Hardware/services | ❌ | ❌ | PARTIAL |

---

## 8. NixOS/Flake Audit

| Item | Status | Notes |
|------|--------|-------|
| flake.nix | ✅ | Clean, no dynamic imports |
| modules/services | ✅ | Deterministic imports |
| Home Manager | ✅ | Declarative |
| CUDA | ✅ | Properly configured |
| Firewall | ✅ | Services on localhost |
| VM/baremetal | ✅ | Compatible |

---

## 9. Test Quality

| Category | Count | Quality |
|----------|-------|---------|
| Unit tests | ~40 | Good — test real logic |
| Integration tests | ~20 | Good — test component interaction |
| E2E tests | ~10 | Good — test full pipeline |
| Contract tests | ~5 | Good — test API contracts |
| Dead tests | ~5 | audiobook_ui, legacy_index (test archived modules) |

**Pre-existing failures**: 1 (test_audiobook.py — search keyword fallback)

---

## 10. P0/P1 Issues Found

| ID | Severity | Issue | Fix |
|----|----------|-------|-----|
| P1-1 | P1 | persona_executor disconnected — no CLI entry point | Add `jarvis execute` command |
| P1-2 | P2 | checkpoint.json not per-project | Namespace by project |
| P1-3 | P3 | shell=True in self_test.py | Low risk — test harness only |

---

## 11. What Works For Real

| Capability | Status | Evidence |
|-----------|--------|----------|
| Backend abstraction | ✅ VERIFIED | 32 tests |
| State machine | ✅ VERIFIED | 16 tests |
| Context budget | ✅ VERIFIED | 10 tests |
| E2E pipeline (harness) | ✅ VERIFIED | Corretor 17/17 |
| LLM chat + tool calling | ✅ VERIFIED | Qwen correct |
| Control Plane | ✅ VERIFIED | 73 tests |
| API endpoints | ✅ VERIFIED | 20 endpoints |
| SSE real-time | ✅ VERIFIED | curl verified |
| Gaming toggle | ✅ VERIFIED | Real services |
| Task management | ✅ VERIFIED | Persistent queue |
| Agent state wiring | ✅ VERIFIED | Events → State → SSE |

---

## 12. What Doesn't Work

| Capability | Status | Blocker |
|-----------|--------|---------|
| Autonomous persona execution | ❌ DISCONNECTED | No CLI command |
| Bonsai model | ❌ BLOCKED | Incomplete download |
| SvelteKit browser verification | ❌ UNVERIFIED | No headless test |
| Cross-project checkpoint | ❌ BUG | Single JSON object |
| Nightwatch with real LLM | ⚠️ PARTIAL | Needs LLM running |

---

## 13. Commits This Session

| Commit | What |
|--------|------|
| `e232199` | Add MCP tools knowledge + ChatGPT insights to BUFFY |

---

## 14. Recommendations

### Immediate (P1)
1. **Add `jarvis execute` CLI command** — wire persona_executor into CLI so autonomous pipeline can be triggered
2. **Namespace checkpoint by project** — prevent cross-project state corruption

### Short-term (P2)
3. **Add SvelteKit browser tests** — use Playwright to verify pages render
4. **Verify agent loop traceback feedback** — test that LLM sees real errors on retry
5. **Clean up dead test files** — test_audiobook_ui.py, test_legacy_index.py test archived modules

### Medium-term (P3)
6. **Wire remaining WebUI pages** — Projects, LLM, Voice, Memory, Nightwatch need real data
7. **Add approval UI** — dangerous commands need confirmation in WebUI
8. **Add command palette** — Ctrl+K for quick navigation

---

## 15. Definition of Done

This audit is complete when:
- [x] All files inventoried
- [x] Dead code identified
- [x] Security findings recorded
- [x] Architecture gaps documented
- [x] Control Plane verified
- [x] WebUI audited
- [x] NixOS audited
- [x] Test quality assessed
- [x] P0/P1 issues found
- [x] Recommendations produced
- [ ] P1 fixes implemented (next session)
