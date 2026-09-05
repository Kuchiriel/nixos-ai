# CONTROL PLANE AUDIT — Phase 1 & 2

## AUDIT SUMMARY

**Date:** 2026-09-02
**Status:** Architecture audit complete, implementation pending

---

## PHASE 1 — COMPONENT MAP

### Existing Components and Their Communication Patterns

| Component | State? | Publishes Events? | Consumes Events? | Receives Commands? | Current UI |
|-----------|--------|-------------------|-------------------|-------------------|------------|
| **feedback.py** | `/tmp/jarvis-status.json` | ❌ | ❌ | ❌ (direct calls only) | Waybar, notify-send |
| **eventbus.py** | None (in-memory) | ✅ Central bus | ✅ Subscribers | ❌ | None |
| **watchdog.py** | `~/.local/state/jarvis/watchdog/` | ✅ (via EventBus) | ❌ | ❌ (runs as daemon) | TTS, Telegram, Waybar |
| **doctor.py** | None | ✅ `doctor.report` | ❌ | ❌ (CLI only) | CLI output |
| **heal.py** | `heal-restarts.json`, `heal-audit.jsonl` | ✅ `heal.service`, `heal.recovered` | ✅ (doctor_report) | ❌ | notify-send, Telegram |
| **idle.py** | `idle/*.json` heartbeats | ✅ `idle.task` | ❌ | ❌ (timer-driven) | Telegram |
| **triggers.py** | `trigger-states.json` | ✅ `trigger.fired` | ❌ (poll-based) | ❌ | None |
| **voice.py** | None | ✅ `voice.tts` | ❌ | ❌ | Waybar (via feedback) |
| **gaming.py** | `gaming-profile`, `gaming-stopped-services.json` | ❌ (direct notify-send) | ❌ | ❌ (detect + toggle) | notify-send, sound |
| **telegram.py** | Telegram state | ❌ | ❌ (long-polling) | ✅ (chat commands) | Telegram chat |
| **CLI (main.py)** | None | ❌ (direct calls) | ❌ | ✅ (argparse) | Terminal |
| **nightwatch/harness.py** | `progress.json` | ✅ EventBus | ❌ | ❌ | Telegram (optional) |
| **persona.py** | None | ❌ | ❌ | ❌ | None |
| **orchestrator.py** | In-memory | ✅ `orchestrator.*` | ❌ | ❌ | None |
| **agent_loop.py** | In-memory | ❌ | ❌ | ❌ | None |
| **persona_executor.py** | In-memory | ❌ | ❌ | ❌ | None |
| **mcp_server.py** | None | ❌ | ❌ | ✅ (MCP protocol) | None |
| **audiobook_ui.py** | Audiobook state | ✅ `audiobook.*` | ❌ | ✅ (CLI) | Rofi, Waybar |

### State Files Summary

| File | Location | Purpose | Scoped by Project? |
|------|----------|---------|-------------------|
| `jarvis-status.json` | `/tmp/` | Waybar status | ❌ Global |
| `gaming-profile` | `~/.local/state/jarvis/` | Current profile | ❌ Global |
| `gaming-stopped-services.json` | `~/.local/state/jarvis/` | Services to restore | ❌ Global |
| `gaming-transitions.jsonl` | `~/.local/state/jarvis/` | Transition log | ❌ Global |
| `heal-restarts.json` | `~/.local/state/jarvis/` | Cooldown tracking | ❌ Global |
| `heal-restart-counts.json` | `~/.local/state/jarvis/` | Restart limits | ❌ Global |
| `heal-audit.jsonl` | `~/.local/state/jarvis/` | Audit trail | ❌ Global |
| `component_states.json` | `~/.local/state/jarvis/` | Previous health | ❌ Global |
| `trigger-states.json` | `~/.local/state/jarvis/` | Trigger state | ❌ Global |
| `idle/*.json` | `~/.local/state/jarvis/idle/` | Heartbeats | ❌ Global |
| `progress.json` | `~/.local/state/jarvis/nightwatch/` | Nightwatch state | ❌ Global |
| `alerts.jsonl` | `~/.local/state/jarvis/watchdog/` | Alert history | ❌ Global |
| `heal-audit.jsonl` | `~/.local/state/jarvis/watchdog/` | Watchdog audit | ❌ Global |

---

## PHASE 2 — COMMUNICATION MAP

### A — Systems That SHOULD Communicate But Don't

| From | To | What's Missing |
|------|----|----------------|
| **nightwatch** | **EventBus** | Nightwatch harness doesn't publish task events |
| **agent_loop** | **EventBus** | Agent loop has no event publishing at all |
| **persona_executor** | **EventBus** | No events for persona execution lifecycle |
| **watchdog** | **doctor** | Watchdog duplicates doctor's checks instead of subscribing |
| **triggers** | **EventBus** | Triggers poll instead of subscribing to events |
| **gaming** | **EventBus** | Gaming mode changes don't emit events |
| **mcp_server** | **EventBus** | MCP tool calls don't emit events |

### B — Systems Communicating Via Different Paths

| Function | Path 1 | Path 2 | Conflict? |
|----------|--------|--------|-----------|
| **Notifications** | `feedback.notify()` → notify-send | `gaming._notify()` → notify-send | ✅ Duplicated |
| **Sounds** | `feedback.play_sound()` → canberra | `gaming._play_sound()` → canberra | ✅ Duplicated |
| **Status** | `feedback.set_status()` → JSON file | `watchdog.update_waybar()` → JSON file | ✅ Same file, different code |
| **Service health** | `doctor.check_*()` | `watchdog.check_services()` | ✅ Duplicated checks |
| **Service restart** | `heal._restart_service()` | `watchdog.auto_heal()` | ✅ Duplicated logic |
| **Telegram** | `heal._alert()` → telegram | `idle._notify()` → telegram | ✅ Both import directly |

### C — Duplicated State

| State | Source 1 | Source 2 | Risk |
|-------|----------|----------|------|
| Service health | doctor.py | watchdog.py | Different thresholds |
| Service restart | heal.py | watchdog.py | Different cooldowns |
| Profile state | gaming.py | jarvis-gaming-mode.sh | Manual sync needed |

### D — Notification Channels (Current)

```
feedback.py ──→ notify-send (desktop)
             ──→ canberra-gtk-play (sound)
             ──→ /tmp/jarvis-status.json (waybar)

watchdog.py ──→ feedback.py (waybar)
            ──→ voice.speak() (TTS)
            ──→ telegram.send_message()

heal.py ──→ feedback.notify()
        ──→ feedback.play_sound()
        ──→ telegram.send_notification()

gaming.py ──→ _notify() (own notify-send call)
          ──→ _play_sound() (own sound call)

idle.py ──→ telegram.send_notification()

voice.py ──→ feedback.set_status()
         ──→ EventBus (voice.tts)
```

**Problem:** Every component imports feedback.py AND/OR calls notify-send independently. No central routing.

### E — Missing Command System

Currently, all "commands" are:
1. CLI argparse commands (jarvis ask, jarvis doctor, etc.)
2. Telegram chat commands (handled by telegram.py)
3. Direct function calls (no validation, no policy, no audit)

**Missing:**
- No command registry
- No risk classification
- No confirmation flow
- No audit log for commands
- No policy engine
- No way for WebUI to execute commands safely

---

## KEY FINDINGS

### 1. EventBus Exists But Is Underutilized
The EventBus is well-designed (async, DLQ, retry, stats) but only 8 out of 15+ components publish events. No component subscribes to events from other components (except heal subscribing to doctor via direct function call, not EventBus).

### 2. feedback.py Is a Monolith of Direct Calls
`feedback.py` handles:
- Status JSON (waybar)
- Desktop notifications
- Sound playback
- Waybar formatting

Every component imports it directly. No event-driven routing.

### 3. No Unified Command Interface
There's no way for the WebUI to execute commands. CLI, Telegram, and direct calls all bypass each other.

### 4. State Is Scattered Across 13+ JSON Files
No central state store. No state queries. No state subscriptions.

### 5. Duplicated Logic (Critical)
- Service health: doctor + watchdog (different thresholds)
- Service restart: heal + watchdog (different cooldowns)
- Notifications: feedback + gaming + heal + idle (all call notify-send directly)
- Sounds: feedback + gaming (both call canberra directly)

---

## ARCHITECTURE DECISION: Control Plane

Based on this audit, the Control Plane should be:

```
                    JARVIS CORE
                        │
           ┌────────────┼────────────┐
           │            │            │
         EVENTS       STATE       COMMANDS
           │            │            │
           └────────────┼────────────┘
                        │
                  CONTROL PLANE
                        │
          ┌─────────────┼─────────────┐
          │             │             │
        WebUI         CLI         ADAPTERS
          │                         │
      SvelteKit                  Waybar
                                Telegram
                                Desktop
                                Voice
```

### What Changes

1. **EventBus becomes the backbone** — all components publish events through it
2. **State Store** — single source of truth for operational state
3. **Command Registry** — typed commands with validation and policy
4. **Notification Manager** — replaces direct feedback.py calls with event-driven routing
5. **Adapters** — Waybar, Telegram, Desktop, Voice all consume from the same event/state/command layer

### What Doesn't Change

- Individual component logic (doctor, heal, watchdog, etc.)
- NixOS service definitions
- LLM backend
- Agent loop internals
- Nightwatch task execution
