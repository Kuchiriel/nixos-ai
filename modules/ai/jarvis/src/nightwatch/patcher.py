"""Patcher — Patch-based file editing for the Nightwatch harness.

Instead of asking the LLM to return full files, we ask for structured patches.
This is safer because:
1. Only specific changes are applied
2. Context around changes is preserved
3. We can validate each hunk independently
4. We can detect if the file changed since we read it
"""

from __future__ import annotations

import difflib
import json
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from nightwatch.file_guard import apply_with_guard, strip_markdown_fences
from nightwatch.paths import REPO_ROOT


@dataclass
class PatchHunk:
    """A single change within a file."""
    old_text: str
    new_text: str
    line_start: int = 0
    line_end: int = 0


@dataclass
class FilePatch:
    """A patch for a single file."""
    path: str
    hunks: list[PatchHunk] = field(default_factory=list)
    rationale: str = ""
    create: bool = False  # True = create new file (not modify existing)
    whole: bool = False  # True = hunk new_text is the COMPLETE file content


@dataclass
class PatchResult:
    """Result of applying a patch."""
    success: bool
    files_applied: list[str] = field(default_factory=list)
    files_failed: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    diff: str = ""


def get_file_baseline(path: Path) -> str | None:
    """Get the current content of a file (baseline)."""
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return None
    except Exception:
        return None


def get_git_baseline(path: Path) -> str | None:
    """Get the git version of a file (last committed)."""
    try:
        rel = path.relative_to(REPO_ROOT)
        result = subprocess.run(
            ["git", "show", f"HEAD:{rel}"],
            capture_output=True, text=True, timeout=10,
            cwd=str(REPO_ROOT),
        )
        if result.returncode == 0:
            return result.stdout
    except Exception:
        pass
    return None


def parse_llm_patch(response: str) -> list[FilePatch]:
    """Parse LLM response into structured patches.
    
    Expected format:
    === FILE: path/to/file.py ===
    REASON: why this change is needed
    --- old text ---
    ...exact text to find...
    --- new text ---
    ...replacement text...
    --- end ---
    
    Or unified diff format:
    --- a/path/to/file.py
    +++ b/path/to/file.py
    @@ -10,5 +10,7 @@
    ...
    """
    patches = []
    current_patch = None
    current_hunk = None
    mode = None  # None, "old", "new"
    
    for line in response.split("\n"):
        # New file patch (modify existing)
        if line.startswith("=== FILE: ") and line.endswith(" ==="):
            if current_patch and current_patch.hunks:
                patches.append(current_patch)
            path = line[10:-4].strip()
            current_patch = FilePatch(path=path)
            current_hunk = None
            mode = None
            continue
        # Create new file
        if line.startswith("=== CREATE: ") and line.endswith(" ==="):
            if current_patch and current_patch.hunks:
                patches.append(current_patch)
            path = line[12:-4].strip()
            current_patch = FilePatch(path=path, create=True)
            current_hunk = None
            mode = None
            continue
        # Whole-file replacement (for weak/local models — tokens are free)
        if line.startswith("=== WHOLE: ") and line.endswith(" ==="):
            if current_patch and current_patch.hunks:
                patches.append(current_patch)
            path = line[11:-4].strip()
            current_patch = FilePatch(path=path, whole=True)
            current_hunk = None
            mode = None
            continue
        
        if current_patch is None:
            continue
        
        # Reason
        if line.startswith("REASON: "):
            current_patch.rationale = line[8:]
            continue
        
        # Old/new text markers
        if line.strip() == "--- old text ---":
            current_hunk = PatchHunk(old_text="", new_text="")
            mode = "old"
            continue
        elif line.strip() == "---" and mode is None and current_hunk is None:
            # Tolerance: weak models often emit a bare --- opener.
            # Only outside content collection (markdown --- inside
            # old/new text stays literal).
            current_hunk = PatchHunk(old_text="", new_text="")
            mode = "old"
            continue
        elif line.strip() == "--- new text ---":
            mode = "new"
            continue
        elif line.strip() == "--- content ---":
            # For CREATE: the entire content is the new file
            current_hunk = PatchHunk(old_text="", new_text="")
            mode = "new"  # reuse "new" mode to collect content
            continue
        elif line.strip() == "--- end ---":
            if current_hunk:
                current_patch.hunks.append(current_hunk)
            current_hunk = None
            mode = None
            continue
        
        # Collect text
        if current_hunk is not None:
            if mode == "old":
                if current_hunk.old_text:
                    current_hunk.old_text += "\n" + line
                else:
                    current_hunk.old_text = line
            elif mode == "new":
                if current_hunk.new_text:
                    current_hunk.new_text += "\n" + line
                else:
                    current_hunk.new_text = line    # Don't forget last patch
    if current_patch and current_patch.hunks:
        patches.append(current_patch)

    # Strip markdown fences from all hunks (LLM often wraps code in ```)
    for patch in patches:
        for hunk in patch.hunks:
            hunk.old_text = strip_markdown_fences(hunk.old_text.strip())
            hunk.new_text = strip_markdown_fences(hunk.new_text.strip())

    return patches


def _find_similar_content(search_text: str, file_content: str, context_lines: int = 3) -> str:
    """Find similar content in the file for failed matches (Aider-style 'Did you mean?').
    
    Searches for the first meaningful word/identifier from the search text
    and returns the surrounding lines as context.
    """
    if not search_text or not file_content:
        return ""
    
    # Extract first meaningful identifier from search text
    words = search_text.strip().split()
    search_term = ""
    for w in words:
        # Skip keywords and very short tokens
        if len(w) > 2 and w not in ('def', 'class', 'import', 'from', 'return', 'if', 'else', 'for', 'while', 'with', 'try', 'except', 'finally', 'and', 'or', 'not', 'in', 'is', 'None', 'True', 'False'):
            search_term = w.strip('():,')
            break
    
    if not search_term:
        return ""
    
    # Find the line containing this term
    file_lines = file_content.split('\n')
    for i, line in enumerate(file_lines):
        if search_term in line:
            # Return context around this line
            start = max(0, i - context_lines)
            end = min(len(file_lines), i + context_lines + 1)
            return '\n'.join(file_lines[start:end])
    
    return ""


def _lines_match_fuzzy(line_a: str, line_b: str, tolerance: float = 0.2) -> bool:
    """Check if two lines match with fuzzy tolerance.
    
    Allows up to `tolerance` fraction of characters to differ.
    This handles LLM generating slightly different whitespace,
    comments, or minor variations.
    
    For short lines (<20 chars), fuzzy matching is disabled to prevent
    false positives (e.g., 'def f():' matching 'def g():').
    """
    a, b = line_a.strip(), line_b.strip()
    if a == b:
        return True
    if not a or not b:
        return False
    # Short lines must match exactly — fuzzy is too risky for short strings
    if len(a) < 20 or len(b) < 20:
        return False
    # Quick check: same length ±20%
    if abs(len(a) - len(b)) > max(len(a), len(b)) * tolerance:
        return False
    # Count matching characters
    matches = sum(1 for ca, cb in zip(a, b) if ca == cb)
    max_len = max(len(a), len(b))
    return matches / max_len >= (1 - tolerance)


def apply_hunk(content: str, hunk: PatchHunk) -> tuple[bool, str]:
    """Apply a single hunk to file content.
    
    Matching strategy (from Aider research):
    1. Exact match
    2. Whitespace-insensitive line-by-line match
    3. Fuzzy line-by-line match (20% tolerance per line)
    
    Returns (success, new_content).
    """
    # 1. Exact match
    if hunk.old_text in content:
        new_content = content.replace(hunk.old_text, hunk.new_text, 1)
        return True, new_content

    old_lines = hunk.old_text.strip().split("\n")
    content_lines = content.split("\n")

    # 2. Whitespace-insensitive line-by-line match
    for i in range(len(content_lines) - len(old_lines) + 1):
        match = True
        for j, old_line in enumerate(old_lines):
            if content_lines[i + j].strip() != old_line.strip():
                match = False
                break
        if match:
            new_lines = content_lines[:i] + hunk.new_text.split("\n") + content_lines[i + len(old_lines):]
            return True, "\n".join(new_lines)

    # 3. Fuzzy line-by-line match (allows minor variations)
    for i in range(len(content_lines) - len(old_lines) + 1):
        match = True
        for j, old_line in enumerate(old_lines):
            if not _lines_match_fuzzy(content_lines[i + j], old_line):
                match = False
                break
        if match:
            new_lines = content_lines[:i] + hunk.new_text.split("\n") + content_lines[i + len(old_lines):]
            return True, "\n".join(new_lines)

    return False, content


def apply_patch(patch: FilePatch) -> tuple[bool, str, str]:
    """Apply a file patch with validation.
    
    Returns (success, new_content_or_error, diff).
    """
    import os
    env_root = os.environ.get("JARVIS_PROJECT_ROOT")
    project_root = Path(env_root) if env_root and Path(env_root).exists() else REPO_ROOT
    
    # Try project root first (external projects), then REPO_ROOT
    path = project_root / patch.path
    if not path.exists():
        path = REPO_ROOT / patch.path
    if not path.exists():
        # Try with common prefixes
        for prefix in ["modules/ai/jarvis/src/", "src/jarvis/", "jarvis/"]:
            alt = REPO_ROOT / prefix / patch.path
            if alt.exists():
                path = alt
                break
    
    # Get baseline
    baseline = get_file_baseline(path)
    
    # File creation
    if baseline is None:
        if patch.create and patch.hunks:
            # Use the new_text from hunks as the full file content
            content = patch.hunks[0].new_text
            if not content.strip():
                return False, f"CREATE requested but content is empty for {patch.path}", ""
            # Create parent directories
            path.parent.mkdir(parents=True, exist_ok=True)
            # Write the new file
            path.write_text(content, encoding="utf-8")
            diff = f"+++ new file {patch.path}\n" + "\n".join(
                f"+{line}" for line in content.splitlines()
            )
            return True, content, diff
        return False, f"File not found: {patch.path}", ""
    
    # Whole-file replacement: skip hunk matching, validate full content.
    # FileGuard enforces syntax/tests/structural integrity — safer than hunks
    # (no match ambiguity) and the recommended format for weak local models.
    if patch.whole and patch.hunks:
        content = patch.hunks[0].new_text
        if not content.strip():
            return False, f"WHOLE requested but content is empty for {patch.path}", ""
        if content.strip() == baseline.strip():
            return False, f"WHOLE content identical to current {patch.path} (no changes)", ""
        success, validation = apply_with_guard(path, content, baseline)
        if not success:
            return False, "; ".join(validation.errors), ""
        diff = "\n".join(difflib.unified_diff(
            baseline.splitlines(), content.splitlines(),
            fromfile=f"a/{patch.path}", tofile=f"b/{patch.path}",
        ))
        return True, content, diff

    # Apply hunks
    content = baseline
    applied = 0
    for hunk in patch.hunks:
        success, new_content = apply_hunk(content, hunk)
        if success:
            content = new_content
            applied += 1
        else:
            # Aider-style: show actual file content near the failed match
            # so the LLM can see what the file actually contains
            did_you_mean = _find_similar_content(hunk.old_text, content)
            error_msg = f"Hunk not found in {patch.path}: {hunk.old_text[:80]}..."
            if did_you_mean:
                error_msg += f"\n\nDid you mean to match this actual content from {patch.path}?\n{did_you_mean}"
            return False, error_msg, ""
    
    if applied == 0:
        return False, "No hunks applied", ""
    
    # Validate with FileGuard
    success, validation = apply_with_guard(path, content, baseline)
    if not success:
        return False, "; ".join(validation.errors), ""
    
    # Generate diff
    diff = "\n".join(difflib.unified_diff(
        baseline.splitlines(), content.splitlines(),
        fromfile=f"a/{patch.path}", tofile=f"b/{patch.path}",
    ))
    
    return True, content, diff


def create_patch_from_llm(
    task_description: str,
    target_files: list[str],
    llm_response: str,
) -> PatchResult:
    """Parse LLM response and create structured patches."""
    patches = parse_llm_patch(llm_response)
    
    if not patches:
        return PatchResult(
            success=False,
            errors=["No valid patches found in LLM response"],
        )
    
    result = PatchResult(success=True)
    
    for patch in patches:
        success, content_or_error, diff = apply_patch(patch)
        
        if success:
            result.files_applied.append(patch.path)
            result.diff += diff + "\n"
        else:
            result.files_failed.append(patch.path)
            result.errors.append(f"{patch.path}: {content_or_error}")
    
    result.success = len(result.files_failed) == 0
    return result


def request_patch_from_llm(
    task_description: str,
    target_files: list[str],
    call_llm_fn,
) -> PatchResult:
    """Ask the LLM to generate patches and apply them."""
    # Read current files
    file_contents = {}
    for path_str in target_files:
        path = REPO_ROOT / path_str
        if not path.exists():
            for prefix in ["modules/ai/jarvis/src/", "src/jarvis/", "jarvis/"]:
                alt = REPO_ROOT / prefix / path_str
                if alt.exists():
                    path = alt
                    break
        try:
            file_contents[path_str] = path.read_text(encoding="utf-8")[:6000]
        except Exception:
            pass
    
    if not file_contents:
        return PatchResult(success=False, errors=["No target files readable"])
    
    # Build prompt asking for patches, not full files
    files_section = "\n".join(
        f"=== {path} ===\n{content[:3000]}" 
        for path, content in file_contents.items()
    )
    
    prompt = f"""You are improving Python code. Generate STRUCTURAL PATCHES, not full files.

Task: {task_description}

Current code:
{files_section}

For EACH file you want to change, use EXACTLY this format:

=== FILE: path/to/file.py ===
REASON: why this change is needed
--- old text ---
exact text to find and replace (must match exactly, including whitespace)
--- new text ---
replacement text
--- end ---

Rules:
1. The "old text" must be EXACT substring of the current file
2. Keep changes minimal and focused
3. Preserve all existing functionality
4. Don't add markdown fences (```)
5. Don't include line numbers
6. If no changes needed, respond with NO_CHANGES_NEEDED

Generate patches now:"""

    response = call_llm_fn(prompt, max_tokens=3000)
    
    if "NO_CHANGES_NEEDED" in response:
        return PatchResult(success=True)
    
    return create_patch_from_llm(task_description, target_files, response)
