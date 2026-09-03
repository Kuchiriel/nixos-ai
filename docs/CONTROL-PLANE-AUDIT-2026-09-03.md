# Control Plane Audit — 2026-09-03

## AUDIT METHODOLOGY

This audit traces real execution flows, not code structure.
Each claim was verified by running the actual code.

## AUDIT RESULTS

### 1. EventBus → Event History → API → SSE → Frontend

| Link | Status | Evidence |
|------|--------|----------|
| EventBus publish | ✅ VERIFIED | `bus.publish('test', {})` → stats.events_published=1 |
| Event History recording | ✅ VERIFIED | `plane.get_event_history()` returns recorded events |
| API /api/events/history | ✅ VERIFIED | Returns JSON array of events |
| SSE stream | ⚠️ UNVERIFIED | Endpoint exists but not tested with real browser |
| Frontend Activity page | ⚠️ UNVERIFIED | Component exists, SSE connection coded, not tested in browser |

**Gap**: SSE → SvelteKit link unverified in real browser.

### 2. CommandRegistry

| Feature | Status | Evidence |
|---------|--------|----------|
| Registration | ✅ VERIFIED | 17 commands across 7 categories |
| Arg validation | ✅ VERIFIED | Missing required arg → error message |
| Risk enforcement | ✅ VERIFIED | MEDIUM/HIGH require confirmation |
| Audit trail | ✅ VERIFIED | command-audit.jsonl grows with entries |
| Event emission | ✅ VERIFIED | command.completed/failed events published |

### 3. Systemd Adapter

| Feature | Status | Evidence |
|---------|--------|----------|
| Dynamic discovery | ✅ VERIFIED | 14 services found via systemctl |
| Status check | ✅ VERIFIED | Shows active/inactive/enabled/disabled |
| Start/Stop/Restart | ⚠️ UNVERIFIED | Commands registered, not tested with real services |
| Cache | ✅ VERIFIED | Second call returns cached results |

### 4. Notifications

| Channel | Status | Evidence |
|---------|--------|----------|
| Web (SSE) | ⚠️ UNVERIFIED | Handler exists, not tested end-to-end |
| Desktop (notify-send) | ✅ VERIFIED | Falls back correctly when binary missing |
| Sound | ⚠️ UNVERIFIED | play_sound() exists, not tested |
| Waybar | ✅ VERIFIED | set_status() writes JSON file |
| Telegram | ⚠️ UNVERIFIED | Import exists, not tested |
| Voice (TTS) | ⚠️ UNVERIFIED | speak() exists, not tested |

### 5. API Endpoints

| Endpoint | Status | Response Time |
|----------|--------|---------------|
| /api/health | ✅ 200 | <0.1s |
| /api/commands | ✅ 200 | <0.1s |
| /api/services | ✅ 200 | ~1s (systemctl) |
| /api/llm | ✅ 200 | ~0.1s |
| /api/voice | ✅ 200 | <0.1s |
| /api/memory | ✅ 200 | ~0.1s |
| /api/agent | ✅ 200 | <0.1s |
| /api/projects | ✅ 200 | ~0.1s (cached) |
| /api/events/history | ✅ 200 | <0.1s |

### 6. WebUI Pages

| Page | Route | Real Data | Real-time | Actions |
|------|-------|-----------|-----------|---------|
| Dashboard | / | ✅ | ✅ SSE | ❌ |
| Activity | /activity | ✅ | ✅ SSE | ❌ |
| Services | /services | ✅ | ❌ | ✅ start/stop |
| LLM | /llm | ✅ | ❌ | ❌ |
| Voice | /voice | ✅ | ❌ | ❌ |
| Memory | /memory | ✅ | ❌ | ❌ |
| Agent | /agent | ✅ | ❌ | ❌ |
| Nightwatch | /nightwatch | ✅ | ❌ | ❌ |
| Projects | /projects | ✅ | ❌ | ❌ |
| Commands | /commands | ✅ | ❌ | ✅ execute |
| Tasks | /tasks | ❌ placeholder | ❌ | ❌ |
| System | /system | ✅ | ❌ | ❌ |

### 7. Critical Bugs Found & Fixed

| Bug | Impact | Fix |
|-----|--------|-----|
| setup_integration() called doctor_report() at startup | ALL API endpoints blocked (10s+ timeout) | Removed blocking HTTP call |
| /api/projects called WorkspaceDiscovery.discover() | Endpoint blocked (10s+ on nixos-ai) | Fast shallow scan (0.1s) |
| notify() returned True without delivery | False positive on notification success | Check CP delivery before fallback |
| Duplicate subscriptions in plane.py + integration.py | Double event processing | Moved to integration.py only |
| Systemd adapter used manual service list | Wrong/stale service list | Dynamic discovery from systemctl |

## WHAT WAS CLAIMED BUT NOT VERIFIED

1. **SSE real-time in browser** — code exists but no browser test
2. **Service start/stop via WebUI** — button exists, command registered, not tested
3. **Command execution via WebUI** — button exists, not tested
4. **Telegram notification delivery** — import exists, not tested
5. **Voice/TTS via Control Plane** — speak() exists, not tested
6. **Sound notification delivery** — play_sound() exists, not tested

## WHAT IS ACTUALLY MISSING

1. **Browser testing** — no evidence the frontend loads and works
2. **E2E test** — no automated test of the full stack
3. **Error handling in frontend** — no loading/error states tested
4. **SSE reconnection** — coded but not verified
5. **Command Palette (Ctrl+K)** — not implemented yet
6. **Notification center** — not implemented yet
7. **Approval cards** — not implemented yet
8. **Terminal/log viewer** — not implemented yet

## VERDICT

**Implementation completeness: ~60%**

What works:
- Backend API (all 9 endpoints return 200)
- CommandRegistry (validation, audit, events)
- Systemd discovery (14 services found)
- Event History (records events)
- State Store (persists to disk)

What's unverified:
- Frontend actually renders and functions
- SSE real-time in browser
- Service operations via UI
- Notification delivery across channels

What's missing:
- Browser-based testing
- E2E automated tests
- Command Palette
- Notification center
- Approval workflow
