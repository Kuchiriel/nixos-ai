---
name: opencode-coordination
description: "Coordinate with ANOTHER opencode agent on this machine (roster, lane claims, API delivery, wake). Use when you need to talk to a peer agent, split or claim work, avoid file collisions, deliver a note without running the target, cancel someone's turn, or rehydrate the session (first tool = jarvis_rehydrate). Triggers: peer, other agent, multi-agent, coordination, roster, claim, lane, wake, rehydrate, handoff."
license: MIT
---

# Multi-agent coordination (nixos-ai, 2026-11-02)

> This file is read by an LLM: **English only**. Small local models (bonsai)
> do not read pt-BR, and a rule the model cannot read does not exist.

## 0. First tool of the session (harness rule)

`jarvis_rehydrate(task="<what you are about to do>")` — one call
returns: pinned guards + queue top + HANDOFF + memories + lessons + RAG +
roster. This is the rescue: without it the agent re-does a diagnosis that was
already paid for (the RAG was used only to *record*, never to *recover* —
2607.08032: reversible memory beats a summary; 2608.22752: five compactions
drop rule adherence from 53% to 10%).

Tool name: opencode exposes MCP tools as `<server-key>_<tool>`, so the server
key `jarvis` + the tool `rehydrate` = **`jarvis_rehydrate`**. The tools are
registered with canonical names on purpose (no doubled prefix). The tool has a
**loop-breaker**: a second call within 120s returns only a short pointer
(measured: without it the 4B model looped — 293k input tokens).

## 1. Roster = who exists (single source of truth)

`scripts/agent-roster.py` (state in `~/projects/.agents/roster.json`):

```bash
scripts/agent-roster.py claim --name <n> --lane "<repo/area>" --repo <repo> --files "<glob1,glob2>"
scripts/agent-roster.py list          # live/stale/dead + lanes + tasks
# liveness = SESSÃO viva (opencode -s ses_...), não o address da janela:
# o address do Hyprland é efêmero (reabrir a janela = address novo) e
# fazia o roster dar o agente por morto → "não está vivo" no agent-msg.
scripts/agent-roster.py release --name <n>
scripts/agent-roster.py task add --title "..." --owner <n>
```

- **Claim before speaking** (without a claim you are not addressable).
- Two claims with **overlapping files** are refused (explicit boundaries).
  `--force` only with a declared intent. Same lane with disjoint files is OK
  (2 windows, 1 topic).

## 2. Delivery (opencode API — never wtype/focus)

`scripts/agent-msg.sh` delivers **into the target's session**
(`POST /session/:id/message`):

```bash
scripts/agent-msg.sh --to <name> "text"      # REQUEST: the target runs (prompt_async)
scripts/agent-msg.sh --note "text"            # NOTE: enters the session, does NOT run (noReply) — zero tokens
scripts/agent-msg.sh --cancel <id>             # aborts the target's turn (POST /session/:id/abort)
scripts/agent-msg.sh --list                    # dry-run: targets, session, busy?
scripts/agent-msg.sh --pending                 # requests without an answer
```

Rules:
- `--note` is a notification (does not trigger a run). **Never** "leave text in
  the input box": it blocks the human's typing and never enters the queue
  (a real failure).
- Without a roster entry, `--to other` **sends nothing**; broadcast only with
  an explicit `--broadcast` (costs ~15x tokens per multi-agent setup —
  Anthropic 06/2025).
- One line per message; every send is logged in `~/projects/AGENTS-MSG.log`.

## 3. Wake (the watcher wakes the owner of the repo)

`scripts/agents-watcher.sh`: wakes **via the API** (does not steal focus) and
is **lane-aware** — a commit in repo X only wakes the agent whose repo/lane is
X; queue and hooks are global; no roster = legacy global behavior.

## 4. When an error repeats (the stumble)

1. `jarvis_rehydrate(task="<the error>")` — the lesson may already be there.
2. `jarvis_lessons("<error pattern>")` if the lesson does not show up.
3. After fixing it: `jarvis_remember(text=..., category="decision"|"error")` +
   `agent-pains.sh scan-apply` (the scanner captures the error on its own).

## 5. Queue and HANDOFF (shared state)

- `~/projects/AGENTS-QUEUE.md`: the top is the **real** current state (today's
  mission). Update it as a **delta** at the top, never rewrite the history
  (ACE 2510.04618: playbooks evolve by patch; a monolithic rewrite degrades).
- Vault: `HANDOFF-<date>-<slug>.md` (resume pointer) — `jarvis_vault_list`.

## 6. Night 2-agent loop (runbook — owner directive 20/10)

Owner asking for "noite melhorando X" ("night improving X") = invoke the 3
READY pieces (zero recall/rg needed):

1. **Watcher** (systemd, already lives): `systemctl --user status
   agents-watcher.service`. For the whole night:
   `printf '[Service]\nEnvironment="AGENTS_QUIET=0 0"\n' | systemctl --user edit --runtime --stdin agents-watcher.service && systemctl --user restart agents-watcher.service`
   — quotes MANDATORY in the value (without them `QUIET_ATE` becomes empty =
   quiet PERMANENT, bug 20/10); runtime-only, survives reboot, never edit
   `~/.config`. Verify: `tail -3 /tmp/opencode/agents-watcher/states` →
   line `quiet=0h-0h`.
2. **Blackboard**: mission at the TOP of `~/projects/AGENTS-QUEUE.md` (scope,
   lanes who-does-what without file collision, channels, guards, reminder
   "recent papers on the subject before implementing" — directive 20/10) +
   commit — the queue commit is the event that wakes the idle colleague. Only
   `git add AGENTS-QUEUE.md` (the root has dirty submodules).
3. **Direct channel**: `agent-msg.sh --to <name> "text"` (the target runs) ·
   `--note "text"` (enters the session, does NOT run, zero token) ·
   `--cancel <id>`; `--broadcast` only explicitly. Claim first (§1).

Protocols evaluated 20/10 (HB+OC):
- END-OF-ERA SEAL = ★ note + REMOVE the era's prospects from
  `tools/agents-watcher-prospects.txt` (no automatic expiry — a dead prospect
  woke an agent post-seal).
- post-seal wake = check the ★ at the top of the queue BEFORE acting.
- anomaly in a SHARED resource (/tmp, ports, docker, builds) = ask the
  colleague BEFORE investigating (1 question resolves what 4 ghost-hunt calls
  don't).
- the readable wake points to queue-top (real STATE, not yesterday's mission)
  + vault HANDOFF (deep state + memory ids).

Historical method: `nixos-ai/scripts/LOOP-v2.md` / `LOOP-v3.md`.

## 7. Papers behind this (RAG `books`, ~/Books/papers)

2607.08032 (reversible > summary) · 2608.22752 (compaction breaks rules) ·
2609.40118 (query-conditioned) · 2609.28771 (feature-based retrieval) ·
2510.05381 (long context hurts) · 2602.11988 (inflated AGENTS.md = cost) ·
2601.20404 (minimal AGENTS.md = −28% runtime) · 2510.04618 (deltas) ·
A2A v1.0 (deterministic routing, messageId, tasks/cancel).
Synthesis: `nixos-ai/docs/REHYDRATACAO-E-COORDENACAO.md`.
