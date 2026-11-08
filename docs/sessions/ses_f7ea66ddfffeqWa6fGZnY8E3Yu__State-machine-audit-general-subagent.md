# State machine audit (@general subagent)

- **sessão:** `ses_f7ea66ddfffeqWa6fGZnY8E3Yu`
- **quando:** 2026-09-08 14:08 (UTC)
- **diretório:** `/home/nixos/projects`
- **mensagens:** 11 (exportadas: 4)
- **origem:** `opencode-stable.db` (opencode 1.18.34, schema v1)

---

## · ?

In /home/nixos/projects/nixos-ai (read-only, NO edits), audit STATE MACHINES in modules/ai/jarvis/src/jarvis/: (1) Session lifecycle (create/use/close/recreate — find session classes, what persists, what leaks: subscriptions, tools, project root, persona, telemetry); (2) Agent run states; (3) Tool call states + cancellation (does cancel reach subprocess?); (4) LLM request states + retry/timeout/breaker semantics; (5) Voice states (wake/listen/transcribe/speak/idle — owners, transitions, stale writes, old transcript overwriting new state); (6) asyncio.create_task without owner/await/cancel (task leaks); (7) EventBus delivery semantics + subscriber death/slow subscriber; (8) datetime.now/time.time usage — wall clock vs monotonic for durations. For EACH: file:line + verdict (OK / SUSPECT:reason / BUG:reason). Max 100 lines. Do NOT fix.

---

## · ?

Auditing session, agent, tool, and voice state machines — read-only sweep in progress.

---

## · ?

Initial patterns mapped — now digging into lifecycle, voice, and bus internals.

---

## · ?

Core flows checked — now verifying subprocess handling, retries, and clock usage.

---

