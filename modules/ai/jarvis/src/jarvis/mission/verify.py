"""Evidence-based verification plus per-task change attribution.

Two concrete problems this fixes:

1. **Completion by self-report.** The harness marked a task done when the
   LLM said so. Here `verify_task` returns DONE only if the acceptance
   criteria pass against the WORLD (file exists, content contains, tests
   pass, command exits 0). Without evidence the task is not done, and the
   reason is recorded.

2. **Diff attribution.** `persona_executor` ran
   `git diff --name-only HEAD` and attributed ALL of it to the current
   task, including previous or foreign work. Here the runner snapshots the
   dirty paths BEFORE execution, and attribution is the difference between
   "was dirty before" and "is dirty now" (plus new files). So the report
   ties a change to the task that produced it.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from jarvis.mission.models import AcceptanceCriterion, MissionTask


# ── diff / attribution ─────────────────────────────────────────────────────

@dataclass
class DiffSnapshot:
    """Set of modified paths plus a content hash, for one moment in time."""

    paths: frozenset[str] = frozenset()
    blob: dict[str, str] = field(default_factory=dict)   # path -> short sha1

    def new_paths(self, later: "DiffSnapshot") -> list[str]:
        return sorted(later.paths - self.paths)

    def changed_paths(self, later: "DiffSnapshot") -> list[str]:
        """Paths this task touched: new ones OR ones whose content differs.

        A file already dirty before and edited again shows up here (the
        hash changed) — which is correct: the task MODIFIED the file, it
        did not create it.
        """
        touched = set(later.paths - self.paths)
        for p, h in later.blob.items():
            if self.blob.get(p) != h:
                touched.add(p)
        return sorted(touched)


def _git(root: Path, *args: str, timeout: int = 20) -> str:
    r = subprocess.run(["git", "-C", str(root), *args],
                       capture_output=True, text=True, timeout=timeout)
    return r.stdout if r.returncode == 0 else ""


def take_snapshot(root: str | Path) -> DiffSnapshot:
    """Snapshot of the dirty tree (working tree + staged + untracked)."""
    root = Path(root)
    if not (root / ".git").exists():
        return DiffSnapshot()
    paths: set[str] = set()
    for args in (["diff", "--name-only", "HEAD"],
                 ["diff", "--name-only", "--cached"],
                 ["ls-files", "--others", "--exclude-standard"]):
        out = _git(root, *args)
        for line in out.splitlines():
            if line.strip():
                paths.add(line.strip())
    blob: dict[str, str] = {}
    for p in sorted(paths):
        fp = root / p
        try:
            if fp.is_file() and fp.stat().st_size < 4_000_000:
                blob[p] = hashlib.sha1(fp.read_bytes()).hexdigest()[:12]
            else:
                blob[p] = "big"
        except OSError:
            blob[p] = "unreadable"
    return DiffSnapshot(frozenset(paths), blob)


def head_sha(root: str | Path) -> str:
    return _git(Path(root), "rev-parse", "--short", "HEAD").strip()


# ── verification ───────────────────────────────────────────────────────────

@dataclass
class VerificationResult:
    verified: bool
    evidence: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if self.verified:
            return f"VERIFIED ({len(self.evidence)} evidence items)"
        return f"NOT VERIFIED: {'; '.join(self.missing[:3]) or 'no criteria'}"


def _check_one(crit: AcceptanceCriterion, root: Path,
               task: MissionTask) -> tuple[bool, str]:
    kind = crit.kind
    target = crit.target
    try:
        if kind == "file_exists":
            p = Path(target) if Path(target).is_absolute() else root / target
            ok = p.is_file()
            return ok, f"file_exists {target} -> {'present' if ok else 'MISSING'}"
        if kind == "file_absent":
            p = Path(target) if Path(target).is_absolute() else root / target
            ok = not p.exists()
            return ok, f"file_absent {target} -> {'absent (ok)' if ok else 'STILL EXISTS'}"
        if kind == "content_contains":
            p = Path(target) if Path(target).is_absolute() else root / target
            if not p.is_file():
                return False, f"content_contains {target} -> file missing"
            try:
                text = p.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                return False, f"content_contains {target} -> unreadable ({exc})"
            needle = crit.description or ""
            ok = (needle in text) if needle else bool(text.strip())
            return ok, (f"content_contains {target} ~ {needle!r} -> "
                        f"{'present' if ok else 'NOT FOUND'}")
        if kind == "test_passes":
            cmd = target or "python3 -m pytest -x -q"
            r = subprocess.run(["bash", "-lc", cmd], capture_output=True,
                               text=True, timeout=600, cwd=str(root))
            out = (r.stdout or "") + (r.stderr or "")
            ok = r.returncode == 0
            tail = " ".join(out.strip().splitlines()[-2:])[:160]
            return ok, f"test_passes `{cmd}` rc={r.returncode} {tail}"
        if kind == "command_ok":
            cmd = target or "true"
            r = subprocess.run(["bash", "-lc", cmd], capture_output=True,
                               text=True, timeout=300, cwd=str(root))
            out = (r.stdout or "") + (r.stderr or "")
            return r.returncode == 0, (f"command_ok `{cmd}` rc={r.returncode} "
                                       f"{' '.join(out.split())[:120]}")
        if kind == "diff_present":
            ok = bool(task.files_attributed)
            return ok, (f"diff_present -> {len(task.files_attributed)} file(s): "
                        f"{', '.join(task.files_attributed[:5]) or 'none'}")
        if kind == "evidence_present":
            ok = bool(task.verification_evidence or task.commit_sha)
            return ok, (f"evidence_present -> commit={task.commit_sha or '-'} "
                        f"evidence={len(task.verification_evidence)}")
    except subprocess.TimeoutExpired:
        return False, f"{kind} {target} -> TIMEOUT"
    except Exception as exc:  # noqa: BLE001 - verification never breaks the run
        return False, f"{kind} {target} -> error {type(exc).__name__}: {exc}"
    # Unknown criterion: does NOT pass (fail-closed). Declaring a new type
    # without implementing it here would mean a "verified" task with no
    # verification.
    return False, f"unknown criterion: {kind!r}"


def verify_task(task: MissionTask, project_root: str | Path) -> VerificationResult:
    """Verify a task against the world. No criteria => NOT verified.

    A task without acceptance criteria is a task without a contract: we
    say so explicitly instead of reading silence as success.
    """
    root = Path(project_root or task.project_root or ".")
    if not task.acceptance:
        return VerificationResult(
            verified=False,
            missing=["task has no verifiable acceptance criterion"],
        )
    evidence: list[str] = []
    missing: list[str] = []
    for crit in task.acceptance:
        ok, note = _check_one(crit, root, task)
        (evidence if ok else missing).append(note)
    # A single failing mandatory criterion fails the whole task.
    return VerificationResult(verified=not missing, evidence=evidence,
                              missing=missing)


# ── deriving criteria from text ────────────────────────────────────────────

_PATH_RE = __import__("re").compile(
    r"[\w\-./]+\.(?:py|nix|md|json|ya?ml|toml|sh|txt|js|ts|lua|cfg|ini|service)\b")


def criteria_from_description(description: str, *,
                              expect_changes: bool = False) -> list[AcceptanceCriterion]:
    """Derive verifiable criteria from a task description.

    Honest about its limits: it only converts what can actually be checked.
    A path cited in the text -> `file_exists`. A path with a needle after
    "containing" -> `content_contains`. A mention of tests -> `test_passes`.
    With no signal -> an empty list, and the orchestrator marks the task as
    needing a human criterion instead of faking verification.
    """
    import re
    out: list[AcceptanceCriterion] = []
    desc = description or ""

    m = re.search(r"(?:containing|contains|with)\s+[\"']?([^\"'\n]{3,80})[\"']?",
                  desc, re.IGNORECASE)
    needle = m.group(1).strip() if m else ""
    needle = re.sub(r"\.py.*$", "", needle).strip() or ""

    for pm in _PATH_RE.finditer(desc):
        path = pm.group(0)
        if needle and needle.lower() in desc.lower() and path.lower() in desc.lower():
            out.append(AcceptanceCriterion(
                kind="content_contains", target=path, description=needle))
        else:
            out.append(AcceptanceCriterion(
                kind="file_exists", target=path,
                description=needle if needle and path in needle else ""))

    if re.search(r"\b(test|pytest|tests pass|test suite)\b", desc, re.IGNORECASE):
        out.append(AcceptanceCriterion(
            kind="test_passes", target="",
            description="project test suite must pass"))
    if expect_changes:
        out.append(AcceptanceCriterion(
            kind="diff_present", target="", description=""))
    seen: set[tuple[str, str]] = set()
    uniq: list[AcceptanceCriterion] = []
    for c in out:
        k = (c.kind, c.target)
        if k not in seen:
            seen.add(k)
            uniq.append(c)
    return uniq