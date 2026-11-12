# Autonomous Self-Improvement Loop (metacognitive, AI-first)

> Goal: run unattended for long periods (hours/days), improve the system with evidence, and reduce the need for manual prompts.
> Scope: nixos-ai monorepo (NixOS config + JARVIS + nightwatch + docs/ops). GPU-heavy benchmarks are opt-in and scheduled separately.
> Date: 2026-11-12 (design draft, grounded in current harness + research).

## 0. Diagnosis: why manual prompting is still required

Observed state (evidence in repo): nightwatch provides a strong execution core (task queue, patcher/safe editor, validator, evaluator, checkpoints, loop detection, safety/gates, memory bridge) but is not wired as a safe always-on autonomous service/timer (`docs/operations/SCHEDULE.md`: nightwatch module exists, desligado; no user timer/service). Self-improvement is therefore episodic (human-triggered) rather than continuous.

Gaps that force intervention:
1. **No unattended driver with safe scheduling**: no timer/service that runs nightwatch in bounded windows, respects GPU/LLM contention, publishes progress, and stops on failure budget.
2. **Task discovery is not a closed loop**: improvements are not continuously harvested from `docs/pains/`, failed checks, TODOs, flaky tests, perf regressions, doc drift, and user-observed friction into a prioritized backlog.
3. **Learning is local, not meta-cognitive**: failures can be recorded, but the system rarely updates the improvement procedure itself (prompts, skills, AGENTS guidance, validators, task decomposition rules) based on measured outcomes.
4. **Evaluation/acceptance is uneven**: "improved" is not defined per class of change (build/test/boot/doc/UX), so runs can churn without converging.
5. **Observability/notification gap**: long runs need TTS/Telegram/log summaries and a single status surface; without it, humans must poll.

## 1. Research grounding (what to copy)

- **Darwin Godel Machine / open-ended self-improvement (coding)**: maintain an archive of variants/attempts, select and mutate promising agents/changes, evaluate on real tasks; open-ended exploration avoids getting stuck. (Zhang et al., DGM, ICLR 2026 / arXiv 2505.22954)
- **Hyperagents / DGM-H (arXiv 2603.19461)**: integrate a task agent and a meta agent in one editable program; make the meta-level improvement procedure itself editable (metacognitive self-modification) so the system improves how it improves, not only task outputs.
- **Intrinsic metacognition (Liu & van der Schaar, 2025, arXiv 2506.05109; ICML poster)**: three components — metacognitive knowledge (what I can/can't do, task/strategy models), metacognitive planning (what/how to learn next), metacognitive evaluation (reflect on learning to update future strategy). Extrinsic fixed loops limit adaptability; move toward intrinsic, but keep hard safety gates.
- **Reflexion / verbal reinforcement**: store textual lessons from failures and feed them into subsequent attempts; persist only lessons that pass validation (avoid poisoning).
- **Practical harness lesson (measured in this repo, docs/CRITERIOS-AUTO-EVOLUCAO.md)**: verifier/harness bugs masquerade as model limits; fix instrumentation first, classify failures (a/b/c), require N>=3 for convergence claims.

## 2. Target architecture: Task loop + Meta loop

Two coupled loops with hard safety boundaries:

### A. Task loop (does the work) — mostly exists in nightwatch
1. **Discover** candidate tasks (scripted + LLM, but grounded in evidence).
2. **Select/plan** next task by priority, risk, and expected value; decompose large tasks.
3. **Execute** via patcher + safe editor (LLM never writes directly).
4. **Validate** proportionally (syntax/import/targeted tests/build checks) with honest baselines.
5. **Evaluate** independently (diff/review/gates); reject on regression.
6. **Commit/checkpoint** only on green gates; rollback/abort on failure.
7. **Record** outcome (progress, lessons, pains) and notify.

### B. Meta loop (improves the improver) — the missing metacognitive layer
Runs on a slower cadence (e.g. after N tasks or daily) and may modify *procedure*, not product code:
1. **Observe**: aggregate metrics (success/convergence rate, failure classes, time/cost, repeat pains, reverted patches, false-positive validators).
2. **Diagnose**: classify dominant failure modes (context/targeting, bad decomposition, flaky/irrelevant tests, wrong assumptions, prompt/format issues) with evidence.
3. **Hypothesize** a small procedural change (prompt tweak, task-template, validator rule, discovery heuristic, AGENTS/runbook clarification, skill) — one change at a time.
4. **Experiment**: A/B or before/after on a fixed task slice; require N>=3 where stochastic.
5. **Adopt or revert**: keep only if measured improvement and no regressions; archive result (stepping stone).
6. **Publish**: update runbook/AGENTS/skills and emit a summary (what changed, evidence, remaining gaps).

Key rule: the meta loop edits **procedures and guardrails** conservatively; product changes still pass the task loop gates. Never auto-weaken assertions/tests to "pass".

## 3. Task sources (continuous backlog, evidence-driven)

Feed a single prioritized queue (nightwatch.task_queue / workitems) from:
- `docs/pains/` and recurring tool/command failures (agent-pains).
- Failing or flaky checks (`nix flake check`, targeted tests) and boot/service health signals.
- TODO/FIXME/HACK with context, doc drift (broken refs, stale schedules/maps), and dead code.
- Performance/latency signals and resource contention (only when safe to measure).
- UX friction: unclear CLI output, missing notifications/TTS summaries, rough edges.
- "Should talk to what" gaps: producers without consumers (timers->logs with no alert, state not surfaced to bus/Telegram).

Each task carries: goal, evidence, acceptance check, risk, and max scope. Large/ambiguous work is decomposed before execution.

## 4. Safety, scheduling, and stop conditions (required for unattended runs)

- **Resource discipline**: one heavy job at a time; never contend with active LLM/bench/GPU use. Gate on load/VRAM/service activity (like swap-probe ExecCondition pattern). No GPU benchmarks unless explicitly scheduled.
- **Scope limits**: protected paths, no secrets, no push/deploy, no destructive ops; small diffs; per-run task/time budgets; loop detector and failure budget stop the run.
- **Isolation**: work on task branches/worktrees as harness supports; commit only on green gates; keep main green.
- **No auto-weakening**: failing checks must be fixed at cause or reported; never skip/suppress to pass.
- **Observability**: append-only run log + progress, periodic status to bus/Telegram, optional TTS summary at end-of-run; single "what is running / last result" surface.
- **Human checkpoints**: pause for decisions that change architecture, defaults, security posture, or external behavior; otherwise proceed within declared bounds.

## 5. Minimal viable rollout (incremental)

1. **M0 — Instrument & define "good"**: standard metrics (tasks attempted/completed/blocked, convergence, gate pass rate, failure taxonomy) and a daily summary artifact.
2. **M1 — Unattended dry/wet run (bounded)**: add a declarative user timer/service for a short nightly window with resource guards, max_tasks/time, and notifications; dry-run first, then low-risk categories (docs, lint, small fixes).
3. **M2 — Better discovery**: auto-ingest pains + failing checks into the queue with dedup and prioritization.
4. **M3 — Meta loop**: scheduled reflection job that proposes one procedural tweak at a time, evaluates on fixed slice, adopts/reverts with evidence, and records to lessons/AGENTS/runbook.
5. **M4 — Richer feedback**: TTS/Telegram end-of-run report, UI/kanban surfacing, and convergence dashboard.

## 6. Concrete gaps found in this audit (actionable)

- `flake check --no-build` was broken for `nixosConfigurations.*.system.build.toplevel` by conflicting ` .config/opencode/tui.json` (home.file vs HM opencode module/xdg). Fixed by moving config to `programs.opencode.tui` (keeps theme + thinking visible). Rebuild/switch risk removed.
- Nightwatch autonomous run not operationalized (no timer/service; only CLI/library). Needs declarative, resource-gated, observable scheduling before "run for days".
- Meta-cognitive update path (prompts/skills/validators/AGENTS updated from measured failures) is ad-hoc; needs a governed, evidence-gated procedure.
- `modules/ai/free-providers.json` (nvidia/minimaxai/minimax-m3.1-flash) defines variants mixing effort levels and a `thinking` alias mapping to `high`; verify against actual NIM/opencode variant semantics before relying on them (user-reported "variants don't make sense").

## 7. References (starting points)
- Zhang et al., *Darwin Gödel Machine: Open-Ended Evolution of Self-Improving Agents* (2025/ICLR 2026).
- Zhang et al., *Hyperagents* (arXiv:2603.19461, 2026) — metacognitive self-modification of the improvement procedure.
- Liu & van der Schaar, *Truly Self-Improving Agents Require Intrinsic Metacognitive Learning* (arXiv:2506.05109, 2025).
- Shinn et al., *Reflexion: Language Agents with Verbal Reinforcement Learning* (2023).
- CLMC: code-level metacognition for LLM agents (ICDMW 2025).
- Repo-local: `docs/CRITERIOS-AUTO-EVOLUCAO.md`, `docs/architecture/SELF-IMPROVEMENT-LOOP.mmd`, `docs/architecture/nightwatch-components.md`, `docs/operations/SCHEDULE.md`.
