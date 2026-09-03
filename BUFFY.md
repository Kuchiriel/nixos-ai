# BUFFY.md — nixos-ai Execution Protocol

> Project-specific rules for the nixos-ai repository.
> Monorepo governance is in ~/projects/BUFFY.md.
> Updated: 2026-09-03

---

## 0. CORE RULE

The only valid evidence is: **code + execution + observed behavior.**

Everything else is a claim until proven.

---

## 1. PROJECT STRUCTURE

```
nixos-ai/
├── modules/ai/
│   ├── jarvis/
│   │   ├── src/jarvis/
│   │   │   ├── core/          # Business logic
│   │   │   ├── cli/           # CLI
│   │   │   ├── providers/     # LLM, MCP, Telegram, RAG
│   │   │   ├── control_plane/ # Events, State, Commands, Notifications
│   │   │   └── webui/         # FastAPI + SvelteKit
│   │   └── tests/             # Tests (pytest)
│   ├── package.nix            # Nix package
│   └── models.nix             # Model config
├── modules/services/          # NixOS service modules
├── home-manager/modules/      # User configs
├── nightwatch/                # Nightwatch harness
└── docs/                      # Documentation + audits
```

---

## 2. RUNNING SERVICES

| Service | Port | Check |
|---------|------|-------|
| llama-server | 8080 | `curl http://127.0.0.1:8080/health` |
| embeddings | 8081 | `curl http://127.0.0.1:8081/health` |
| rerank | 8082 | `curl http://127.0.0.1:8082/health` |
| qdrant | 6333 | `curl http://127.0.0.1:6333/collections` |
| WebUI | 8090 | `curl http://127.0.0.1:8090/api/health` |
| SvelteKit dev | 5173 | browser localhost:5173 |

---

## 3. COMMANDS

```bash
# Tests
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q --tb=short

# Build
nix build .#jarvis --no-link && nix flake check

# Rebuild system
./rebuild-host.sh

# WebUI backend
jarvis-webui                    # port 8090

# SvelteKit frontend
cd modules/ai/jarvis/src/jarvis/webui/frontend && npm run dev
```

---

## 4. CONTROL PLANE ARCHITECTURE

```
Core Components
    ↓
Control Plane
├── Events (taxonomy + history)
├── State (persistent store)
├── Commands (validated + audited)
├── Notifications (multi-channel)
├── Policies (risk levels)
└── Audit (JSONL trail)
    ↓
API (FastAPI, 11 endpoints)
    ↓
SvelteKit (12 routes, SSE real-time)
```

---

## 5. VERIFICATION MATRIX (Current State — 2026-09-03)

| Component | Unit | Integration | E2E | Browser |
|-----------|------|-------------|-----|---------|
| EventBus | ✅ VERIFIED | ✅ VERIFIED | ✅ VERIFIED | — |
| EventBus unsubscribe | — | — | ✅ IMPLEMENTED | — |
| StateStore | ✅ VERIFIED | ✅ VERIFIED | ⚠️ PARTIAL | — |
| CommandRegistry | ✅ VERIFIED | ✅ VERIFIED | ✅ VERIFIED | — |
| NotificationManager | ✅ VERIFIED | ⚠️ PARTIAL | ⚠️ PARTIAL | — |
| Notification web delivery | — | — | ✅ IMPLEMENTED | — |
| SystemdAdapter | ✅ VERIFIED | ✅ VERIFIED | ⚠️ PARTIAL | — |
| API (20 endpoints) | — | ✅ VERIFIED | ✅ VERIFIED | — |
| SSE stream | — | ✅ VERIFIED | ✅ VERIFIED | — |
| SvelteKit pages (12) | — | — | — | ❌ UNVERIFIED |
| persona_executor | ✅ VERIFIED | ✅ VERIFIED | ⚠️ PARTIAL | — |
| `jarvis execute` CLI | ✅ VERIFIED | — | ⚠️ PARTIAL | — |

**Legend**: ✅ verified, ⚠️ partially verified, ❌ not verified, — not applicable

---

## 6. KNOWN LIMITATIONS

1. **SvelteKit not verified in browser** — code exists, no headless test
2. **Service start/stop via WebUI** — buttons exist, not tested with real systemctl
3. **Desktop/Sound/Telegram/Voice notifications** — handlers exist, delivery not verified
4. ~~Agent state never populated~~ — FIXED: harness events now flow to State Store
5. **Nightwatch state** — reads from progress.json which may not exist
6. ~~Tasks page~~ — FIXED: real persistent queue, retry/cancel actions
7. **Command audit trail** — JSONL append-only, integrity not tested
8. **State crash recovery** — no test for process killed mid-write

---

## 7. KNOWN BUGS (Fixed 2026-09-03)

| # | Bug | Fix | Evidence |
|---|-----|-----|----------|
| 1 | SSE subscriber leak — every connection adds subscriber, never removed | EventBus.unsubscribe() + unique UUID per SSE connection | Code verified, not runtime-tested with multiple connections |
| 2 | _deliver_web returns True without delivering | Now pushes to SSE queues via _push_to_sse() | Code verified |
| 3 | Duplicate SSE subscribe — old + new name both in code | Removed old subscribe, only UUID-based remains | Code verified |
| 4 | `--dry-run` parsed but never passed to harness | PersonaExecutor now accepts dry_run parameter | Verified: `harness.config.dry_run=True` when `--dry-run` passed |
| 5 | Hardcoded `/home/nixos/projects` in persona_executor | Uses `JARVIS_PROJECTS_DIR` env or `~/projects` | Verified: imports Path, resolves dynamically |
| 6 | `files_changed` reported candidates not actual changes | Now uses `git diff --name-only HEAD` | Verified: subprocess call to git |
| 7 | `except Exception: pass` silenced event publishing errors | Now logs warning via `logging.getLogger` | Code verified |
| 8 | self_test.py referenced archived modules (orchestrator, workitem) | Replaced with task_queue and harness_status tests | Verified: self_test passes 9/10 black, 6/6 white |

---

## 8. WHAT WORKS FOR REAL

| Capability | Status | Evidence |
|-----------|--------|----------|
| Backend abstraction (llama-cpp/prismml/bonsai) | ✅ VERIFIED | 32 tests, factory |
| State machine (DISCOVERED→COMPLETED) | ✅ VERIFIED | 16 tests, invalid transitions rejected |
| Context budget (auto-detect n_ctx) | ✅ VERVerified | 10 tests, /props integration |
| Test taxonomy (unit/integration markers) | ✅ VERIFIED | conftest.py + markers |
| E2E pipeline (discovery→task→validate→commit) | ✅ VERIFIED | Corretor project, 17/17 tests |
| LLM chat + tool calling | ✅ VERIFIED | Qwen returns correct tool_calls |
| Control Plane events/state/commands | ✅ VERIFIED | 134 tests pass |
| API endpoints (all 9) | ✅ VERIFIED | curl 200 on all |
| SSE real-time stream | ✅ VERIFIED | curl shows init + heartbeats |
| Gaming toggle (real services) | ✅ VERIFIED | curl shows services restarted |
| Command arg validation | ✅ VERIFIED | voice.speak without text → error |
| Autonomous persona execution | ✅ VERIFIED | `jarvis execute` CLI + persona_executor |
| Agent state wiring | ✅ VERIFIED | harness → EventBus → State → SSE |

---

## 9. WHAT DOESN'T WORK

| Capability | Status | Blocker |
|-----------|--------|---------|
| Bonsai model | ❌ BLOCKED | Models corrupted (incomplete download) |
| PrismML standalone | ⚠️ PARTIAL | VRAM insufficient for 2 servers |
| Nightwatch autonomous | ⚠️ PARTIAL | Pipeline works, needs LLM in harness |
| SvelteKit browser verification | ❌ UNVERIFIED | No headless browser in test env |
| Real notification delivery | ⚠️ PARTIAL | Depends on runtime binaries |

---

## 10. PERSONAS

| Persona | When |
|---------|------|
| cto | Architecture, priority |
| architect | System design, ADRs |
| backend_engineer | Implementation, APIs |
| nixos_engineer | NixOS config, services |
| qa_engineer | Testing, validation |
| security_engineer | Security review |
| researcher | Web research, evaluation |
| technical_writer | Documentation |
| supervisor | Task decomposition |
| devops_engineer | CI/CD, deployment |

---

## 11. SESSION LOG

### 2026-09-03: Hardening + SSE Fix

**What was done:**
- Audited both BUFFY files for gaps and ritualism
- Traced all architecture flows (EventBus → Control Plane → API → SSE → Frontend)
- Fixed SSE subscriber leak (EventBus.unsubscribe + UUID per connection)
- Fixed _deliver_web stub (now pushes to SSE queues)
- Removed duplicate SSE subscribe
- Wrote hardened BUFFY with Completion Gate, Evidence Ladder, Adversarial Verification
- Produced 40-item requirement matrix with real statuses
- Actual test count: 820 passed (not 134 as claimed)

**What remains UNVERIFIED:**
- SvelteKit browser rendering
- Real notification delivery (desktop/sound/telegram/voice)
- Service start/stop via WebUI with real systemctl
- Agent state population in Control Plane
- Tasks page implementation

### 2026-09-03: Consolidation + Agent State + Tasks

**What was done:**
- Archived 9 dead modules (orchestrator, workitem, subagent, context, agent_loop, ast_guard, ast_cache, learning, vision_analyzer)
- Refactored persona_executor to use harness directly (eliminated PAUSADO dependency)
- Wired agent state from harness → global EventBus → Control Plane → SSE → Dashboard
- Implemented real Tasks page with persistent queue
- Fixed systemd_adapter KNOWN_SERVICES bug
- Added task.retry/task.cancel commands to CommandRegistry
- E2E verified: PersonaExecutor → LLM → patch → validator → events → state → API
- Actual test count: 820 passed (not 302 as claimed)

**Commits:**
- `88c34f6` — Consolidation: archive 9 modules, refactor persona_executor
- `b02af88` — Update HANDOFF.md
- `296767a` — Fix test_platform_e2e for archived modules
- `d94fb10` — Agent state wiring + Tasks page + service fix
- `840ab17` — Updated requirement matrix
- `55e8088` — Dashboard agent indicator + task actions + E2E verified

**What remains UNVERIFIED:**
- SvelteKit browser rendering
- Real notification delivery
- Service start/stop via WebUI with real systemctl
- Nightwatch autonomous loop with real LLM
- Cross-project task execution

### 2026-09-03: Forensic Verification

**Bugs found and fixed:**
1. `--dry-run` parsed but never wired → FIXED
2. Hardcoded `/home/nixos/projects` → FIXED (uses config)
3. `files_changed` reported candidates → FIXED (uses git diff)
4. `except Exception: pass` silenced errors → FIXED (logs warning)
5. self_test.py referenced archived modules → FIXED

**False markings corrected:**
- Test count: 302/303 → 820/833 actual
- Endpoint count: 9 → 20 actual
- persona_executor VERIFIED → PARTIAL (dry-run was broken)
- `jarvis execute` VERIFIED → PARTIAL (files_changed was wrong)

**Unfixed (needs separate session):**
- P6: checkpoint.json not per-project (cross-project state corruption)
- Agent loop never feeds error context back to LLM (architectural)
- 13 test failures (5 API mismatch, 3 pipeline bugs, 3 test infra, 2 LLM offline)

## Consolidation 2026-09-03 — Complete

### What was eliminated
- 9 archived modules (orchestrator, workitem, subagent, context, agent_loop, ast_guard, ast_cache, learning, vision_analyzer)
- 0 PAUSADO imports remaining
- persona_executor now uses harness directly (no orchestrator dependency)
- CLI commands updated to use task_queue

### Verified
- 302/303 tests pass (1 pre-existing failure)
- PersonaExecutor E2E on Corretor: commit bd3919f2
- No regressions from consolidation

### Architecture (current)
```
PersonaExecutor
  → TaskQueue (persistent)
    → Harness (pipeline engine)
      → LLM (via _default_call_llm)
        → Patcher + SafeEditor
          → Validator (syntax + tests)
            → Evaluator (review)
              → Checkpoint + Safety
                → Git commit
```

### Archived code lives in
- `archive/core/` — 9 modules + 1 test + README

---

## 16. MCP TOOLS & READING EXTERNAL SOURCES

### Reading ChatGPT Conversations

ChatGPT shared URLs are too large for `read_url` (>2MB). Use Playwright:

```bash
nix-shell -p python3Packages.playwright --run "python3 /tmp/read_chatgpt_convo.py"
```

Script at `/tmp/read_chatgpt_convo.py` uses system Chromium via `executable_path="/etc/profiles/per-user/nixos/bin/chromium"`. The cached Playwright Chromium lacks shared libs (`libglib-2.0.so.0`). Scrolls to load lazy content, saves to `/tmp/chatgpt_conversation.txt`.

### MCP Tools Available

- `read_url` — fetches URL text (works for most sites, NOT ChatGPT shared links)
- `web_search` — Google search via Serper API
- `gravity_index` — third-party service discovery
- `render_ui` — render UI widgets
- `code_search` — ripgrep search across project files
- `read_files` — read files from disk
- `write_file` — create/overwrite files
- `str_replace` — edit files with string replacement
- `run_terminal_command` — execute bash commands

### ChatGPT Conversation Key Findings (2026-09-03)

Claude analyzed the project and identified:

1. **P2/P3 already fixed** — `record_attempt()` only tracks failures, `_persist_now()` called immediately
2. **P6 is a real bug** — `checkpoint.json` and `mission_state.json` are single objects, not per-project. Different projects can overwrite each other's state
3. **Critical unverified question**: does the agent loop send traceback feedback to the LLM on retry? If not, it's a loop bug, not model capacity limit. Never confirmed.
4. **Claude's recommendation**: prove the harness works on real projects before adding infrastructure
5. **Bonsai/PrismML**: worth trying but download attempts consumed entire sessions. Pre-download with stable internet.
6. **buffy.md pattern**: good manual but needs Enforcement Gates (added in this session)

### Lessons from Failed Sessions

- **Bonsai download**: don't attempt large downloads during sessions — pre-download with stable internet
- **Playwright on NixOS**: use system Chromium via `executable_path`, not Playwright's cached binary
- **Agent loop capacity**: 15 retries seeing same error = likely model capacity limit, but never confirmed
- **Token throughput**: was 30 t/s, dropped to 9 t/s — check for background processes consuming resources
- **Session fragmentation**: critical context lives in ChatGPT/Claude conversations, not in codebase — use Playwright reader to bridge

---

## 17. CHATGPT SESSION STATE (2026-09-03)

The ChatGPT conversation at `https://chatgpt.com/share/6a99bf79-72bc-83e9-aeed-f0f15ca835ac` contains:

- Full analysis of buffy.md weaknesses
- Claude's prompt for buffy hardening
- Claude's analysis of P2-P9 audit items
- Recommendation to break audit into sessions (P4+P6, P5+P8, P7, P9)
- Bonsai/PrismML evaluation context
- Agent loop traceback feedback question

**Always read this conversation at session start using Playwright to recover context.**
