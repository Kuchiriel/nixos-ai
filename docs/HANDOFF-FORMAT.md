# HANDOFF FORMAT — continuity anchor for the next agent

Referenced by the root `AGENTS.md` (§Handoff). An agent only reads this when
it is about to write a handoff. Everything an LLM reads stays in English.

## Where and how to name

- Live handoff: `nixos-ai/docs/HANDOFF-YYYY-MM-DD.md` (add `-MANHA`/`-NOITE`
  only when two handoffs exist on the same day).
- Older handoffs move to `nixos-ai/docs/archive/` and are never rewritten:
  they are history, not state.
- Exactly one handoff is current: the newest one supersedes the previous.
  Say so in the first lines (`supersedes: HANDOFF-YYYY-MM-DD.md`).
- Vault copy (`~/.local/state/jarvis/vault/`) is optional for the human
  index; the repository file is the source of truth.

## Required fields (all four, or the handoff is not a checkpoint)

1. **Completed** — what actually changed, with commit shas for each logical
   change. Facts only: measured numbers, files touched, tests run with the
   exact command and result.
2. **Remaining** — the exact next task, written so it can be executed
   without re-reading the whole session: file path, the defect or goal, and
   the check that proves it is done.
3. **Blockers** — what needs the owner's authorization or a missing
   credential, and the one command the owner would run.
4. **Context** — the non-inferable facts: HEAD at handoff time, branch,
   running services and their ports, anything that would be re-derived by
   the next agent if omitted.

## Rules

- Never claim a test passed without the command and its result line.
- Never include secret values; name the variable and where its value lives.
- Never rewrite an archived handoff to fix a link.
- Never write the owner's personal nickname.
- A handoff without `Completed` + `Remaining` is a status note, not a
  checkpoint: do not call a session closed after writing one.

## Template

```markdown
# HANDOFF YYYY-MM-DD — <one-line theme>

> supersedes: HANDOFF-YYYY-MM-DD.md
> HEAD: <sha> (<branch>)

## Completed
- <change> — `<sha>` (<test command> -> <result>)

## Remaining
1. <exact next task> — verify with <command>

## Blockers
- <what> needs <authorization/credential>; owner runs: `<command>`

## Context
- Services up: <name:port>, verified with `<probe>`
- Non-obvious facts: <what would otherwise be re-derived>
```
