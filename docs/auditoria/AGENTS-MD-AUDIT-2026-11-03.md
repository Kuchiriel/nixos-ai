# AGENTS.md audit — 2026-11-03 (what an agent actually gets, and what it misses)

## Question (owner)

"Are the new features (agent roster, the hydration MCPs — memory, rag, recall,
save facts, index — etc.) well explained in AGENTS.md, so agents know **what,
when and how** to use them? Is AGENTS.md overall ok?"

## Method

1. Read both context files: root [`AGENTS.md`](../../AGENTS.md) (injected in every
   opencode session) and [`nixos-ai/AGENTS.md`](../../nixos-ai/AGENTS.md)
   (closest-file wins).
2. Inventory what actually reaches the agent: the `memory.js` plugin injection
   (IDENTITY + SESSION STATE + pinned guards + the tool router), the MCP tool
   descriptions (`mcp_server.py`, 37 tools), the skills, and the `.agents/*.md`
   trigger files.
3. Research: market standard + papers (web + `~/Books/papers`).
4. Link check + line counts on every file touched.

## What was already good

- The **hydration contract is injected, not remembered**: `memory.js` puts
  `## Rehydration (first tool of the session)`, the coordination guards and the
  "which memory tool (pick ONE)" router into every system prompt (and again
  after compaction). Rules last, state first — measured, not guessed.
- `nixos-ai/AGENTS.md` has the right skeleton: prohibitions first, commands,
  env contract, checkpoint/pains, coordination, boundaries, index.
- Every nixos-ai link resolved (14/14) before and after the changes.

## Gaps found (and fixed)

| Gap | Evidence | Fix |
|---|---|---|
| **Stale tool catalog**: `.agents/mcp-catalog.md` said "25 tools", dated 07/10, wrong `home.nix` line, and the hydration family wasn't listed at all — yet it is the file the trigger rules point to ("mcp, rag, vault, github") | `mcp_server.py` has **37** tools (`JARVIS_TOOLS` 28 + `HACKMD_TOOLS` 5 + `MAKE_TOOLS` 4) | rewritten: exact names, what/when/when-not per tool, the router, the other servers |
| **Wrong tool names in a skill** → agents call tools that don't exist | `.opencode/skills/sandbox-qa/SKILL.md:211` had `jarvis_jarvis_observe_file`; the recon/memory rules used bare `recall`/`rag_search`/`remember` (the MCP only exposes `jarvis_*`) | fixed to the real names |
| **The tool-name rule existed only in the plugin** (opencode-only); other harnesses and static readers had no way to learn it | `memory.js:93-99` | one line in both AGENTS.md files + a full section in the catalog |
| **New host automations were invisible to agents** (window restore, provider ping) | new features from 03/11 | 2 short blocks in `nixos-ai/AGENTS.md` |
| **Duplicated checkpoint section** in the root (same 10 lines twice) | root `AGENTS.md` | merged (kept the tool subsection once) |
| **Repo-specific detail sat in the monorepo root** (karaok runbook, MT5 result, night-loop runbook, project map) | root AGENTS.md | detail moved to the owning file (`karaok/AGENTS.md`, `mt5/AGENTS.md`, skill `opencode-coordination`, `docs/architecture/SYSTEM-MAP.md`); the root keeps **pointers** |
| **The pointer target was stale**: `SYSTEM-MAP.md` (the "authoritative inventory") was from 09-15 and did not know mt5/karaok | `docs/architecture/SYSTEM-MAP.md` | appended UPDATE 11/03 with the measured inventory (~80 dirs, own vs reference-clone rule) |

## Deliberately NOT done

- **No new prose in the AGENTS.md files for features the plugin already injects.**
  Duplicating the router in two files buys nothing (arXiv 2602.11988: context
  files don't raise success rate and cost ~20% inference; the same paper says
  *instructions* are followed well, *repository overviews* are not).
- **No trimming of local-model knowledge.** The local tier reads English and
  gets chunked context (`jarvis/core/context_budget.py` splits by budget), so
  size is not the constraint for bonsai — duplication is. The root went
  396 → 313 lines, but nothing was deleted that has no other home: every
  removed block now lives in the file that owns it.

## Files changed

- `AGENTS.md` (root): 396 → 313 lines — repo inventory/night runbook/karaok/
  MT5 detail → pointers to their owners; duplicate checkpoint merged; MCP
  tool-name router added; `SYSTEM-MAP` + `AGENTS-QUEUE` + `karaok/AGENTS.md`
  as real links.
- `nixos-ai/AGENTS.md`: 239 lines — MCP naming rule, host automations
  (restore + provider guard), index rows for the new audits; model-identity
  block collapsed to a pointer (the full 3-tier version stays in the root,
  which is always injected).
- `nixos-ai/.agents/mcp-catalog.md`: rewritten (74 lines) — the what/when/how
  for all 37 tools + the naming trap + the other MCP servers.
- `nixos-ai/home-manager/files/opencode/skills/opencode-coordination/SKILL.md`:
  + the night 2-agent loop runbook (watcher `AGENTS_QUIET=0 0`, blackboard
  mission, delivery, seal protocols, shared-resource rule).
- `.opencode/skills/sandbox-qa/SKILL.md`: tool names fixed.
- `docs/architecture/SYSTEM-MAP.md`: UPDATE 11/03 inventory.

## Validation

- Link check on all touched files: **0 broken**.
- Line counts: root 313 · nixos-ai 239 · catalog 74 · skill 126.
- Full suite (my WIP + the colleague's commits): **1845 passed, 21 skipped,
  5 xpassed, 1 pre-existing failure** (`test_legacy_index.py::test_parity_with_synthetic_index`).

## Still open (not mine)

- `.opencode/agent/suite-runner.md` is pt-BR and marked SUPERSEDED → the
  colleague's lane (CLI/MCP unification).
- The other skills' tool names were not audited line by line (only sandbox-qa,
  which had the two known defects).
- `AGENTS.md` in the other repos (karaok, mt5, guia-renamer) were not
  re-audited against the tool contract — they don't use the jarvis MCP.
