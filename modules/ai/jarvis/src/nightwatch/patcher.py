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
        # New file patch
        if line.startswith("=== FILE: ") and line.endswith(" ==="):
            if current_patch and current_patch.hunks:
                patches.append(current_patch)
            path = line[10:-4].strip()
            current_patch = FilePatch(path=path)
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
        elif line.strip() == "--- new text ---":
            mode = "new"
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
                    current_hunk.new_text = line
    
    # Don't forget last patch
    if current_patch and current_patch.hunks:
        patches.append(current_patch)
    
    return patches


def apply_hunk(content: str, hunk: PatchHunk) -> tuple[bool, str]:
    """Apply a single hunk to file content.

    FAIL-CLOSED: only exact and line-by-line matches allowed.
    Fuzzy matching removed — it could apply patches to wrong locations.

    Returns (success, new_content).
    """
    # 1. Exact match
    if hunk.old_text in content:
        new_content = content.replace(hunk.old_text, hunk.new_text, 1)
        return True, new_content

    # 2. Line-by-line match (for multi-line hunks)
    old_lines = hunk.old_text.strip().split("\n")
    content_lines = content.split("\n")

    for i in range(len(content_lines) - len(old_lines) + 1):
        match = True
        for j, old_line in enumerate(old_lines):
            if content_lines[i + j].strip() != old_line.strip():
                match = False
                break
        if match:
            new_lines = content_lines[:i] + hunk.new_text.split("\n") + content_lines[i + len(old_lines):]
            return True, "\n".join(new_lines)

    # FAIL-CLOSED: no fuzzy match — reject if exact/line match failed
    return False, content


def apply_patch(patch: FilePatch) -> tuple[bool, str, str]:
    """Apply a file patch with validation.
    
    Returns (success, new_content_or_error, diff).
    """
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
    if baseline is None:
        return False, f"File not found: {patch.path}", ""
    
    # Apply hunks
    content = baseline
    applied = 0
    for hunk in patch.hunks:
        success, new_content = apply_hunk(content, hunk)
        if success:
            content = new_content
            applied += 1
        else:
            return False, f"Hunk not found in {patch.path}: {hunk.old_text[:50]}...", ""
    
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
