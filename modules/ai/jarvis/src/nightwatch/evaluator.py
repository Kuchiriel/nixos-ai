"""Evaluator — Independent review of changes.

The evaluator receives:
- Original task
- Diff
- Acceptance criteria
- Test results

And provides:
- Pass/fail verdict
- Specific issues found
- Suggestions for improvement
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


from nightwatch.paths import REPO_ROOT


@dataclass
class ReviewResult:
    """Result of independent review."""
    verdict: str  # pass, fail, needs_revision
    issues: list[str] = field(default_factory=list)
    suggestions: list[str] = field(default_factory=list)
    confidence: float = 0.0
    summary: str = ""
    
    @property
    def passed(self) -> bool:
        return self.verdict == "pass"


def _get_git_cwd() -> str:
    """Get the correct git working directory (project root, not nixos-ai)."""
    import os
    env_root = os.environ.get("JARVIS_PROJECT_ROOT")
    if env_root and Path(env_root).exists():
        return env_root
    return str(REPO_ROOT)


def get_git_diff() -> str:
    """Get current uncommitted changes (modified + untracked files with content)."""
    cwd = _get_git_cwd()
    diff = ""
    try:
        # Modified/staged files
        result = subprocess.run(
            ["git", "diff"],
            capture_output=True, text=True, timeout=10,
            cwd=cwd,
        )
        diff = result.stdout[:8000]
        # Also include untracked files (new file creation) with their content
        result2 = subprocess.run(
            ["git", "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, timeout=10,
            cwd=cwd,
        )
        untracked = result2.stdout.strip()
        if untracked:
            diff += f"\n\n=== NEW FILES (untracked) ===\n"
            for f in untracked.split("\n"):
                f = f.strip()
                if f:
                    try:
                        fpath = Path(cwd) / f
                        if fpath.exists() and fpath.is_file():
                            content = fpath.read_text(encoding="utf-8")[:3000]
                            diff += f"\n--- {f} (NEW) ---\n{content}\n"
                    except Exception:
                        diff += f"\n--- {f} (NEW, unreadable) ---\n"
    except Exception:
        pass
    return diff


def get_git_diff_stat() -> str:
    """Get diff statistics."""
    cwd = _get_git_cwd()
    try:
        result = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True, text=True, timeout=10,
            cwd=cwd,
        )
        return result.stdout
    except Exception:
        return ""


def review_with_llm(
    task_description: str,
    acceptance_criteria: str,
    diff: str,
    test_results: str,
    call_llm_fn,
) -> ReviewResult:
    """Use the LLM to review changes independently."""
    
    prompt = f"""You are an independent code reviewer. Review this change objectively.

TASK: {task_description}

ACCEPTANCE CRITERIA: {acceptance_criteria}

DIFF:
{diff[:5000]}

TEST RESULTS:
{test_results[:2000]}

Provide your review as JSON:
{{
  "verdict": "pass" or "fail" or "needs_revision",
  "issues": ["list of specific issues found"],
  "suggestions": ["list of improvement suggestions"],
  "confidence": 0.0-1.0,
  "summary": "brief summary of your review"
}}

Rules:
- Be objective but fair
- A test that correctly validates the function is acceptable even if it could be more thorough
- Check if the change actually addresses the task
- Check for regressions (tests that now fail)
- Check for security issues
- Only reject if the change is broken, incorrect, or introduces regressions
- Style preferences (like assertion style) are suggestions, not failures

Review now:"""

    response = call_llm_fn(prompt, max_tokens=1000)
    
    # Parse JSON from response
    try:
        start = response.find("{")
        end = response.rfind("}") + 1
        if start >= 0 and end > start:
            data = json.loads(response[start:end])
            return ReviewResult(
                verdict=data.get("verdict", "fail"),
                issues=data.get("issues", []),
                suggestions=data.get("suggestions", []),
                confidence=data.get("confidence", 0.5),
                summary=data.get("summary", ""),
            )
    except json.JSONDecodeError:
        pass
    
    # Fallback: conservative fail
    return ReviewResult(
        verdict="needs_revision",
        issues=["Could not parse review response"],
        confidence=0.0,
        summary="Review failed to parse",
    )


def review_change(
    task_description: str,
    acceptance_criteria: str,
    test_output: str,
    call_llm_fn,
    require_change: bool = True,
) -> ReviewResult:
    """Review a change using diff and test results.

    Args:
        require_change: If True (default), a task that requires work
            cannot pass with zero diff. The caller should set this to
            False only for tasks that are explicitly no-ops (e.g.
            "verify X is already correct").
    """
    diff = get_git_diff()
    diff_stat = get_git_diff_stat()

    if not diff:
        if require_change:
            return ReviewResult(
                verdict="fail",
                summary="Task requires changes but no diff was produced",
                issues=["No changes detected — task may not have been executed, "
                        "or the LLM decided no changes were needed. "
                        "If the task is truly a no-op, set require_change=False."],
                confidence=0.9,
            )
        return ReviewResult(
            verdict="pass",
            summary="No changes needed (explicit no-op)",
            confidence=1.0,
        )

    return review_with_llm(
        task_description=task_description,
        acceptance_criteria=acceptance_criteria,
        diff=diff_stat + "\n\n" + diff,
        test_results=test_output,
        call_llm_fn=call_llm_fn,
    )


def auto_review(diff: str, test_output: str) -> ReviewResult:
    """Quick automated review without LLM.

    Checks structural integrity of the change:
    - Dangerous patterns
    - Test failures
    - Size sanity
    - Import removal
    - Function/class removal
    """
    issues = []
    suggestions = []

    # 1. Check for dangerous patterns
    dangerous = [
        "rm -rf",
        "sudo",
        "chmod 777",
        "eval(",
        "exec(",
        "shell=True",
        "__import__",
    ]
    for pattern in dangerous:
        if pattern in diff:
            issues.append(f"Dangerous pattern: {pattern}")

    # 2. Check for test failures
    if "FAILED" in test_output or "ERROR" in test_output:
        issues.append("Test failures in output")

    # 3. Size sanity
    added = sum(1 for line in diff.split("\n") if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff.split("\n") if line.startswith("-") and not line.startswith("---"))
    if added + removed > 200:
        suggestions.append(f"Large change: +{added}/-{removed} lines")

    # 4. Check for import removal (structural damage indicator)
    removed_lines = [l[1:] for l in diff.split("\n") if l.startswith("-") and not l.startswith("---")]
    removed_imports = [l for l in removed_lines if l.strip().startswith("import ") or l.strip().startswith("from ")]
    if removed_imports:
        issues.append(f"Imports removed: {len(removed_imports)} import statements")

    # 5. Check for function/class removal
    removed_defs = [l for l in removed_lines if l.strip().startswith("def ") or l.strip().startswith("class ")]
    if removed_defs:
        names = [l.strip().split("(")[0].split(":")[0].replace("def ", "").replace("class ", "") for l in removed_defs]
        issues.append(f"Definitions removed: {', '.join(names)}")

    # 6. Check for missing tests
    if ".py" in diff and "test" not in diff.lower():
        suggestions.append("Python changed without test changes")

    verdict = "pass" if not issues else "fail"
    confidence = 0.7 if not issues else 0.9

    return ReviewResult(
        verdict=verdict,
        issues=issues,
        suggestions=suggestions,
        confidence=confidence,
        summary=f"Auto-review: {len(issues)} issues, {len(suggestions)} suggestions",
    )
