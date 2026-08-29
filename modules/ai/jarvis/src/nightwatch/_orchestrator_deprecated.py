"""Nightwatch v2 — Orchestrator

Main loop: discover → prioritize → snapshot → branch → fix → gate → commit/revert → learn → report

Inspired by:
- Reflexion (Shinn et al.): generate → critique → revise
- Self-Challenging Agents (NeurIPS 2025): Code-as-Task
- Grounded critique: tests > execution > self-opinion
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nightwatch.categories import CATEGORY_REGISTRY, SEVERITY_ORDER, Task
from nightwatch import safety


LOG_DIR = Path.home() / ".local/state/jarvis/nightwatch"
LOG_DIR.mkdir(parents=True, exist_ok=True)


@dataclass
class TaskResult:
    """Result of executing a single task."""
    task: Task
    status: str  # fixed, reverted, flagged, skipped
    gate_passed: bool
    commit_sha: str | None
    duration_s: float
    output: str = ""


@dataclass
class NightwatchReport:
    """Aggregated report from a nightwatch run."""
    run_id: str
    started_at: float
    results: list[TaskResult] = field(default_factory=list)
    baseline_tests: int = 0

    @property
    def fixed(self) -> int:
        return sum(1 for r in self.results if r.status == "fixed")

    @property
    def reverted(self) -> int:
        return sum(1 for r in self.results if r.status == "reverted")

    @property
    def flagged(self) -> int:
        return sum(1 for r in self.results if r.status == "flagged")

    @property
    def skipped(self) -> int:
        return sum(1 for r in self.results if r.status == "skipped")

    @property
    def success_rate(self) -> float:
        total = len(self.results)
        return self.fixed / total if total > 0 else 0.0


def run_nightwatch(
    max_tasks: int = 10,
    categories: list[str] | None = None,
    report_telegram: bool = False,
    max_minutes: int = 180,
    dry_run: bool = False,
) -> NightwatchReport:
    """Main nightwatch loop.

    Flow:
    1. Discover tasks from all enabled categories
    2. Sort by severity (critical first)
    3. For each task: snapshot → branch → fix → gate → commit/revert
    4. Log results
    5. Detect recurring patterns
    6. Report to Telegram
    """
    run_id = time.strftime("%Y%m%d-%H%M%S")
    started = time.time()

    # Baseline
    baseline = safety._count_passing_tests()

    # Discover tasks
    active_categories = categories or list(CATEGORY_REGISTRY.keys())
    queue: list[Task] = []

    for cat_name in active_categories:
        if cat_name in CATEGORY_REGISTRY:
            try:
                tasks = CATEGORY_REGISTRY[cat_name]()
                queue.extend(tasks)
            except Exception:
                pass

    # Sort by severity
    queue.sort(key=lambda t: SEVERITY_ORDER.get(t.severity, 9))

    report = NightwatchReport(
        run_id=run_id,
        started_at=started,
        baseline_tests=baseline,
    )

    # Execute tasks
    executed = 0
    for task in queue:
        if executed >= max_tasks:
            break
        if (time.time() - started) > max_minutes * 60:
            break

        result = _execute_task(task, dry_run=dry_run)
        report.results.append(result)
        _log_result(result, run_id)

        executed += 1

    # Report
    if report_telegram:
        _send_telegram_report(report)

    # Cleanup
    safety.prune_orphan_branches()

    return report


def _execute_task(task: Task, dry_run: bool = False) -> TaskResult:
    """Execute a single task with full safety pipeline."""
    t0 = time.time()

    if dry_run:
        return TaskResult(
            task=task,
            status="skipped",
            gate_passed=False,
            commit_sha=None,
            duration_s=0,
            output="dry-run",
        )

    # Snapshot
    snapshot = safety.pre_task_snapshot(task.id)

    # Branch
    branch = safety.create_task_branch(task.id, task.category)

    try:
        # Apply fix if auto-fixable
        if task.auto_fixable and task.fix_fn:
            task.fix_fn()
        else:
            # Not auto-fixable — just flag it
            safety.abort_task_branch(branch)
            return TaskResult(
                task=task,
                status="flagged",
                gate_passed=False,
                commit_sha=None,
                duration_s=round(time.time() - t0, 1),
                output="not auto-fixable",
            )

        # Get changed files
        result = subprocess.run(
            ["git", "-C", str(safety.REPO_ROOT), "diff", "--name-only", "main"],
            capture_output=True, text=True, timeout=10,
        )
        changed = result.stdout.strip().splitlines()

        if not changed:
            safety.abort_task_branch(branch)
            return TaskResult(
                task=task,
                status="skipped",
                gate_passed=False,
                commit_sha=None,
                duration_s=round(time.time() - t0, 1),
                output="no changes",
            )

        # Gate
        gate = safety.run_gate(changed)

        # Commit or revert
        outcome = safety.commit_or_revert(
            task.id, task.category, task.description, branch, gate
        )

        return TaskResult(
            task=task,
            status=outcome["status"],
            gate_passed=gate.passed,
            commit_sha=outcome.get("commit_sha"),
            duration_s=outcome.get("duration_s", 0),
            output=gate.output,
        )

    except Exception as e:
        safety.abort_task_branch(branch)
        return TaskResult(
            task=task,
            status="reverted",
            gate_passed=False,
            commit_sha=None,
            duration_s=round(time.time() - t0, 1),
            output=f"error: {e}",
        )


def _log_result(result: TaskResult, run_id: str) -> None:
    """Log result to JSONL file."""
    entry = {
        "run_id": run_id,
        "timestamp": time.time(),
        "task_id": result.task.id,
        "category": result.task.category,
        "severity": result.task.severity,
        "description": result.task.description,
        "status": result.status,
        "gate_passed": result.gate_passed,
        "commit_sha": result.commit_sha,
        "duration_s": result.duration_s,
    }
    log_path = LOG_DIR / "history.jsonl"
    with open(log_path, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


def _send_telegram_report(report: NightwatchReport) -> None:
    """Send summary report to Telegram."""
    elapsed = time.time() - report.started_at
    minutes = int(elapsed // 60)
    seconds = int(elapsed % 60)

    msg = f"""🌙 **Nightwatch Report** — {report.run_id}

⏱️ Duration: {minutes}m {seconds}s
📊 Tasks: {len(report.results)}
✅ Fixed: {report.fixed}
❌ Reverted: {report.reverted}
⚠️ Flagged: {report.flagged}
⏭️ Skipped: {report.skipped}
📈 Success Rate: {report.success_rate:.0%}

"""
    for i, r in enumerate(report.results, 1):
        icon = {"fixed": "✅", "reverted": "❌", "flagged": "⚠️", "skipped": "⏭️"}.get(r.status, "?")
        msg += f"{icon} {i}. [{r.task.severity}] {r.task.category}: {r.task.description[:60]}\n"

    msg += f"\n🧪 Tests baseline: {report.baseline_tests}"

    # Send via Telegram
    try:
        env_file = Path("/etc/jarvis-telegram.env")
        if env_file.exists():
            env = {}
            for line in env_file.read_text().splitlines():
                if "=" in line:
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()

            token = env.get("JARVIS_TELEGRAM_TOKEN", "")
            chat_id = env.get("JARVIS_TELEGRAM_CHAT_ID", "")

            if token and chat_id:
                import requests
                requests.post(
                    f"https://api.telegram.org/bot{token}/sendMessage",
                    json={"chat_id": chat_id, "text": msg, "parse_mode": "Markdown"},
                    timeout=10,
                )
    except Exception:
        pass
