# BUFFY.md — Agent Execution Rules for nixos-ai

> This file is read by Buffy when working on the nixos-ai project.
> It provides context, rules, and verification requirements.

> Tags: #status/active #type/agent-profile #project/nixos-ai

## ⚠️ CORE RULE: NEVER DECLARE COMPLETION WITHOUT EVIDENCE

**The #1 failure pattern is claiming something works because:**
- An file was created
- A class was defined
- An endpoint exists
- A component renders
- A test passes
- Documentation says it works

**The only valid evidence is:**
- A real execution trace showing the full flow
- Output from the actual system (not mocked)
- A test that exercises the real path
- A browser/device showing the result

## VERIFICATION PROTOCOL (MANDATORY)

Before declaring any task complete, execute this checklist:

### 1. Requirements Extraction
- [ ] Extract all requirements from the prompt
- [ ] Separate functional vs non-functional requirements
- [ ] Identify dependencies between requirements
- [ ] Define acceptance criteria for each requirement
- [ ] Identify which requirements need integration testing

### 2. Baseline
- [ ] Run `git status` — record current state
- [ ] Run existing tests — record pass/fail count
- [ ] Check which services are running
- [ ] Record the commit hash

### 3. Implementation
- [ ] Implement in small, verifiable increments
- [ ] Each increment has a clear acceptance criterion
- [ ] Run tests after each increment
- [ ] Don't skip ahead to the next increment if current one fails

### 4. Integration Verification (THE CRITICAL STEP)

**For each flow, trace the ENTIRE chain:**

```
Producer → Abstraction → Adapter → API → Client → UI
```

**Do NOT stop at any link. Verify EVERY link.**

Example for Control Plane:
```
Component publishes event
  → EventBus receives it
    → Event History records it
      → API serves it
        → SSE streams it
          → Frontend receives it
            → UI displays it
```

**If you can't verify a link, mark it as UNVERIFIED, not WORKING.**

### 5. Adversarial Verification

Try to break your own implementation:
- Invalid arguments
- Missing services
- Unavailable backends
- Duplicate events
- Lost events
- Process crash
- Timeout
- Incorrect persisted state
- Frontend disconnection
- Reconnection
- API errors
- Unconfirmed dangerous commands

### 6. Evidence Collection

For each verified requirement, record:
- What was tested
- How it was tested
- What the output was
- Which file/command produced the output

**"Seems to work" is not evidence.**

### 7. Completion Gate

Before declaring DONE:
- [ ] All requirements checked (100%)
- [ ] Relevant tests executed
- [ ] Integration verified
- [ ] Regressions checked
- [ ] Documentation updated
- [ ] Git diff reviewed
- [ ] Dead code identified
- [ ] Critical TODOs identified
- [ ] Limitations explicitly documented

**If any requirement is incomplete, write: "X/Y implemented" and continue.**

## FAILURE PATTERNS TO AVOID

### Pattern 1: "File exists = functionality works"
```python
# WRONG
def test_api():
    assert os.path.exists("api.py")  # This proves nothing

# RIGHT
def test_api():
    client = TestClient(app)
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
```

### Pattern 2: "Test passes = system works"
```python
# WRONG — test mocks the real system
def test_notification():
    with mock("notify-send"):
        result = notify("test")
        assert result == True  # Proves nothing about real delivery

# RIGHT — test exercises real path
def test_notification():
    result = notify("test")  # Real call
    # Check if notification file was written OR binary was called
```

### Pattern 3: "Component exists = feature complete"
```svelte
<!-- WRONG — component renders but does nothing -->
<script>
  let data = [];
  onMount(async () => {
    data = await fetch("/api/fake").then(r => r.json());
  });
</script>
<div>{data}</div>

<!-- RIGHT — component renders AND handles errors AND shows loading -->
<script>
  let data = $state([]);
  let loading = $state(true);
  let error = $state(null);
  onMount(async () => {
    try {
      data = await fetchRealAPI();
    } catch (e) {
      error = e.message;
    } finally {
      loading = false;
    }
  });
</script>
{#if loading}Loading...{:else if error}Error: {error}{:else}{data}{/if}
```

### Pattern 4: "First link works = chain works"
```python
# WRONG — only tests the first link
def test_flow():
    bus.publish("test", {})  # Link 1: works
    # But never checks links 2-6

# RIGHT — tests the entire chain
def test_flow():
    bus.publish("test", {})  # Link 1
    history = plane.get_event_history()  # Link 2
    assert len(history) > 0
    r = client.get("/api/events/history")  # Link 3
    assert r.status_code == 200
    assert len(r.json()) > 0
    # Link 4-6: SSE + frontend (mark UNVERIFIED if can't test)
```

### Pattern 5: "Returns success = operation succeeded"
```python
# WRONG
def notify(title, body):
    # ... does nothing ...
    return True  # FALSE POSITIVE

# RIGHT
def notify(title, body):
    delivered = False
    try:
        # Try real delivery
        result = send_real_notification(title, body)
        delivered = result.success
    except Exception:
        pass
    if not delivered:
        # Fallback
        delivered = send_fallback(title, body)
    return delivered  # Only True if actually delivered
```

## CONTEXT ENGINEERING

### Before each response (mandatory):
```bash
# 1. RAG search — semantic context
./scripts/jarvis-cli.sh rag-search "keywords from prompt"

# 2. Memory recall — what was done recently
./scripts/jarvis-cli.sh recall "recent changes"

# 3. Lessons — past similar errors
./scripts/jarvis-cli.sh lessons "problem type"
```

### After each change:
```bash
# 1. Remember — what was done
./scripts/jarvis-cli.sh remember "changed X in Y because of Z"

# 2. Update HANDOFF.md if status changed (not every commit)
```

### Every 5 prompts:
```bash
# Check git status
git status --short
```

## JARVIS TOOLS — USE THEM

| Tool | When to Use |
|------|-------------|
| `jarvis recall` | Before assuming something about past work |
| `jarvis rag-search` | Before creating something that might exist |
| `jarvis lessons` | Before making changes that might repeat past errors |
| `jarvis read` | Before editing a file you haven't seen |
| `jarvis shell` | Before claiming a service is running |
| `jarvis health` | Before claiming the system is healthy |

## DEclarative First Rule

**ALL configuration files MUST be created via NixOS modules or home-manager.**

- Use `home.file` for user config files
- Use `xdg.configFile` for XDG config
- Use `pkgs.writeShellScriptBin` for scripts
- Use `systemd.user.services` for user services
- Use `systemd.services` for system services

**DO NOT** create files manually (mkdir, touch, echo > file).

## Project Structure

```
~/projects/                    # Monorepo root
├── nixos-ai/                  # Main project
│   ├── modules/ai/jarvis/     # Python code
│   │   ├── src/jarvis/        # Source
│   │   │   ├── core/          # Business logic
│   │   │   ├── cli/           # CLI
│   │   │   ├── providers/     # LLM, MCP, Telegram, RAG
│   │   │   ├── control_plane/ # Events, State, Commands, Notifications
│   │   │   └── webui/         # FastAPI + SvelteKit
│   │   └── tests/             # Tests (pytest)
│   ├── modules/services/      # NixOS modules
│   ├── home-manager/modules/  # User configs
│   ├── nightwatch/            # Nightwatch harness
│   └── docs/                  # Documentation
```

## Running Services

| Service | Port | Status |
|---------|------|--------|
| llama-server | 8080 | Check with `curl http://127.0.0.1:8080/health` |
| embeddings | 8081 | Check with `curl http://127.0.0.1:8081/health` |
| rerank | 8082 | Check with `curl http://127.0.0.1:8082/health` |
| qdrant | 6333 | Check with `curl http://127.0.0.1:6333/collections` |

## Commands

```bash
# Tests
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q --tb=short

# Build
git add -A && nix build .#jarvis --no-link && nix flake check

# Rebuild system
./rebuild-host.sh

# WebUI
jarvis-webui                    # Backend on port 8090
cd modules/ai/jarvis/src/jarvis/webui/frontend && npm run dev  # Frontend on 5173
```

## Control Plane Architecture

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
API (FastAPI, 9 endpoints)
    ↓
SvelteKit (12 routes, SSE real-time)
```

## Verification Matrix

| Component | Unit Test | Integration | E2E | Browser |
|-----------|-----------|-------------|-----|---------|
| EventBus | ✅ | ✅ | ⚠️ | ❌ |
| StateStore | ✅ | ✅ | ⚠️ | ❌ |
| CommandRegistry | ✅ | ✅ | ⚠️ | ❌ |
| NotificationManager | ✅ | ⚠️ | ❌ | ❌ |
| SystemdAdapter | ✅ | ✅ | ⚠️ | ❌ |
| API endpoints | ❌ | ✅ | ❌ | ❌ |
| SvelteKit pages | ❌ | ❌ | ❌ | ❌ |

**Legend**: ✅ verified, ⚠️ partially verified, ❌ not verified

## Known Limitations

1. **SSE not tested in browser** — code exists but no browser verification
2. **Service operations untested** — start/stop buttons exist but not tested with real services
3. **Telegram/Sound/Voice notifications** — handlers exist but delivery not verified
4. **Frontend error handling** — exists in code but not verified in practice
5. **Command Palette** — not implemented yet
6. **Notification center** — not implemented yet
7. **Approval workflow** — not implemented yet

## Session Log

### 2026-09-03: Control Plane Audit

**What was verified:**
- All 9 API endpoints return 200
- CommandRegistry validates args, enforces risk, audits execution
- SystemdAdapter discovers 14 services dynamically
- Event History records EventBus events
- State Store persists to disk

**What was NOT verified:**
- Frontend renders correctly in browser
- SSE delivers events to frontend in real-time
- Service start/stop works via WebUI
- Notifications deliver across all channels

**Bugs found and fixed:**
- setup_integration() blocked all API (doctor_report at startup)
- /api/projects blocked (WorkspaceDiscovery.scan slow)
- notify() returned True without delivery
- Duplicate subscriptions in plane.py + integration.py
- Systemd adapter used manual list instead of discovery

**Commits:**
- `07f572a` fix: notify() returns False when no channel delivers
- `7176446` fix: P0 Control Plane corrections
- `93e6cc6` feat: JARVIS Control Center
- `ca6b78f` fix: critical API blocking issues

## Session 2026-09-03 — Control Plane Audit + Fix

### What was verified

| Endpoint | Latency | Status |
|----------|---------|--------|
| /api/status | 114ms | ✅ |
| /api/state | 3ms | ✅ |
| /api/commands | 3ms | ✅ |
| /api/services | 150ms | ✅ |
| /api/llm | 138ms | ✅ |
| /api/voice | 4ms | ✅ |
| /api/memory | 5ms | ✅ |
| /api/agent | 5ms | ✅ |
| /api/events/history | 5ms | ✅ |

### Bugs fixed

| # | Bug | Fix |
|---|-----|-----|
| 1 | SvelteKit TS 0 errors, 0 warnings | Verified clean |
| 2 | CommandRegistry arg validation works | voice.speak without text → error |
| 3 | SSE sends state init + heartbeats | Verified real-time stream |
| 4 | Gaming toggle actually works | Restores llama-cpp services |
| 5 | 143/144 tests pass (1 pre-existing voice path) | No regressions |

### What was NOT done (still pending)

- Multi-route SvelteKit pages are skeleton only (no real data binding per-page yet)
- Event history API returns events but SSE doesn't push individual events (only state changes)
- No approval cards or confirmation UI for dangerous commands
- No command palette (Ctrl+K)

### Key lesson

API endpoints were previously blocked by `doctor_report()` hanging on down services at startup. Fixed by removing synchronous health check from `setup_integration()`. Always verify startup isn't blocking.
