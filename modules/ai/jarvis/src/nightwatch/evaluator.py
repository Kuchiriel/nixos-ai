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


def get_git_diff() -> str:
    """Get current uncommitted changes."""
    try:
        result = subprocess.run(
            ["git", "diff"],
            capture_output=True, text=True, timeout=10,
            cwd=str(REPO_ROOT),
        )
        return result.stdout[:10000]
    except Exception:
        return ""


def get_git_diff_stat() -> str:
    """Get diff statistics."""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True, text=True, timeout=10,
            cwd=str(REPO_ROOT),
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
- Be objective and critical
- Don't just say "looks good"
- Check if the change actually addresses the task
- Check for regressions
- Check for missing tests
- Check for security issues
- Check for code quality

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
) -> ReviewResult:
    """Review a change using diff and test results."""
    diff = get_git_diff()
    diff_stat = get_git_diff_stat()
    
    if not diff:
        return ReviewResult(
            verdict="pass",
            summary="No changes to review",
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
    """Quick automated review without LLM."""
    issues = []
    suggestions = []
    
    # Check for dangerous patterns
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
            issues.append(f"Dangerous pattern found: {pattern}")
    
    # Check for test failures
    if "FAILED" in test_output or "ERROR" in test_output:
        issues.append("Test failures detected")
    
    # Check for large changes
    added = sum(1 for line in diff.split("\n") if line.startswith("+") and not line.startswith("+++"))
    removed = sum(1 for line in diff.split("\n") if line.startswith("-") and not line.startswith("---"))
    if added + removed > 200:
        suggestions.append(f"Large change: +{added}/-{removed} lines. Consider breaking into smaller changes.")
    
    # Check for missing tests
    if ".py" in diff and "test" not in diff.lower():
        suggestions.append("Python files changed but no test changes detected")
    
    verdict = "pass" if not issues else "fail"
    confidence = 0.7 if not issues else 0.9
    
    return ReviewResult(
        verdict=verdict,
        issues=issues,
        suggestions=suggestions,
        confidence=confidence,
        summary=f"Auto-review: {len(issues)} issues, {len(suggestions)} suggestions",
    )
