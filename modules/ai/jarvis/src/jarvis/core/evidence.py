"""
Evidence Collection — each task produces verifiable evidence.

Based on the principle: "IMPLEMENTED" is not the same as "VERIFIED".

Evidence types:
- code_change: git diff showing what changed
- test_result: pytest output showing tests pass
- validation: nix flake check, AST parse, etc
- screenshot: visual evidence of GUI changes
- metric: quantitative measurement before/after
- comparison: before/after comparison
- e2e: end-to-end execution proof

Each task MUST produce evidence proportional to its risk.
"""

import json
import os
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class EvidenceItem:
    """A single piece of evidence."""
    type: str  # code_change, test_result, validation, screenshot, metric, comparison, e2e
    description: str
    data: str = ""  # raw evidence data (diff, output, path, etc)
    passed: bool = True
    timestamp: float = 0
    metadata: dict = field(default_factory=dict)

    def __post_init__(self):
        if not self.timestamp:
            self.timestamp = time.time()

    def to_dict(self):
        return asdict(self)


@dataclass
class TaskEvidence:
    """Complete evidence package for a task."""
    task_id: str
    task_description: str
    project: str
    persona: str = ""
    model_tier: str = ""
    items: list[EvidenceItem] = field(default_factory=list)
    started_at: float = 0
    completed_at: float = 0
    verdict: str = "pending"  # pending, implemented, tested, verified, partial, failed

    @property
    def all_passed(self) -> bool:
        return all(item.passed for item in self.items) if self.items else False

    @property
    def evidence_count(self) -> int:
        return len(self.items)

    @property
    def has_code_change(self) -> bool:
        return any(item.type == "code_change" for item in self.items)

    @property
    def has_test_result(self) -> bool:
        return any(item.type == "test_result" for item in self.items)

    @property
    def has_validation(self) -> bool:
        return any(item.type == "validation" for item in self.items)

    def to_dict(self):
        return {
            "task_id": self.task_id,
            "task_description": self.task_description,
            "project": self.project,
            "persona": self.persona,
            "model_tier": self.model_tier,
            "items": [item.to_dict() for item in self.items],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "verdict": self.verdict,
            "all_passed": self.all_passed,
            "evidence_count": self.evidence_count,
        }


class EvidenceCollector:
    """Collects and manages evidence for tasks."""

    def __init__(self, state_dir: str = None):
        if state_dir is None:
            state_dir = os.path.expanduser("~/.local/state/jarvis/evidence")
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)

    def start_task(self, task_id: str, description: str, project: str) -> TaskEvidence:
        """Start collecting evidence for a task."""
        evidence = TaskEvidence(
            task_id=task_id,
            task_description=description,
            project=project,
            started_at=time.time(),
        )
        return evidence

    def add_code_change(self, evidence: TaskEvidence, files: list[str], diff: str = "") -> None:
        """Add code change evidence."""
        if not diff and files:
            # Try to get git diff
            try:
                result = subprocess.run(
                    ["git", "diff", "--stat"] + files,
                    capture_output=True, text=True, timeout=10,
                )
                diff = result.stdout
            except Exception:
                diff = f"Files modified: {', '.join(files)}"

        evidence.items.append(EvidenceItem(
            type="code_change",
            description=f"Modified {len(files)} file(s)",
            data=diff[:2000],
            passed=True,
            metadata={"files": files},
        ))

    def add_test_result(self, evidence: TaskEvidence, test_output: str, passed: bool) -> None:
        """Add test result evidence."""
        evidence.items.append(EvidenceItem(
            type="test_result",
            description=f"Tests {'passed' if passed else 'failed'}",
            data=test_output[:2000],
            passed=passed,
        ))

    def add_validation(self, evidence: TaskEvidence, name: str, output: str, passed: bool) -> None:
        """Add validation evidence."""
        evidence.items.append(EvidenceItem(
            type="validation",
            description=name,
            data=output[:1000],
            passed=passed,
        ))

    def add_metric(self, evidence: TaskEvidence, name: str, before: float, after: float, unit: str = "", lower_is_better: bool = False) -> None:
        """Add metric evidence."""
        improvement = ((after - before) / before * 100) if before > 0 else 0
        if lower_is_better:
            passed = after <= before  # lower is better
        else:
            passed = after >= before  # higher is better
        evidence.items.append(EvidenceItem(
            type="metric",
            description=f"{name}: {before}{unit} → {after}{unit} ({improvement:+.1f}%)",
            data=json.dumps({"before": before, "after": after, "unit": unit}),
            passed=passed,
            metadata={"before": before, "after": after, "unit": unit, "improvement_pct": improvement},
        ))

    def add_comparison(self, evidence: TaskEvidence, name: str, before: str, after: str) -> None:
        """Add before/after comparison."""
        evidence.items.append(EvidenceItem(
            type="comparison",
            description=f"{name} comparison",
            data=f"BEFORE:\n{before[:500]}\n\nAFTER:\n{after[:500]}",
            passed=True,
        ))

    def add_e2e(self, evidence: TaskEvidence, description: str, output: str, passed: bool) -> None:
        """Add end-to-end execution evidence."""
        evidence.items.append(EvidenceItem(
            type="e2e",
            description=description,
            data=output[:2000],
            passed=passed,
        ))

    def complete_task(self, evidence: TaskEvidence) -> None:
        """Finalize evidence and determine verdict."""
        evidence.completed_at = time.time()

        if not evidence.all_passed:
            evidence.verdict = "failed"
        elif evidence.has_code_change and evidence.has_test_result and evidence.has_validation:
            evidence.verdict = "verified"
        elif evidence.has_code_change and evidence.has_test_result:
            evidence.verdict = "tested"
        elif evidence.has_code_change:
            evidence.verdict = "implemented"
        else:
            evidence.verdict = "partial"

        # Save to disk
        self._save(evidence)

    def _save(self, evidence: TaskEvidence) -> None:
        """Save evidence to disk."""
        evidence_file = self.state_dir / f"{evidence.task_id}.json"
        with open(evidence_file, "w") as f:
            json.dump(evidence.to_dict(), f, indent=2, default=str)

        # Also append to summary log
        summary_file = self.state_dir / "evidence-log.jsonl"
        summary_entry = {
            "task_id": evidence.task_id,
            "verdict": evidence.verdict,
            "evidence_count": evidence.evidence_count,
            "all_passed": evidence.all_passed,
            "project": evidence.project,
            "timestamp": evidence.completed_at,
        }
        with open(summary_file, "a") as f:
            f.write(json.dumps(summary_entry, default=str) + "\n")

    def get_task_evidence(self, task_id: str) -> Optional[dict]:
        """Get evidence for a specific task."""
        evidence_file = self.state_dir / f"{task_id}.json"
        if evidence_file.exists():
            with open(evidence_file) as f:
                return json.load(f)
        return None

    def get_summary(self) -> dict:
        """Get evidence summary across all tasks."""
        summary_file = self.state_dir / "evidence-log.jsonl"
        if not summary_file.exists():
            return {"total": 0, "by_verdict": {}}

        entries = []
        for line in summary_file.read_text().splitlines():
            if line.strip():
                try:
                    entries.append(json.loads(line))
                except Exception:
                    continue

        by_verdict = {}
        for entry in entries:
            verdict = entry.get("verdict", "unknown")
            by_verdict[verdict] = by_verdict.get(verdict, 0) + 1

        return {
            "total": len(entries),
            "by_verdict": by_verdict,
            "recent": entries[-5:] if entries else [],
        }

    def collect_git_diff(self, evidence: TaskEvidence, project_path: str = ".") -> None:
        """Collect git diff as evidence."""
        try:
            result = subprocess.run(
                ["git", "diff", "--stat"],
                capture_output=True, text=True, timeout=10,
                cwd=project_path,
            )
            if result.stdout.strip():
                self.add_code_change(evidence, [], result.stdout)
        except Exception:
            pass

    def collect_test_output(self, evidence: TaskEvidence, project_path: str = ".") -> None:
        """Run tests and collect output as evidence."""
        try:
            result = subprocess.run(
                ["python3", "-m", "pytest", "modules/ai/jarvis/tests/", "-x", "-q", "--tb=short"],
                capture_output=True, text=True, timeout=120,
                cwd=project_path,
            )
            passed = result.returncode == 0
            output = result.stdout + result.stderr
            self.add_test_result(evidence, output, passed)
        except Exception as e:
            self.add_test_result(evidence, str(e), False)

    def collect_nix_validation(self, evidence: TaskEvidence, project_path: str = ".") -> None:
        """Run nix flake check as evidence."""
        try:
            result = subprocess.run(
                ["nix", "flake", "check", "--no-build"],
                capture_output=True, text=True, timeout=120,
                cwd=project_path,
            )
            passed = result.returncode == 0
            output = result.stdout + result.stderr
            self.add_validation(evidence, "nix flake check", output, passed)
        except Exception as e:
            self.add_validation(evidence, "nix flake check", str(e), False)
