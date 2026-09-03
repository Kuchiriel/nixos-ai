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
| API (9 endpoints) | — | ✅ VERIFIED | ✅ VERIFIED | — |
| SSE stream | — | ✅ VERIFIED | ✅ VERIFIED | — |
| SvelteKit pages (12) | — | — | — | ❌ UNVERIFIED |

**Legend**: ✅ verified, ⚠️ partially verified, ❌ not verified, — not applicable

---

## 6. KNOWN LIMITATIONS

1. **SvelteKit not verified in browser** — code exists, no headless test
2. **Service start/stop via WebUI** — buttons exist, not tested with real systemctl
3. **Desktop/Sound/Telegram/Voice notifications** — handlers exist, delivery not verified
4. **Agent state never populated** — /api/agent returns empty, pipeline doesn't write to State Store
5. **Nightwatch state** — reads from progress.json which may not exist
6. **Tasks page** — placeholder only, no data
7. **Command audit trail** — JSONL append-only, integrity not tested
8. **State crash recovery** — no test for process killed mid-write

---

## 7. KNOWN BUGS (Fixed 2026-09-03)

| # | Bug | Fix | Evidence |
|---|-----|-----|----------|
| 1 | SSE subscriber leak — every connection adds subscriber, never removed | EventBus.unsubscribe() + unique UUID per SSE connection | Code verified, not runtime-tested with multiple connections |
| 2 | _deliver_web returns True without delivering | Now pushes to SSE queues via _push_to_sse() | Code verified |
| 3 | Duplicate SSE subscribe — old + new name both in code | Removed old subscribe, only UUID-based remains | Code verified |

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
- 134 tests pass (baseline verified)

**What remains UNVERIFIED:**
- SvelteKit browser rendering
- Real notification delivery (desktop/sound/telegram/voice)
- Service start/stop via WebUI with real systemctl
- Agent state population in Control Plane
- Tasks page implementation
