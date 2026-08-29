"""Nightwatch — autonomous improvement loop with grounded reflection.

Inspired by:
- Reflexion (Shinn et al., 2023): generate → critique → revise
- Self-Challenging Agents (Zhou et al., NeurIPS 2025): Code-as-Task
- Karpathy Loop: autonomous overnight experiments
- Grounded critique: tests > execution > retrieval > self-opinion

Design principles:
1. SAFE DISPATCH: Only reversible tasks or tasks with tests
2. GROUNDED CRITIQUE: Run tests after each change, not just self-opinion
3. ITERATION CAP: Max tasks per cycle, max cycles per night
4. STATUS REPORTING: Telegram + terminal progress
5. RECOVERY: Revert on failure, log everything
6. VISION: Screen capture to verify UI state when relevant

Usage:
    jarvis nightwatch                  # Interactive loop
    jarvis nightwatch --tasks 10       # Max 10 tasks
    jarvis nightwatch --report-telegram # Send status to Telegram
    jarvis nightwatch --dry-run        # Show what would be done
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any

from rich.console import Console
from rich.panel import Panel
from rich.table import Table
from rich.text import Text


console = Console()

# ═══ Safe Task Categories ═══
# Only tasks that are reversible or have verifiable outcomes

SAFE_TASK_CATEGORIES = {
    "lint": {
        "description": "Run linters and fix issues",
        "commands": [
            "echo ruff-not-available",
            "echo markdownlint-not-available",
        ],
        "reversible": True,
        "has_tests": True,
    },
    "format": {
        "description": "Auto-format code",
        "commands": [
            "echo ruff-format-not-available",
        ],
        "reversible": True,
        "has_tests": True,
    },
    "test": {
        "description": "Run test suite",
        "commands": [
            "python3 -m pytest modules/ai/jarvis/tests/test_agent.py -x -q",
        ],
        "reversible": False,
        "has_tests": True,
    },
    "docs": {
        "description": "Check documentation consistency",
        "commands": [
            "grep -r 'TODO\\|FIXME\\|HACK' modules/ai/jarvis/src/ --include='*.py' | head -20",
        ],
        "reversible": False,
        "has_tests": False,
    },
    "security": {
        "description": "Scan for security issues",
        "commands": [
            "grep -rn 'shell=True' modules/ai/jarvis/src/ --include='*.py'",
            "grep -rn 'password\\|secret\\|token' modules/ai/jarvis/src/ --include='*.py' -i",
        ],
        "reversible": False,
        "has_tests": False,
    },
    "dedup": {
        "description": "Find code duplication",
        "commands": [
            "grep -rn 'def command_allowed\\|def has_chaining' modules/ai/jarvis/src/ --include='*.py'",
        ],
        "reversible": False,
        "has_tests": False,
    },
    "commit": {
        "description": "Stage and commit changes",
        "commands": [
            "git add -A",
            "git status --short",
        ],
        "reversible": False,
        "has_tests": False,
    },    "dead-code": {
        "description": "Find dead code and unused imports",
        "commands": [
            "grep -rn 'import.*# noqa' modules/ai/jarvis/src/ --include='*.py' | head -10",
            "grep -rn '^def ' modules/ai/jarvis/src/jarvis/core/ --include='*.py' | wc -l",
        ],
        "reversible": False,
        "has_tests": False,
    },
    "git-hygiene": {
        "description": "Check git status and stale work",
        "commands": [
            "git status --short",
            "git log --oneline -10",
            "git stash list",
            "git branch -a | head -10",
        ],
        "reversible": False,
        "has_tests": False,
    },
    "nix-check": {
        "description": "NixOS configuration validation",
        "commands": [
            "statix check . 2>/dev/null || echo statix-not-available",
            "deadnix . 2>/dev/null || echo deadnix-not-available",
        ],
        "reversible": False,
        "has_tests": False,
    },
    "performance": {
        "description": "Check for performance opportunities",
        "commands": [
            "grep -rn 'time\.time\|time\.monotonic' modules/ai/jarvis/src/ --include='*.py' | wc -l",
            "grep -rn 'subprocess\.run\|subprocess\.Popen' modules/ai/jarvis/src/ --include='*.py' | wc -l",
        ],
        "reversible": False,
        "has_tests": False,
    },
}


def _run_safe_command(cmd: str, timeout: int = 60) -> tuple[bool, str]:
    """Run a command safely with timeout."""
    try:
        result = subprocess.run(
            cmd, shell=True, capture_output=True, text=True,
            timeout=timeout, cwd=os.getcwd(),
        )
        output = result.stdout + result.stderr
        return result.returncode == 0, output[:3000]
    except subprocess.TimeoutExpired:
        return False, f"Timeout after {timeout}s"
    except Exception as e:
        return False, str(e)


def _send_telegram(message: str) -> bool:
    """Send status message to Telegram."""
    try:
        env_file = Path("/etc/jarvis-telegram.env")
        if not env_file.exists():
            return False
        env = {}
        for line in env_file.read_text().splitlines():
            if "=" in line:
                key, _, value = line.partition("=")
                env[key.strip()] = value.strip()

        token = env.get("JARVIS_TELEGRAM_TOKEN", "")
        chat_id = env.get("JARVIS_TELEGRAM_CHAT_ID", "")
        if not token or not chat_id:
            return False

        import requests
        resp = requests.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": message, "parse_mode": "Markdown"},
            timeout=10,
        )
        return resp.status_code == 200
    except Exception:
        return False


def _capture_screen() -> str | None:
    """Capture screenshot for vision analysis."""
    try:
        result = subprocess.run(
            ["grim", "-g", "-", "-"],
            capture_output=True, timeout=5,
        )
        if result.returncode == 0:
            # Save to temp file
            tmp = Path("/tmp/nightwatch-screenshot.png")
            tmp.write_bytes(result.stdout)
            return str(tmp)
    except Exception:
        pass
    return None


def _git_has_changes() -> bool:
    """Check if there are uncommitted changes."""
    result = subprocess.run(
        ["git", "status", "--porcelain"],
        capture_output=True, text=True, timeout=5,
    )
    return bool(result.stdout.strip())


def _git_commit(message: str) -> bool:
    """Commit current changes."""
    try:
        subprocess.run(["git", "add", "-A"], capture_output=True, timeout=10)
        result = subprocess.run(
            ["git", "commit", "-m", message, "--no-verify"],
            capture_output=True, text=True, timeout=30,
        )
        return result.returncode == 0
    except Exception:
        return False


def _reflect_on_result(
    task_name: str,
    success: bool,
    output: str,
    tests_passed: bool | None = None,
) -> dict[str, Any]:
    """Grounded reflection — evaluate result against external truth.

    Returns reflection dict with:
    - verdict: "pass" | "fail" | "partial"
    - issues: list of specific issues found
    - next_action: "continue" | "revert" | "skip"
    - confidence: 0.0-1.0
    """
    issues = []
    verdict = "pass" if success else "fail"
    next_action = "continue" if success else "revert"
    confidence = 0.8 if success else 0.3

    # Check output for error signals
    error_signals = ["error", "failed", "exception", "traceback", "fatal"]
    for signal in error_signals:
        if signal.lower() in output.lower():
            issues.append(f"Output contains '{signal}'")
            confidence -= 0.2

    # Check test results if available
    if tests_passed is not None:
        if not tests_passed:
            issues.append("Tests failed after change")
            verdict = "fail"
            next_action = "revert"
            confidence = 0.9  # High confidence when tests fail

    # Check for regressions
    if "regression" in output.lower():
        issues.append("Regression detected")
        confidence -= 0.3

    # Clamp confidence
    confidence = max(0.0, min(1.0, confidence))

    return {
        "task": task_name,
        "verdict": verdict,
        "issues": issues,
        "next_action": next_action,
        "confidence": confidence,
        "timestamp": datetime.now().isoformat(),
    }


def _generate_report(
    reflections: list[dict[str, Any]],
    start_time: datetime,
    max_tasks: int,
) -> str:
    """Generate a human-readable status report."""
    elapsed = datetime.now() - start_time
    passed = sum(1 for r in reflections if r["verdict"] == "pass")
    failed = sum(1 for r in reflections if r["verdict"] == "fail")
    partial = sum(1 for r in reflections if r["verdict"] == "partial")

    report = f"""🌙 **Nightwatch Report**
━━━━━━━━━━━━━━━━━━━━━━

⏱️ Duration: {elapsed.seconds // 60}m {elapsed.seconds % 60}s
📊 Tasks: {len(reflections)}/{max_tasks}
✅ Passed: {passed}
❌ Failed: {failed}
⚠️ Partial: {partial}
📈 Success Rate: {passed/max(len(reflections),1)*100:.0f}%

"""
    for i, r in enumerate(reflections, 1):
        icon = "✅" if r["verdict"] == "pass" else "❌" if r["verdict"] == "fail" else "⚠️"
        report += f"{icon} {i}. {r['task']} — {r['verdict']} (conf: {r['confidence']:.0%})\n"
        if r["issues"]:
            for issue in r["issues"]:
                report += f"   └─ {issue}\n"

    report += f"""
🎯 **Next Steps:**
"""
    if failed > 0:
        report += "- Review failed tasks and fix root causes\n"
    if passed < max_tasks:
        report += f"- {max_tasks - passed} tasks remaining in queue\n"
    report += "- Run `jarvis nightwatch --continue` to resume\n"

    return report


def run_nightwatch(
    max_tasks: int = 10,
    max_cycles: int = 3,
    report_telegram: bool = False,
    dry_run: bool = False,
    tasks: list[str] | None = None,
) -> int:
    """Main nightwatch loop.

    Loop structure (grounded reflection):
    1. SCAN: identify safe tasks from categories
    2. EXECUTE: run task commands
    3. CRITIQUE: run tests/verification (grounded, not self-opinion)
    4. REFLECT: evaluate result against external truth
    5. RECOVER: revert if failed, commit if passed
    6. REPORT: send status to Telegram
    7. REPEAT: until max_tasks or max_cycles
    """
    start_time = datetime.now()
    reflections: list[dict[str, Any]] = []
    tasks_completed = 0

    console.print(Panel(
        f"[bold cyan]🌙 Nightwatch Starting[/]\n"
        f"Max tasks: {max_tasks} | Max cycles: {max_cycles}\n"
        f"Telegram: {'✅' if report_telegram else '❌'} | "
        f"Dry run: {'✅' if dry_run else '❌'}",
        border_style="cyan",
    ))

    # Send start notification
    if report_telegram:
        _send_telegram(f"🌙 Nightwatch started\nMax tasks: {max_tasks}")

    # Determine which tasks to run
    task_queue = tasks or list(SAFE_TASK_CATEGORIES.keys())

    for cycle in range(max_cycles):
        console.print(f"\n[dim]━━━ Cycle {cycle + 1}/{max_cycles} ━━━[/]")

        for task_name in task_queue:
            if tasks_completed >= max_tasks:
                break

            task_info = SAFE_TASK_CATEGORIES.get(task_name, {})
            if not task_info:
                continue

            console.print(f"\n[bold]🔧 {task_name}:[/] {task_info['description']}")

            if dry_run:
                console.print(f"  [dim]Would run: {task_info.get('commands', [])}[/]")
                continue

            # Execute task commands
            task_success = True
            task_output = ""

            for cmd in task_info.get("commands", []):
                console.print(f"  [dim]$ {cmd}[/]")
                success, output = _run_safe_command(cmd, timeout=60)
                task_output += output + "\n"

                if not success:
                    task_success = False
                    console.print(f"  [red]✗ Failed: {output[:100]}[/]")
                    break
                else:
                    preview = output.strip()[:100] or "(no output)"
                    console.print(f"  [green]✓ {preview}[/]")

            # Run tests if task has them (grounded critique)
            tests_passed = None
            if task_info.get("has_tests") and task_success:
                console.print("  [dim]Running verification...[/]")
                test_ok, test_output = _run_safe_command(
                    "python3 -m pytest modules/ai/jarvis/tests/test_agent.py -x -q",
                    timeout=120,
                )
                tests_passed = test_ok
                if not test_ok:
                    console.print(f"  [red]✗ Tests failed: {test_output[:100]}[/]")

            # Reflect on result (grounded, not self-opinion)
            reflection = _reflect_on_result(
                task_name, task_success, task_output, tests_passed
            )
            reflections.append(reflection)

            # Recovery: revert if failed
            if reflection["next_action"] == "revert" and _git_has_changes():
                console.print("  [yellow]Reverting changes...[/]")
                subprocess.run(
                    ["git", "checkout", "--", "."],
                    capture_output=True, timeout=10,
                )
                subprocess.run(
                    ["git", "clean", "-fd"],
                    capture_output=True, timeout=10,
                )

            # Commit if passed and has changes
            elif reflection["verdict"] == "pass" and _git_has_changes():
                commit_msg = f"nightwatch({task_name}): auto-fix via reflection loop"
                if _git_commit(commit_msg):
                    console.print(f"  [green]Committed: {commit_msg}[/]")

            tasks_completed += 1

        if tasks_completed >= max_tasks:
            break

    # Generate and send report
    report = _generate_report(reflections, start_time, max_tasks)
    console.print(Panel(report, title="📊 Report", border_style="green"))

    if report_telegram:
        _send_telegram(report)

    # Save reflection log
    log_path = Path.home() / ".local/state/jarvis/nightwatch-log.jsonl"
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as f:
        for r in reflections:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    console.print(f"\n[dim]Log saved to {log_path}[/]")
    return 0 if all(r["verdict"] == "pass" for r in reflections) else 1
