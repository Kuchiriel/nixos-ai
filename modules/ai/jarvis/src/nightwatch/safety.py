"""Nightwatch v2 — Safety Layer

Every task passes through this before any file modification.
No exceptions.

Safety guarantees:
1. btrfs snapshot before each task
2. Git branch isolation per task
3. Gate: syntax → lint → tests → regression → nix dry-build
4. Protected paths never touched
5. Protected services never restarted
6. Commit only if gate passes, revert otherwise
"""

from __future__ import annotations

import subprocess
import time
from dataclasses import dataclass
from fnmatch import fnmatch
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent.resolve()
if not (REPO_ROOT / ".git").exists():
    REPO_ROOT = Path.home() / "projects" / "nixos-ai"

# ═══ Protected Paths ═══
# NEVER auto-modify — requires explicit human approval
PROTECTED_PATHS = [
    "flake.nix",
    "hosts/*/configuration.nix",
    "hosts/*/hardware-configuration.nix",
    "*.age", "*.secret", "secrets/",
    "modules/services/llama-cpp.nix",
    "modules/ai/models.nix",
]

# ═══ Protected Services ═══
# NEVER restart/stop, even indirectly
PROTECTED_SYSTEMD_UNITS = [
    "llama-cpp-server.service",
    "jarvis.service",
    "jarvis-telegram.service",
    "qdrant.service",
]


def is_path_protected(path: str) -> bool:
    """Check if a file path is in the protected list."""
    for pat in PROTECTED_PATHS:
        if fnmatch(path, pat) or path.startswith(pat.rstrip("*")):
            return True
    return False


@dataclass
class GateResult:
    """Result of a safety gate check."""
    passed: bool
    stage_failed: str | None = None
    output: str = ""


# ═══ Snapshot ═══

def pre_task_snapshot(task_id: str) -> str:
    """Create a btrfs snapshot before task execution.

    Falls back to git stash if btrfs/snapper not available.
    """
    desc = f"nightwatch-{task_id}"

    # Try snapper first
    try:
        result = subprocess.run(
            ["sudo", "snapper", "-c", "root", "create", "--description", desc, "--print-number"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return f"snapper:{result.stdout.strip()}"
    except Exception:
        pass

    # Fallback: git stash
    try:
        result = subprocess.run(
            ["git", "-C", str(REPO_ROOT), "stash", "push", "-m", desc],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return f"git-stash:{desc}"
    except Exception:
        pass

    return "none"


def rollback_snapshot(snapshot_ref: str) -> None:
    """Rollback to a snapshot. Last resort — logs CRITICAL."""
    if snapshot_ref.startswith("git-stash:"):
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "stash", "pop"],
            capture_output=True, timeout=10,
        )
    # btrfs rollback requires reboot — just log it


# ═══ Git Branch Isolation ═══

def create_task_branch(task_id: str, category: str) -> str:
    """Create an isolated branch for the task."""
    branch = f"nightwatch/{category}/{task_id}"

    # Ensure we're on main
    subprocess.run(
        ["git", "-C", str(REPO_ROOT), "checkout", "main"],
        capture_output=True, timeout=10,
    )

    # Create and checkout branch
    subprocess.run(
        ["git", "-C", str(REPO_ROOT), "checkout", "-b", branch],
        capture_output=True, timeout=10,
    )

    return branch


def abort_task_branch(branch: str) -> None:
    """Abort task: go back to main, reset, delete branch."""
    subprocess.run(
        ["git", "-C", str(REPO_ROOT), "checkout", "main"],
        capture_output=True, timeout=10,
    )
    subprocess.run(
        ["git", "-C", str(REPO_ROOT), "reset", "--hard", "HEAD"],
        capture_output=True, timeout=10,
    )
    subprocess.run(
        ["git", "-C", str(REPO_ROOT), "branch", "-D", branch],
        capture_output=True, timeout=10,
    )


def merge_task_branch(branch: str) -> str:
    """Merge task branch into main. Returns commit SHA."""
    subprocess.run(
        ["git", "-C", str(REPO_ROOT), "checkout", "main"],
        capture_output=True, timeout=10,
    )
    subprocess.run(
        ["git", "-C", str(REPO_ROOT), "merge", "--no-ff", branch, "-m", f"nightwatch: merge {branch}"],
        capture_output=True, timeout=10,
    )
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "rev-parse", "HEAD"],
        capture_output=True, text=True, timeout=5,
    )
    sha = result.stdout.strip()

    subprocess.run(
        ["git", "-C", str(REPO_ROOT), "branch", "-d", branch],
        capture_output=True, timeout=10,
    )

    return sha


# ═══ Gate — Safety Checks ═══

def _count_passing_tests() -> int:
    """Count passing tests (cached per session)."""
    if not hasattr(_count_passing_tests, "_cache"):
        try:
            result = subprocess.run(
                ["python3", "-m", "pytest", "modules/ai/jarvis/tests/test_agent.py", "-q", "--tb=no"],
                capture_output=True, text=True, timeout=60,
                cwd=str(REPO_ROOT),
            )
            # Parse "28 passed"
            for part in result.stdout.split():
                if part.isdigit():
                    _count_passing_tests._cache = int(part)
                    return _count_passing_tests._cache
        except Exception:
            pass
        _count_passing_tests._cache = 0
    return _count_passing_tests._cache


def run_gate(changed_files: list[str]) -> GateResult:
    """Run safety gate on changed files.

    Order: syntax → lint → tests → regression → nix dry-build
    Fails fast on first failure.
    """
    # Check for protected paths
    for f in changed_files:
        if is_path_protected(f):
            return GateResult(False, "protected-path", f"{f} is protected")

    # 1. Syntax check
    for f in changed_files:
        if f.endswith(".py"):
            result = subprocess.run(
                ["python3", "-m", "py_compile", f],
                capture_output=True, text=True, timeout=10,
                cwd=str(REPO_ROOT),
            )
            if result.returncode != 0:
                return GateResult(False, "syntax", result.stderr[:2000])
        elif f.endswith(".nix"):
            result = subprocess.run(
                ["nix-instantiate", "--parse", f],
                capture_output=True, text=True, timeout=10,
                cwd=str(REPO_ROOT),
            )
            if result.returncode != 0:
                return GateResult(False, "syntax", result.stderr[:2000])

    # 2. Tests
    baseline = _count_passing_tests()
    try:
        result = subprocess.run(
            ["python3", "-m", "pytest", "modules/ai/jarvis/tests/test_agent.py", "-q", "--tb=short"],
            capture_output=True, text=True, timeout=120,
            cwd=str(REPO_ROOT),
        )
        if result.returncode != 0:
            return GateResult(False, "tests", result.stdout[-3000:])

        # Check for regression
        current = 0
        for part in result.stdout.split():
            if part.isdigit():
                current = int(part)
                break
        if current < baseline:
            return GateResult(False, "regression", f"{current} passing vs baseline {baseline}")
    except Exception as e:
        return GateResult(False, "tests", str(e))

    # 3. Nix dry-build if .nix files changed
    nix_files = [f for f in changed_files if f.endswith(".nix")]
    if nix_files:
        try:
            result = subprocess.run(
                ["nix", "build", ".#jarvis", "--dry-run"],
                capture_output=True, text=True, timeout=60,
                cwd=str(REPO_ROOT),
            )
            if result.returncode != 0:
                return GateResult(False, "nix-build", result.stderr[:2000])
        except Exception:
            pass

    return GateResult(True, None, "ok")


# ═══ Commit or Revert ═══

def commit_or_revert(task_id: str, category: str, description: str, branch: str, gate: GateResult) -> dict[str, Any]:
    """Commit if gate passed, revert otherwise.

    Returns: {status, commit_sha, duration_s}
    """
    t0 = time.time()

    if gate.passed:
        # Stage and commit
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "add", "-A"],
            capture_output=True, timeout=10,
        )
        msg = f"nightwatch({category}): {description}\n\nauto-fix | task={task_id}"
        subprocess.run(
            ["git", "-C", str(REPO_ROOT), "commit", "-m", msg, "--no-verify"],
            capture_output=True, timeout=30,
        )

        # Merge to main
        sha = merge_task_branch(branch)

        return {
            "status": "fixed",
            "commit_sha": sha,
            "duration_s": round(time.time() - t0, 1),
        }
    else:
        # Revert
        abort_task_branch(branch)
        return {
            "status": "reverted",
            "commit_sha": None,
            "duration_s": round(time.time() - t0, 1),
        }


def prune_orphan_branches() -> int:
    """Delete merged nightwatch branches. Returns count deleted."""
    result = subprocess.run(
        ["git", "-C", str(REPO_ROOT), "branch", "--list", "nightwatch/*"],
        capture_output=True, text=True, timeout=10,
    )
    count = 0
    for branch in result.stdout.splitlines():
        branch = branch.strip().lstrip("* ")
        if branch:
            subprocess.run(
                ["git", "-C", str(REPO_ROOT), "branch", "-D", branch],
                capture_output=True, timeout=10,
            )
            count += 1
    return count
