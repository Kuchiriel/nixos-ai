"""Nightwatch v2 — Learning Loop

Detects recurring patterns across nightwatch runs.
Updates agent memory with insights.
Append-only log for audit trail.
"""

from __future__ import annotations

import collections
import json
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any

LOG_DIR = Path.home() / ".local/state/jarvis/nightwatch"
MEMORY_PATH = Path.home() / "projects/nixos-ai/docs/NIGHTWATCH-MEMORY.md"


@dataclass
class PatternInsight:
    """A recurring pattern detected across runs."""
    category: str
    path_glob: str
    occurrences: int
    suggestion: str


def detect_recurring_patterns(
    window_days: int = 14,
    min_occurrences: int = 3,
) -> list[PatternInsight]:
    """Detect patterns that appear multiple times across runs.

    Groups by (category, directory) — no NLP, cheap on CPU.
    Only flags real structural patterns, not isolated findings.
    """
    log_path = LOG_DIR / "history.jsonl"
    if not log_path.exists():
        return []

    cutoff = time.time() - (window_days * 86400)
    counter: dict[tuple[str, str], int] = collections.Counter()

    for line in log_path.read_text().splitlines():
        try:
            entry = json.loads(line)
        except json.JSONDecodeError:
            continue

        ts = entry.get("timestamp", 0)
        if ts < cutoff:
            continue

        category = entry.get("category", "unknown")
        desc = entry.get("description", "")
        # Extract path from description or use category
        key = (category, desc[:50])
        counter[key] += 1

    insights: list[PatternInsight] = []
    for (category, desc), n in counter.items():
        if n >= min_occurrences:
            insights.append(PatternInsight(
                category=category,
                path_glob=desc,
                occurrences=n,
                suggestion=_suggest_for(category, desc),
            ))

    return insights


def _suggest_for(category: str, desc: str) -> str:
    """Generate a suggestion based on category and pattern."""
    suggestions = {
        "code-quality": f"Consider structural refactoring — recurring pattern in {desc}",
        "test-coverage": f"Dedicated test suite needed for {desc}",
        "security-scan": f"Priority manual audit for {desc}",
        "nix-check": f"Review NixOS configuration drift in {desc}",
        "dedup": f"Consolidate duplicated code in {desc}",
        "docs": f"Address recurring TODO/FIXME markers in {desc}",
    }
    return suggestions.get(category, f"Recurring pattern in {desc} — investigate root cause")


def update_agent_memory(insights: list[PatternInsight]) -> None:
    """Append insights to NIGHTWATCH-MEMORY.md (append-only, never rewritten)."""
    if not insights:
        return

    MEMORY_PATH.parent.mkdir(parents=True, exist_ok=True)

    block = [f"\n## {date.today().isoformat()} — patterns detected\n"]
    for insight in insights:
        block.append(
            f"- **{insight.category}** in `{insight.path_glob}` — "
            f"{insight.occurrences}x in 14 days → {insight.suggestion}"
        )

    with open(MEMORY_PATH, "a") as f:
        f.write("\n".join(block) + "\n")


def get_stats() -> dict[str, Any]:
    """Get summary statistics from nightwatch history."""
    log_path = LOG_DIR / "history.jsonl"
    if not log_path.exists():
        return {"total_runs": 0, "total_tasks": 0}

    runs: dict[str, list] = collections.defaultdict(list)
    for line in log_path.read_text().splitlines():
        try:
            entry = json.loads(line)
            runs[entry.get("run_id", "unknown")].append(entry)
        except json.JSONDecodeError:
            continue

    total_tasks = sum(len(tasks) for tasks in runs.values())
    total_fixed = sum(
        1 for tasks in runs.values()
        for t in tasks if t.get("status") == "fixed"
    )

    return {
        "total_runs": len(runs),
        "total_tasks": total_tasks,
        "total_fixed": total_fixed,
        "success_rate": total_fixed / total_tasks if total_tasks > 0 else 0,
    }
