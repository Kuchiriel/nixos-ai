"""Nightwatch v2 — Category Registry

Each category provides:
- discover() → list of Task objects
- Optional: autofix(task) → applies fix

Categories are sorted by severity before execution.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable
from pathlib import Path
import subprocess
import re

REPO_ROOT = Path(__file__).parent.parent.parent.parent.parent.resolve()
if not (REPO_ROOT / ".git").exists():
    REPO_ROOT = Path.home() / "projects" / "nixos-ai"


@dataclass
class Task:
    """A single nightwatch task."""
    id: str
    category: str
    severity: str  # critical, high, medium, low, info
    description: str
    target_path: str
    auto_fixable: bool
    fix_fn: Callable | None = None


# ═══ Category Implementations ═══

def discover_test() -> list[Task]:
    """Run tests and report failures."""
    try:
        result = subprocess.run(
            ["python3", "-m", "pytest", "modules/ai/jarvis/tests/test_agent.py", "-q", "--tb=line"],
            capture_output=True, text=True, timeout=120,
            cwd=str(REPO_ROOT),
        )
        if result.returncode != 0:
            return [Task(
                id=f"test-{int(__import__('time').time())}",
                category="test",
                severity="critical",
                description=f"Tests failing: {result.stdout[-200:]}",
                target_path="modules/ai/jarvis/tests/",
                auto_fixable=False,
            )]
    except Exception:
        pass
    return []


def discover_docs() -> list[Task]:
    """Find TODO/FIXME/HACK markers."""
    tasks = []
    try:
        result = subprocess.run(
            ["grep", "-rn", "TODO\\|FIXME\\|HACK", "modules/ai/jarvis/src/", "--include=*.py"],
            capture_output=True, text=True, timeout=10,
            cwd=str(REPO_ROOT),
        )
        for line in result.stdout.splitlines()[:5]:
            parts = line.split(":", 2)
            if len(parts) >= 2:
                tasks.append(Task(
                    id=f"doc-{hash(line) % 100000}",
                    category="docs",
                    severity="low",
                    description=f"TODO/FIXME found: {line[:100]}",
                    target_path=parts[0],
                    auto_fixable=False,
                ))
    except Exception:
        pass
    return tasks


def discover_security() -> list[Task]:
    """Scan for security issues."""
    tasks = []
    patterns = [
        ("shell=True", "high", "shell=True found"),
        ("password", "high", "password reference"),
        ("secret", "medium", "secret reference"),
        ("token", "low", "token reference"),
    ]
    for pattern, severity, desc in patterns:
        try:
            result = subprocess.run(
                ["grep", "-rn", pattern, "modules/ai/jarvis/src/", "--include=*.py", "-i"],
                capture_output=True, text=True, timeout=10,
                cwd=str(REPO_ROOT),
            )
            for line in result.stdout.splitlines()[:3]:
                parts = line.split(":", 1)
                if len(parts) >= 2 and "# noqa" not in line:
                    tasks.append(Task(
                        id=f"sec-{hash(line) % 100000}",
                        category="security",
                        severity=severity,
                        description=f"{desc}: {line[:100]}",
                        target_path=parts[0],
                        auto_fixable=False,
                    ))
        except Exception:
            pass
    return tasks


def discover_dedup() -> list[Task]:
    """Find code duplication patterns."""
    tasks = []
    patterns = [
        "def command_allowed",
        "def has_chaining",
        "_DANGEROUS",
        "_SAFE_PIPE",
    ]
    for pat in patterns:
        try:
            result = subprocess.run(
                ["grep", "-rn", pat, "modules/ai/jarvis/src/", "--include=*.py"],
                capture_output=True, text=True, timeout=10,
                cwd=str(REPO_ROOT),
            )
            matches = result.stdout.strip().splitlines()
            if len(matches) > 2:
                tasks.append(Task(
                    id=f"dedup-{hash(pat) % 100000}",
                    category="dedup",
                    severity="low",
                    description=f"Pattern '{pat}' appears {len(matches)} times",
                    target_path=matches[0].split(":")[0] if matches else "",
                    auto_fixable=False,
                ))
        except Exception:
            pass
    return tasks


def discover_dead_code() -> list[Task]:
    """Find dead code and unused imports."""
    tasks = []
    try:
        result = subprocess.run(
            ["grep", "-rn", "^def ", "modules/ai/jarvis/src/jarvis/core/", "--include=*.py"],
            capture_output=True, text=True, timeout=10,
            cwd=str(REPO_ROOT),
        )
        func_count = len(result.stdout.strip().splitlines())
        if func_count > 50:
            tasks.append(Task(
                id=f"dead-{int(__import__('time').time())}",
                category="dead-code",
                severity="info",
                description=f"{func_count} functions in core/ — consider review",
                target_path="modules/ai/jarvis/src/jarvis/core/",
                auto_fixable=False,
            ))
    except Exception:
        pass
    return tasks


def discover_git_hygiene() -> list[Task]:
    """Check git status and stale work."""
    tasks = []
    try:
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            capture_output=True, text=True, timeout=10,
            cwd=str(REPO_ROOT),
        )
        dirty = len(result.stdout.strip().splitlines())
        if dirty > 0:
            tasks.append(Task(
                id=f"git-{int(__import__('time').time())}",
                category="git-hygiene",
                severity="info",
                description=f"{dirty} uncommitted files",
                target_path=".",
                auto_fixable=False,
            ))
    except Exception:
        pass
    return tasks


def discover_nix_lint() -> list[Task]:
    """Run Nix linters."""
    tasks = []
    for linter in ["statix", "deadnix"]:
        try:
            result = subprocess.run(
                [linter, "."] if linter == "statix" else [linter, "."],
                capture_output=True, text=True, timeout=30,
                cwd=str(REPO_ROOT),
            )
            if result.returncode != 0 and result.stdout.strip():
                tasks.append(Task(
                    id=f"nix-{linter}-{int(__import__('time').time())}",
                    category="nix-lint",
                    severity="medium",
                    description=f"{linter} found issues: {result.stdout[:200]}",
                    target_path=".",
                    auto_fixable=(linter == "statix"),
                ))
        except FileNotFoundError:
            pass
    return tasks


def discover_nix_check() -> list[Task]:
    """Validate NixOS configuration."""
    tasks = []
    try:
        result = subprocess.run(
            ["nix", "build", ".#jarvis", "--dry-run"],
            capture_output=True, text=True, timeout=60,
            cwd=str(REPO_ROOT),
        )
        if result.returncode != 0:
            tasks.append(Task(
                id=f"nixcheck-{int(__import__('time').time())}",
                category="nix-check",
                severity="high",
                description=f"Nix build check failed: {result.stderr[:200]}",
                target_path=".",
                auto_fixable=False,
            ))
    except Exception:
        pass
    return tasks


def discover_performance() -> list[Task]:
    """Check for performance opportunities."""
    tasks = []
    try:
        result = subprocess.run(
            ["grep", "-rn", "time\\.time\\|time\\.monotonic", "modules/ai/jarvis/src/", "--include=*.py"],
            capture_output=True, text=True, timeout=10,
            cwd=str(REPO_ROOT),
        )
        count = len(result.stdout.strip().splitlines())
        if count > 10:
            tasks.append(Task(
                id=f"perf-{int(__import__('time').time())}",
                category="performance",
                severity="info",
                description=f"{count} timing calls found — review for optimization",
                target_path="modules/ai/jarvis/src/",
                auto_fixable=False,
            ))
    except Exception:
        pass
    return tasks


def discover_missao() -> list[Task]:
    """Read TODO-MISSAO.md and convert Status: TODO items into Tasks.

    P0/P1 (security/Nix architecture) → auto_fixable=False (supervised only)
    P2/P3 (quality/docs) → auto_fixable=True (can go through safety gate)
    """
    path = REPO_ROOT / "TODO-MISSAO.md"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    tasks = []
    for block in re.split(r"\n### ", text)[1:]:
        header, _, body = block.partition("\n")
        m = re.match(r"(P\d)-(\d+): (.+)", header)
        if not m:
            continue
        prio, num, title = m.groups()
        status_m = re.search(r"\*\*Status\*\*:\s*(\w+)", body)
        if not status_m or status_m.group(1) != "TODO":
            continue
        arq_m = re.search(r"\*\*Arquivos\*\*:\s*(.+)", body)
        severity = {"P0": "critical", "P1": "high", "P2": "medium", "P3": "low"}.get(prio, "info")
        tasks.append(Task(
            id=f"missao-{prio}-{num}",
            category="missao",
            severity=severity,
            description=title.strip(),
            target_path=(arq_m.group(1).strip() if arq_m else ""),
            auto_fixable=prio in ("P2", "P3"),
        ))
    return tasks


# ═══ Registry ═══

CATEGORY_REGISTRY: dict[str, Callable[[], list[Task]]] = {
    "test": discover_test,
    "docs": discover_docs,
    "security": discover_security,
    "dedup": discover_dedup,
    "dead-code": discover_dead_code,
    "git-hygiene": discover_git_hygiene,
    "nix-lint": discover_nix_lint,
    "nix-check": discover_nix_check,
    "performance": discover_performance,
    "missao": discover_missao,
}

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
