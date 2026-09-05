"""Harness — Unified orchestrator for the Nightwatch autonomous coding agent.

This is the SINGLE entrypoint for all nightwatch operations.
Replaces both orchestrator.py (v2 scripted) and llm_loop.py (v3 LLM-based).

Architecture:
    Task Discovery (categories + LLM)
        ↓
    TaskQueue (persistent state machine)
        ↓
    Patcher (LLM generates patches, not full files)
        ↓
    SafeEditor (atomic writes, validation, backup)
        ↓
    Validator (syntax → imports → tests)
        ↓
    Evaluator (independent review)
        ↓
    Checkpoint (save state)
        ↓
    Safety (protected paths, git ops)
        ↓
    Commit (only if all gates pass)
        ↓
    Learning (persist to AGENTS.md)
        ↓
    Telegram notification

Invariants:
    1. LLM never writes directly to filesystem
    2. Every change has a baseline
    3. Validation is proportional to change type
    4. Unit tests ≠ success
    5. Evaluator is independent from implementer
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from enum import Enum
from nightwatch.task_queue import TaskQueue, Task, TaskStatus, LoopDetector, MissionState
from jarvis.core.eventbus import EventBus, Event


class FailureType(str, Enum):
    """Classification of task failures for recovery strategy."""
    TRANSIENT = "transient"        # Network, timeout, temporary LLM error
    TOOL_FAILURE = "tool_failure"    # Tool returned error, could retry
    VALIDATION_FAILURE = "validation_failure"  # Code didn't pass checks
    CONTEXT_EXHAUSTION = "context_exhaustion"  # Ran out of context
    TASK_FAILURE = "task_failure"    # Task itself is flawed
    UNRECOVERABLE = "unrecoverable"  # Should not retry


def classify_failure(error: str, task_status: str) -> FailureType:
    """Classify a failure into a recovery strategy category."""
    error_lower = (error or "").lower()

    # Transient errors — worth retrying
    if any(kw in error_lower for kw in ["timeout", "connection", "network", "temporary"]):
        return FailureType.TRANSIENT
    if "llm error" in error_lower or "api error" in error_lower:
        return FailureType.TRANSIENT

    # Context exhaustion — need compaction
    if any(kw in error_lower for kw in ["context", "token", "exceeds", "overflow"]):
        return FailureType.CONTEXT_EXHAUSTION

    # Tool failures — could retry with different approach
    if any(kw in error_lower for kw in ["tool", "command", "permission", "denied"]):
        return FailureType.TOOL_FAILURE

    # Validation failures — code is wrong
    if any(kw in error_lower for kw in ["syntax", "import", "validation", "test fail"]):
        return FailureType.VALIDATION_FAILURE

    # SafeEditor rejections — LLM produced bad code
    if "safeditor" in error_lower or "rejected" in error_lower:
        return FailureType.VALIDATION_FAILURE

    # Protected path
    if "protected" in error_lower:
        return FailureType.UNRECOVERABLE

    # Default: task failure (flawed task definition)
    return FailureType.TASK_FAILURE
from nightwatch.safe_editor import SafeEditor, EditResult
from nightwatch.validator import validate_change, ValidationReport
from nightwatch.evaluator import review_change, auto_review, ReviewResult
from nightwatch.checkpoint import Checkpoint, create_checkpoint_for_task, get_recovery_context
from nightwatch import safety
from nightwatch import project_isolation
from nightwatch.project_isolation import (
    ProjectConfig, ProjectRegistry, discover_projects,
    get_project_root, validate_project_path, run_in_project,
)
from nightwatch.context_budget import ContextBudget, query_server_context_size
from nightwatch.paths import REPO_ROOT


STATE_DIR = Path.home() / ".local/state/jarvis/nightwatch"
PROGRESS_LOG = STATE_DIR / "progress.jsonl"


# ═══════════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class HarnessConfig:
    """Configuration for the harness."""
    project: str = "nixos-ai"
    max_tasks: int = 10
    max_minutes: int = 180
    max_retries: int = 3
    auto_approve: bool = True
    run_tests: bool = True
    run_imports: bool = True
    auto_review: bool = True
    telegram_notifications: bool = True
    use_llm_discovery: bool = True
    use_scripted_discovery: bool = True
    dry_run: bool = False
    # Multi-project
    projects: list[str] = field(default_factory=list)  # empty = auto-discover
    project_switch_interval: int = 5  # switch project every N tasks
    # Context budget (0 = auto-detect from llama.cpp /props endpoint)
    context_budget: int = 0
    compaction_threshold: float = 0.7
    # Anti-loop detection
    loop_max_attempts: int = 3
    loop_window_seconds: float = 300.0
    # Task timeout (seconds) — tasks running longer are killed
    task_timeout: int = 600  # 10 minutes


@dataclass
class HarnessResult:
    """Result of a harness run."""
    tasks_completed: int = 0
    tasks_failed: int = 0
    tasks_blocked: int = 0
    tasks_skipped: int = 0
    files_changed: list[str] = field(default_factory=list)
    commits: list[str] = field(default_factory=list)
    duration_seconds: float = 0.0
    errors: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return self.tasks_completed + self.tasks_failed + self.tasks_blocked

    @property
    def success_rate(self) -> float:
        return self.tasks_completed / self.total if self.total > 0 else 0.0


# ═══════════════════════════════════════════════════════════════════════════════
# LLM Interface
# ═══════════════════════════════════════════════════════════════════════════════

def _default_call_llm(prompt: str, max_tokens: int = 2048) -> str:
    """Call the local LLM via the unified provider LLMClient.

    Uses jarvis.providers.llm which supports multiple backends
    (llama-cpp, prismml, bonsai) via the LLMBackend abstraction.

    Disables thinking tokens for coding tasks to prevent
    reasoning from consuming the entire max_tokens budget.
    """
    try:
        from jarvis.providers.llm import LLMClient
        from jarvis.core.config import Config
        client = LLMClient(Config())
        messages = [
            {"role": "system", "content": "You are a code improvement assistant. "
             "Follow the format instructions exactly. Return structured patches as requested."},
            {"role": "user", "content": prompt},
        ]
        response = client.chat_with_tools(
            messages=messages,
            max_tokens=max_tokens,
            temperature=0.3,
            extra={"chat_template_kwargs": {"enable_thinking": False}},
        )
        content = response.content or ""
        # Some backends put response in tool_calls when structured; check content
        if not content.strip() and response.tool_calls:
            # Tool calls present — stringify them
            import json
            content = json.dumps(response.tool_calls, indent=2)
        return content or "ERROR: empty response from LLM"
    except Exception as e:
        return f"ERROR: {e}"


def _default_send_telegram(message: str) -> bool:
    """Delegate to canonical telegram provider.

    The old implementation read /etc/jarvis-telegram.env directly and failed
    silently. This delegates to jarvis.providers.telegram.send_notification()
    which is tested and used by heal.py.
    """
    try:
        from jarvis.providers.telegram import send_notification
        ok = send_notification(message)
        if not ok:
            print("[nightwatch] Telegram configured but send failed — check bot token")
        return ok
    except Exception as e:
        print(f"[nightwatch] Telegram unavailable: {e}")
        return False


# ═══════════════════════════════════════════════════════════════════════════════
# Task Discovery
# ═══════════════════════════════════════════════════════════════════════════════

def _discover_scripted_tasks() -> list[Task]:
    """Discover tasks from the category registry (security scanner, TODO finder, etc.)."""
    try:
        from nightwatch.categories import CATEGORY_REGISTRY, SEVERITY_ORDER
    except ImportError:
        return []

    tasks = []
    for cat_name, cat_fn in CATEGORY_REGISTRY.items():
        try:
            scripted_tasks = cat_fn()
            for st in scripted_tasks:
                # Convert categories.Task → task_queue.Task
                tasks.append(Task(
                    id=st.id,
                    project="nixos-ai",
                    description=st.description,
                    target_files=[st.target_path] if st.target_path else [],
                    acceptance_criteria="",
                    priority=SEVERITY_ORDER.get(st.severity, 5),
                    risk="low" if st.severity in ("info", "low") else "medium",
                    status=TaskStatus.READY.value,
                ))
        except Exception:
            pass
    return tasks


def _discover_llm_tasks(call_llm_fn: Callable, project: str = "nixos-ai") -> list[Task]:
    """Use the LLM to discover improvement tasks in the codebase.
    
    Enhanced version that uses workspace context and RAG for better discovery.
    Uses project root (not REPO_ROOT) for external projects.
    """
    # Get project root for file discovery
    import os
    env_root = os.environ.get("JARVIS_PROJECT_ROOT")
    project_root = Path(env_root) if env_root and Path(env_root).exists() else REPO_ROOT
    
    # Get codebase overview
    try:
        result = subprocess.run(
            ["find", str(project_root), "-name", "*.py", "-type", "f",
             "-not", "-path", "*/__pycache__/*", "-not", "-path", "*/node_modules/*"],
            capture_output=True, text=True, timeout=10,
        )
        files = result.stdout.strip().split("\n")[:20]
    except Exception:
        files = []

    # Get workspace context if available
    workspace_context = ""
    try:
        from jarvis.core.workspace import WorkspaceDiscovery
        ws = WorkspaceDiscovery()
        ws.discover()
        if project in ws._projects:
            ctx = ws.get_project_context(project)
            workspace_context = f"\nProject: {project}\nType: {ctx.get('manifest', {}).get('type', 'unknown')}\nFiles: {ctx.get('file_count', 0)}\nLines: {ctx.get('total_lines', 0)}\n"
    except Exception:
        pass

    # Get recent git changes for context (use project root)
    git_context = ""
    try:
        result = subprocess.run(
            ["git", "log", "--oneline", "-10"],
            capture_output=True, text=True, timeout=5,
            cwd=str(project_root),
        )
        if result.stdout.strip():
            git_context = f"\nRecent changes:\n{result.stdout.strip()}\n"
    except Exception:
        pass

    prompt = f"""Analyze this Python codebase and identify 3-5 improvement tasks.

{workspace_context}{git_context}
Key files:
{chr(10).join(files[:15])}

For each task provide JSON:
{{
  "description": "what to do",
  "target_files": ["file.py"],
  "acceptance_criteria": "how to verify",
  "priority": 1-10,
  "risk": "low/medium/high",
  "persona": "which persona should handle this"
}}

Focus on: error handling, code quality, security, missing tests, documentation, performance.
Prioritize tasks that improve reliability and reduce technical debt.
Return JSON array."""

    # Call LLM with timeout protection
    import concurrent.futures
    response = ""
    try:
        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(call_llm_fn, prompt, 1500)
            response = future.result(timeout=120)  # 2 min max for discovery
    except concurrent.futures.TimeoutError:
        print("[discovery] LLM timeout — skipping LLM discovery", file=sys.stderr)
        return []
    except Exception as e:
        print(f"[discovery] LLM error: {e}", file=sys.stderr)
        return []

    tasks = []
    try:
        start = response.find("[")
        end = response.rfind("]") + 1
        if start >= 0 and end > start:
            items = json.loads(response[start:end])
            for i, item in enumerate(items):
                # LLM may return strings or dicts
                if isinstance(item, str):
                    tasks.append(Task(
                        id=f"disc-{int(time.time())}-{i}",
                        project=project,
                        description=item,
                        priority=5,
                        risk="low",
                        status=TaskStatus.READY.value,
                    ))
                elif isinstance(item, dict):
                    tasks.append(Task(
                        id=f"disc-{int(time.time())}-{i}",
                        project=project,
                        description=item.get("description", ""),
                        target_files=item.get("target_files", []),
                        acceptance_criteria=item.get("acceptance_criteria", ""),
                        priority=item.get("priority", 5),
                        risk=item.get("risk", "low"),
                        status=TaskStatus.READY.value,
                    ))
    except (json.JSONDecodeError, ValueError):
        pass

    return tasks


# ═══════════════════════════════════════════════════════════════════════════════
# File Editing (via Patcher + SafeEditor)
# ═══════════════════════════════════════════════════════════════════════════════

def _read_file_for_llm(path: str, max_chars: int = 0, task_description: str = "") -> str:
    """Read a file for LLM context, with path resolution.

    Args:
        path: File path (absolute or relative to project root)
        max_chars: Max chars to read (0 = auto-detect from context budget)
        task_description: Used to extract relevant section for large files
    """
    try:
        if path.startswith("/"):
            full_path = Path(path)
        else:
            full_path = _resolve_file_path(path)

        if not full_path.exists():
            return f"ERROR: File not found: {path}"

        content = full_path.read_text(encoding="utf-8")

        # Auto-detect truncation from context budget if not specified
        if max_chars <= 0:
            # llama-server -c 4096 means ~4K tokens total.
            # Prompt overhead (system + format instructions): ~600 tokens ≈ 2400 chars.
            # Response reserve: ~500 tokens ≈ 2000 chars.
            # Safe budget for file content: ~2900 tokens ≈ 11500 chars.
            # Aider sends whole file for small files, relevant section for large.
            max_chars = 11000

        if len(content) > max_chars:
            # For large files, try to extract the section around the target function.
            # This is what Aider does — send relevant context, not the whole file.
            content = _extract_relevant_section(content, path, max_chars, task_description)

        return content
    except Exception as e:
        return f"ERROR: Could not read {path}: {e}"


def _extract_relevant_section(content: str, path: str, max_chars: int, task_description: str = "") -> str:
    """Extract the most relevant section of a large file.
    
    Strategy: send only imports + the function being edited + immediate context.
    For 'add new function' tasks, send imports + end of file.
    Falls back to first max_chars if no structure found.
    """
    lines = content.split('\n')
    
    # Find imports (first ~20 lines that start with import/from/#)
    import_end = 0
    for i, line in enumerate(lines[:30]):
        stripped = line.strip()
        if stripped.startswith('import ') or stripped.startswith('from ') or stripped.startswith('#') or stripped == '':
            import_end = i + 1
        else:
            break
    imports = '\n'.join(lines[:import_end]) if import_end > 0 else '\n'.join(lines[:10])
    
    # Find function/class definitions with their line numbers
    definitions = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if stripped.startswith('def ') or stripped.startswith('class '):
            definitions.append((i, stripped[:60]))
    
    if not definitions:
        return content[:max_chars]
    
    # Try to find the function mentioned in the task description
    task_lower = task_description.lower()
    target_section = ""
    
    for i, (def_line, def_text) in enumerate(definitions):
        fname = def_text.split('(')[0].split(':')[0].replace('def ', '').replace('class ', '').strip()
        if fname and fname.lower() in task_lower:
            # Found the target function — send just this function
            end_line = definitions[i+1][0] if i+1 < len(definitions) else len(lines)
            target_section = '\n'.join(lines[def_line:end_line])
            break
    
    # If task mentions adding something new (not editing existing),
    # send imports + last function + the function it calls (if any)
    if not target_section:
        last_def = definitions[-1]
        end_line = len(lines)
        target_section = '\n'.join(lines[last_def[0]:end_line])
        # Also include the 'correct' function if mentioned in task
        if 'correct' in task_lower:
            for i, (def_line, def_text) in enumerate(definitions):
                if 'correct' in def_text and i < len(definitions) - 1:
                    correct_end = definitions[i+1][0]
                    correct_section = '\n'.join(lines[def_line:correct_end])
                    target_section = correct_section + '\n\n# ... [later code] ...\n\n' + target_section
                    break
    
    # Budget: imports + target function, fit within max_chars
    budget_per_part = max_chars // 2
    imports = imports[:budget_per_part]
    target_section = target_section[:budget_per_part]
    
    result = f"{imports}\n\n# ... [file middle omitted] ...\n\n{target_section}"
    return result[:max_chars]


def _get_project_root() -> Path:
    """Get the active project root, preferring JARVIS_PROJECT_ROOT env var."""
    import os
    env_root = os.environ.get("JARVIS_PROJECT_ROOT")
    if env_root and Path(env_root).exists():
        return Path(env_root)
    return REPO_ROOT


def _resolve_file_path(path: str) -> Path:
    """Resolve a file path to an absolute path.

    Tries multiple strategies:
    1. Absolute path as-is
    2. Relative to project root (JARVIS_PROJECT_ROOT or REPO_ROOT)
    3. With common source prefixes stripped
    4. Glob search in project
    """
    project_root = _get_project_root()

    if path.startswith("/"):
        return Path(path)

    # Try direct relative to project root
    direct = project_root / path
    if direct.exists():
        return direct

    # Try with common prefixes stripped
    for prefix in ["modules/ai/jarvis/src/", "src/jarvis/", "jarvis/", "src/"]:
        if path.startswith(prefix):
            stripped = path[len(prefix):]
            for base in [project_root / "modules/ai/jarvis/src", project_root]:
                candidate = base / stripped
                if candidate.exists():
                    return candidate

    # Fallback: search in project
    import subprocess
    try:
        result = subprocess.run(
            ["find", str(project_root), "-name", Path(path).name, "-type", "f"],
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.strip().split("\n"):
            if line and Path(line).exists():
                return Path(line)
    except Exception:
        pass

    return project_root / path  # Return best guess


def _request_structured_patch(
    task_description: str,
    target_files: list[str],
    call_llm_fn: Callable,
    previous_errors: list[str] | None = None,
) -> tuple[bool, list, list[str]]:
    """Request structured patches from the LLM (old_text → new_text).

    Returns (success, list[FilePatch], errors).
    This is the SAFE path — LLM returns hunks, not full files.

    If previous_errors is provided (from a prior failed attempt), the errors
    are injected into the prompt so the LLM can learn from its mistakes
    instead of repeating them. This is the critical feedback loop that
    prevents infinite retry loops.
    """
    from nightwatch.patcher import parse_llm_patch, FilePatch

    # Read target files (full content for context, but LLM returns patches)
    file_contents = {}
    missing_files = []
    for path in target_files:
        content = _read_file_for_llm(path, task_description=task_description)
        if content.startswith("ERROR"):
            # File doesn't exist — treat as CREATE candidate
            missing_files.append(path)
        else:
            file_contents[path] = content

    if not file_contents and not missing_files:
        return False, [], ["No readable target files"]

    files_section = "\n\n".join(
        f"=== FILE: {path} ===\n```\n{content}\n```"
        for path, content in file_contents.items()
    )
    # Tell LLM about missing files (candidates for CREATE)
    if missing_files:
        files_section += "\n\nFILES THAT DO NOT EXIST (create them):\n"
        files_section += "\n".join(f"  - {p}" for p in missing_files)

    # Inject recovery context if available
    recovery_ctx = ""
    try:
        from nightwatch.checkpoint import generate_recovery_summary
        import os
        _proj = os.environ.get("JARVIS_PROJECT_ROOT", "nixos-ai")
        _proj_name = os.path.basename(_proj) if _proj else "nixos-ai"
        recovery_ctx = generate_recovery_summary(project=_proj_name)
    except Exception:
        pass

    # Inject episodic memory lessons from past failures
    memory_ctx = ""
    try:
        from nightwatch.memory_bridge import recall_relevant_lessons
        lessons = recall_relevant_lessons(task_description, top_k=3)
        if lessons:
            memory_ctx = "\n\nLESSONS FROM PAST FAILURES:\n"
            for i, lesson in enumerate(lessons, 1):
                memory_ctx += f"  {i}. {lesson['error_pattern'][:200]}\n"
                if lesson.get('fix'):
                    memory_ctx += f"     Fix: {lesson['fix'][:200]}\n"
    except Exception:
        pass

    error_section = ""
    if previous_errors:
        error_section = (
            "\n\n⚠️ PREVIOUS ATTEMPT FAILED — DO NOT REPEAT THESE ERRORS:\n"
            + "\n".join(f"  - {e[:300]}" for e in previous_errors[-3:])
            + "\n\nAnalyze why the previous patches failed and produce corrected patches."
        )

    total_chars = sum(len(c) for c in file_contents.values())
    use_whole = 0 < total_chars < 6000 and len(file_contents) <= 3

    if use_whole:
        format_block = """To MODIFY a file, return its COMPLETE new content:
=== WHOLE: path/to/file.py ===
REASON: why this change is needed
--- content ---
complete updated file content here
--- end ---

To CREATE a new file, use:
=== CREATE: path/to/new_file.py ===
REASON: why this file is needed
--- content ---
full file content here
--- end ---

RULES:
- Return the COMPLETE file content, not just the changed part
- Preserve everything you are not changing, byte for byte
- Return only files that need changes. If no changes needed, return "NO_CHANGES"."""
    else:
        format_block = """To MODIFY an existing file, use:
=== FILE: path/to/file.py ===
REASON: why this change is needed
--- old text ---
exact text to find (must match exactly)
--- new text ---
replacement text
--- end ---

To CREATE a new file, use:
=== CREATE: path/to/new_file.py ===
REASON: why this file is needed
--- content ---
full file content here
--- end ---

RULES:
- old text MUST be an exact substring of the file
- To CREATE: use --- content --- with the full file content
- You can have multiple hunks per file
- Return only files that need changes. If no changes needed, return "NO_CHANGES"."""

    prompt = f"""Improve this code for the given task.

{recovery_ctx + chr(10) + chr(10) if recovery_ctx else ""}{memory_ctx + chr(10) if memory_ctx else ""}{error_section}TASK: {task_description}

FILES:
{files_section}

{"\n\n⚠️ The following files DO NOT EXIST yet. The task requires creating them.\nYou MUST use the CREATE format below for these files.\n" + chr(10).join(f"  - {p}" for p in missing_files) + chr(10) if missing_files else ""}
{format_block}"""

    response = call_llm_fn(prompt, 4096)

    if "ERROR" in response:
        return False, [], [response]

    if "NO_CHANGES" in response:
        # If files need creating, retry with a dedicated create prompt
        if missing_files:
            return _request_file_creation(task_description, missing_files, call_llm_fn)
        return True, [], []

    # Parse structured patches
    patches = parse_llm_patch(response)

    if not patches:
        try:
            from pathlib import Path as _Path
            dbg = _Path.home() / ".local/state/jarvis/nightwatch/last_patch_failure.txt"
            dbg.parent.mkdir(parents=True, exist_ok=True)
            dbg.write_text(response[:4000], encoding="utf-8")
        except Exception:
            pass
        return False, [], ["Could not parse any patches from LLM response"]

    return True, patches, []


def _request_file_creation(
    task_description: str,
    missing_files: list[str],
    call_llm_fn: Callable,
) -> tuple[bool, list, list[str]]:
    """Dedicated prompt for file creation when the main prompt returns NO_CHANGES.
    
    Uses a simpler, more direct prompt that the Qwen model can follow.
    """
    from nightwatch.patcher import parse_llm_patch, FilePatch

    files_list = "\n".join(f"  - {f}" for f in missing_files)
    prompt = f"""You must create the following files for this task:

TASK: {task_description}

FILES TO CREATE:
{files_list}

For EACH file, return:
=== CREATE: path/to/file.py ===
REASON: why this file is needed
--- content ---
full file content here
--- end ---

IMPORTANT: You MUST create these files. Return the full content for each file.
Do NOT return NO_CHANGES. The files do not exist yet."""

    response = call_llm_fn(prompt, 4096)

    if "ERROR" in response:
        return False, [], [response]

    if "NO_CHANGES" in response:
        return False, [], [f"LLM still returned NO_CHANGES for file creation of: {', '.join(missing_files)}"]

    patches = parse_llm_patch(response)
    if not patches:
        return False, [], ["Could not parse file creation patches from LLM response"]

    # Mark all patches as CREATE
    for p in patches:
        p.create = True

    return True, patches, []


# ═══════════════════════════════════════════════════════════════════════════════
# Git Operations
# ═══════════════════════════════════════════════════════════════════════════════

def _git_diff_stat() -> str:
    """Get git diff stat."""
    try:
        result = subprocess.run(
            ["git", "diff", "--stat"],
            capture_output=True, text=True, timeout=10,
            cwd=str(REPO_ROOT),
        )
        return result.stdout
    except Exception:
        return ""


def _git_commit(message: str) -> str | None:
    """Commit changes and return SHA."""
    try:
        subprocess.run(
            ["git", "add", "-A"],
            capture_output=True, timeout=10,
            cwd=str(REPO_ROOT),
        )
        result = subprocess.run(
            ["git", "commit", "-m", message],
            capture_output=True, text=True, timeout=30,
            cwd=str(REPO_ROOT),
        )
        if result.returncode == 0:
            sha = subprocess.run(
                ["git", "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=str(REPO_ROOT),
            ).stdout.strip()
            return sha
    except Exception:
        pass
    return None


def _git_revert(files: list[str] | None = None) -> None:
    """Revert uncommitted changes.

    If files is provided, only revert those specific files.
    If files is None, revert ALL changes (dangerous — use with caution).
    """
    try:
        if files:
            # Revert only specific files
            for f in files:
                resolved = _resolve_file_path(f)
                if resolved.exists():
                    subprocess.run(
                        ["git", "checkout", "--", str(resolved)],
                        capture_output=True, timeout=10,
                        cwd=str(REPO_ROOT),
                    )
        else:
            # Full revert — last resort
            subprocess.run(
                ["git", "checkout", "--", "."],
                capture_output=True, timeout=10,
                cwd=str(REPO_ROOT),
            )
            subprocess.run(
                ["git", "clean", "-fd"],
                capture_output=True, timeout=10,
                cwd=str(REPO_ROOT),
            )
    except Exception:
        pass


# ═══════════════════════════════════════════════════════════════════════════════
# Progress Logging
# ═══════════════════════════════════════════════════════════════════════════════

def _log_progress(entry: dict) -> None:
    """Append a progress entry to the JSONL log."""
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(PROGRESS_LOG, "a") as f:
        f.write(json.dumps(entry, ensure_ascii=False) + "\n")


# ═══════════════════════════════════════════════════════════════════════════════
# Harness
# ═══════════════════════════════════════════════════════════════════════════════

class Harness:
    """Main harness orchestrator.

    Single entrypoint for all nightwatch operations.
    Integrates: TaskQueue, SafeEditor, Validator, Evaluator, Checkpoint, Safety.
    """

    def __init__(
        self,
        config: HarnessConfig | None = None,
        call_llm: Callable[[str, int], str] | None = None,
        send_telegram: Callable[[str], bool] | None = None,
    ):
        self.config = config or HarnessConfig()
        self.call_llm = call_llm or _default_call_llm
        self.send_telegram = send_telegram or _default_send_telegram
        self.queue = TaskQueue(project=self.config.project)
        self.editor = SafeEditor()
        self.checkpoint = Checkpoint.load(project=self.config.project)
        self.mission = self.queue.mission
        self.project_registry = ProjectRegistry()
        self.loop_detector = LoopDetector(
            max_attempts=self.config.loop_max_attempts,
            window_seconds=self.config.loop_window_seconds,
            project=self.config.project,
        )
        # Event Bus — use global bus so Control Plane receives harness events
        from jarvis.core.eventbus import get_bus
        self._bus = get_bus()
        self._bus.subscribe("harness.notify", self._handle_bus_notify, name="telegram")
        self._bus.subscribe("harness.task", self._handle_bus_log, name="jsonl_logger")
        # Auto-detect context size from llama.cpp server if not specified
        budget = self.config.context_budget
        if budget <= 0:
            server_ctx = query_server_context_size()
            if server_ctx > 0:
                budget = server_ctx
                self.notify(f"📊 Context: {budget:,} tokens (from server)")
            else:
                budget = 8192
                self.notify(f"⚠️ Context: {budget:,} tokens (server unavailable, fallback)")
        self.context_budget = ContextBudget(
            max_tokens=budget,
            compaction_threshold=self.config.compaction_threshold,
        )
        # Auto-discover projects if none specified
        if not self.config.projects:
            self._discover_projects()
        # Auto-cleanup: prune terminal tasks and recover stuck tasks
        # This makes the queue self-managing for autonomous operation.
        pruned_terminals = self.queue.prune_completed(keep_last=20)
        if pruned_terminals > 0:
            self.notify(f"🧹 Pruned {pruned_terminals} old terminal tasks")
        pruned_stale = self.queue.prune_stale(max_age_seconds=3600)
        if pruned_stale > 0:
            self.notify(f"🧹 Pruned {pruned_stale} stale tasks from previous runs")
        recovered = self.queue.recover_stuck_tasks()
        if recovered > 0:
            self.notify(f"♻️ Recovered {recovered} stuck tasks")
        # Sweep leftover nightwatch/* branches from a crashed/killed prior run
        # Pass project root so external project branches are also cleaned
        project_root = _get_project_root()
        pruned = safety.prune_orphan_branches(project_root)
        if pruned > 0:
            self.notify(f"🧹 Pruned {pruned} orphaned nightwatch branches")
        # Sync past failures to episodic memory for future learning
        try:
            from nightwatch.memory_bridge import sync_to_episodic_memory
            sync_result = sync_to_episodic_memory(project=self.config.project, limit=50)
            if sync_result.get('synced', 0) > 0:
                self.notify(f"🧠 Synced {sync_result['synced']} lessons to episodic memory")
        except Exception:
            pass

    # ── Task Failure (with persistence) ───────────────────────────────────

    def _fail_task(self, task: Task, error: str) -> None:
        """Fail a task and persist the state immediately.
        
        This ensures the attempt count and status are saved to disk
        even if the harness crashes before the next _save() call.
        
        Also implements the 'rules ratchet': every failure becomes a rule
        that prevents the same mistake in future sessions.
        """
        task.fail(error)
        self.queue.update_task(
            task.id,
            status=task.status,
            attempts=task.attempts,
            last_error=task.last_error,
        )
        # Rules ratchet: persist failure as a rule for future sessions
        self._record_failure_rule(task, error)

    def _record_failure_rule(self, task: Task, error: str) -> None:
        """Record a failure as a rule for future sessions (rules ratchet).
        
        Every mistake becomes a permanent signal. Rules are stored in
        AGENTS.md so future sessions read them as constraints.
        """
        import os
        project_root = os.environ.get('JARVIS_PROJECT_ROOT', str(REPO_ROOT))
        agents_file = os.path.join(project_root, 'AGENTS.md')
        
        # Classify the failure type
        error_lower = error.lower()
        rule = None
        if 'hunk not found' in error_lower or 'could not parse' in error_lower:
            rule = f"- When patching files, the old_text must be an EXACT substring of the file content. Read the file first, then use the exact text."
        elif 'syntax error' in error_lower:
            rule = f"- After generating code, verify it has no syntax errors before returning. Use python -c 'compile()' to check."
        elif 'validation failed' in error_lower:
            rule = f"- Always run validation checks on generated code before returning it."
        elif 'review failed' in error_lower:
            rule = f"- The independent reviewer checks acceptance criteria. Ensure your changes actually meet the stated requirements."
        elif 'no changes' in error_lower:
            rule = f"- If the task requires creating a new file, use the CREATE format. If modifying, the old_text must match existing content."
        
        if rule:
            try:
                # Read existing rules
                existing = ""
                if os.path.exists(agents_file):
                    with open(agents_file, 'r') as f:
                        existing = f.read()
                
                # Don't duplicate rules
                if rule not in existing:
                    # Append rule under a '## Harness Rules' section
                    if '## Harness Rules' not in existing:
                        existing += f"\n\n## Harness Rules\n\nThese rules were automatically generated from failures. Do not edit manually.\n"
                    with open(agents_file, 'a') as f:
                        f.write(f"{rule}\n")
                    self.notify(f"📏 Rule added: {rule[:60]}...")
            except Exception:
                pass  # Don't fail the task just because rule recording failed

    # ── Notifications ──────────────────────────────────────────────────────

    def notify(self, message: str) -> None:
        """Send notification via Event Bus."""
        self._bus.publish("harness.notify", {"message": message})

    def _handle_bus_notify(self, event: Event) -> None:
        """Handle notify events — delegates to Telegram."""
        if self.config.telegram_notifications:
            self.send_telegram(event.data.get("message", ""))

    def _handle_bus_log(self, event: Event) -> None:
        """Handle task lifecycle events — logs to JSONL."""
        entry = {"ts": event.ts, "event": event.topic, **event.data}
        _log_progress(entry)

    def _emit(self, topic: str, **data: object) -> None:
        """Emit a lifecycle event through the Event Bus."""
        self._bus.publish("harness.task", {"event_type": topic, **data})

    # ── Task Discovery ─────────────────────────────────────────────────────

    def _discover_projects(self) -> None:
        """Auto-discover projects in the workspace."""
        try:
            projects = discover_projects()
            for proj in projects:
                self.project_registry.register(proj)
                if proj.name not in self.config.projects:
                    self.config.projects.append(proj.name)
        except Exception:
            # Fallback: just use the configured project
            if self.config.project not in self.config.projects:
                self.config.projects.append(self.config.project)
    
    def discover_tasks(self, project: str | None = None) -> list[Task]:
        """Discover tasks from all enabled sources.
        
        If project is specified, only discover tasks for that project.
        Otherwise, discover across all configured projects.
        
        Uses platform bridge for workspace-aware discovery when available.
        """
        tasks = []
        projects = [project] if project else self.config.projects

        # Platform-aware discovery: use workspace module if available
        try:
            from nightwatch.platform_bridge import discover_projects_for_nightwatch
            ws_projects = discover_projects_for_nightwatch()
            if ws_projects:
                # Update config with discovered projects
                for proj in ws_projects:
                    if proj["name"] not in self.config.projects:
                        self.config.projects.append(proj["name"])
                        self.notify(f"🏗️ Discovered project: {proj['name']}")
        except Exception:
            pass

        for proj_name in projects:
            # Scripted discovery (per-project if project has a root)
            if self.config.use_scripted_discovery:
                tasks.extend(_discover_scripted_tasks())
            
            # LLM discovery (per-project)
            if self.config.use_llm_discovery:
                tasks.extend(_discover_llm_tasks(self.call_llm, proj_name))

        # Platform-aware persona selection for each task
        try:
            from nightwatch.platform_bridge import select_persona_for_task
            for task in tasks:
                persona = select_persona_for_task(task.description)
                if persona and persona.get("id"):
                    task.persona = persona["id"]
        except Exception:
            pass
        
        # Deduplicate by description
        seen = set()
        unique = []
        for t in tasks:
            key = f"{t.project}:{t.description[:80]}"
            if key not in seen:
                seen.add(key)
                unique.append(t)
        
        return unique

    # ── Task Execution ─────────────────────────────────────────────────────

    def execute_task(self, task: Task) -> bool:
        """Execute a single task through the full pipeline.

        Pipeline:
            1. Checkpoint (save state)
            2. Request patch from LLM
            3. Apply via SafeEditor (atomic, validated)
            4. Validate (syntax, imports, tests)
            5. Review (independent)
            6. Commit (only if all pass)
            7. Learn (persist to AGENTS.md)
        """
        task_start = time.time()

        # Timeout check: skip tasks that have been running too long
        task_age = task_start - task.created_at
        if task_age > self.config.task_timeout:
            self._fail_task(task, f"Task timeout: running for {task_age:.0f}s (limit: {self.config.task_timeout}s)")
            self.notify(f"⏰ *Task Timeout*\n{task.description[:50]}")
            return False

        # Global pause gate: any IDE/CLI/AI (or the watchdog on memory
        # pressure) can defer autonomous work via the PAUSED flag file.
        # Deferred, not failed — no attempts consumed.
        from nightwatch.pause import is_paused
        _paused, _why = is_paused()
        if _paused:
            task.skip(f"paused: {_why}")
            self.notify(f"⏸️ *Task Paused*\n{task.description[:80]}\n{_why}")
            self._emit("task_paused", task_id=task.id, reason=_why)
            return False

        # Create checkpoint
        cp = create_checkpoint_for_task(task.id, task.description, self.config.project)

        # Notify start
        self.notify(f"🔄 *Task Started*\n{task.description[:100]}")
        self._emit("task_started", task_id=task.id, description=task.description[:100])

        # Check protected paths
        for f in task.target_files:
            if safety.is_path_protected(f):
                task.block(f"Protected path: {f}")
                self.notify(f"🚫 *Task Blocked*\nProtected path: {f}")
                return False

        # Mark in progress
        self.queue.update_task(task.id, status=TaskStatus.IN_PROGRESS.value)

        # Dry run
        if self.config.dry_run:
            self.notify(f"🔍 *Dry Run*\n{task.description[:80]}")
            task.skip("dry-run")
            return False

        branch: str | None = None
        try:
            with project_isolation.use_project_root(project_isolation.resolve_project_root(task.project)):
                # ── Step 0a: Isolate on a task branch ──
                # Every commit for this task happens here, never on main
                # directly. abort_task_branch() on any failure path below
                # discards this branch entirely — main is never touched
                # until the merge at the very end.
                branch = safety.create_task_branch(task.id, task.project)
                if not branch:
                    self._fail_task(task, "Could not create isolated branch (git checkout -b failed)")
                    self.notify(f"🚫 *Task Blocked*\nBranch isolation failed for {task.id}")
                    return False

                # ── Step 0b: Context budget check ──
                try:
                    stats = self.context_budget.get_stats()
                    if stats.get("should_compact", False):
                        cp.record_compaction(
                            stats.get("tokens_estimated", 0),
                            stats.get("tokens_estimated", 0) // 2,
                            "auto-compact before LLM call"
                        )
                        self.notify("🗜️ Context compaction triggered")
                except Exception:
                    pass

                # ── Retry loop: patch → apply → validate → review ──
                # On validation/review failure, feed error context back to LLM
                # so it can learn from its mistakes instead of repeating them.
                previous_errors: list[str] = []
                max_attempts = max(self.config.max_retries, 1)

                for attempt in range(max_attempts):
                    if attempt > 0:
                        safety.abort_task_branch(branch)
                        branch = safety.create_task_branch(task.id, task.project)
                        if not branch:
                            self._fail_task(task, f"Could not create branch for retry {attempt}")
                            return False
                        # Reset state so the pipeline can re-enter cleanly
                        self.queue.update_task(task.id, status=TaskStatus.IN_PROGRESS.value)
                        self.notify(f"🔁 Retry {attempt + 1}/{max_attempts} with error context")

                    # ── Step 1: Request structured patches from LLM ──
                    success, patches, errors = _request_structured_patch(
                        task_description=task.description,
                        target_files=task.target_files,
                        call_llm_fn=self.call_llm,
                        previous_errors=previous_errors if previous_errors else None,
                    )

                    cp.record_operation("patch", success, "; ".join(errors) if errors else "")

                    if not success:
                        previous_errors.extend(errors)
                        if attempt < max_attempts - 1:
                            self.notify(f"⚠️ Patch failed (attempt {attempt + 1}), retrying with error context")
                            continue
                        safety.abort_task_branch(branch)
                        self._fail_task(task, "; ".join(errors))
                        self.notify(f"❌ *Patch Failed*\n{errors[0][:100] if errors else 'unknown'}")
                        _log_progress({
                            "task_id": task.id, "status": "patch_failed",
                            "error": errors[0] if errors else "unknown",
                        })
                        return False

                    if not patches:
                        # LLM decided no changes needed — discard the empty
                        # branch instead of leaving it orphaned
                        safety.abort_task_branch(branch)
                        task.skip("no_changes_needed")
                        self.notify(f"⏭️ *No Changes*\n{task.description[:50]}")
                        return False

                    # ── Step 2: Apply structured patches via Patcher + SafeEditor ──
                    self.queue.update_task(task.id, status=TaskStatus.VALIDATING.value)
                    applied_files = []
                    apply_errors = []

                    from nightwatch.patcher import apply_patch
                    from nightwatch.safe_editor import strip_markdown_fences

                    for file_patch in patches:
                        # Apply patch hunks to get new content
                        patch_ok, patched_content, patch_diff = apply_patch(file_patch)

                        if not patch_ok:
                            apply_errors.append(f"Patcher failed for {file_patch.path}: {patched_content}")
                            cp.record_operation(f"patch:{file_patch.path}", False, patched_content)
                            continue

                        # Validate and write via SafeEditor (atomic, validated)
                        resolved = _resolve_file_path(file_patch.path)
                        edit_result: EditResult = self.editor.apply_edit(
                            resolved, patched_content, validate=True
                        )
                        if edit_result.success:
                            applied_files.append(file_patch.path)
                            cp.record_operation(f"write:{file_patch.path}", True)
                        else:
                            apply_errors.extend(edit_result.errors)
                            cp.record_operation(f"write:{file_patch.path}", False, "; ".join(edit_result.errors))

                    if not applied_files:
                        previous_errors.extend(apply_errors)
                        if attempt < max_attempts - 1:
                            self.notify(f"⚠️ Write failed (attempt {attempt + 1}), retrying")
                            continue
                        safety.abort_task_branch(branch)
                        self._fail_task(task, f"All patches failed: {'; '.join(apply_errors)}")
                        self.notify(f"❌ *Write Failed*\n{apply_errors[0][:100] if apply_errors else 'rejected'}")
                        _log_progress({
                            "task_id": task.id, "status": "write_failed",
                            "errors": apply_errors,
                        })
                        return False

                    # ── Step 3: Validate ──
                    validation = validate_change(
                        applied_files,
                        run_tests=self.config.run_tests,
                        run_imports=self.config.run_imports,
                    )

                    cp.record_operation("validate", validation.passed, validation.summary)

                    if not validation.passed:
                        previous_errors.append(f"Validation failed: {validation.summary}")
                        if attempt < max_attempts - 1:
                            self.notify(f"⚠️ Validation failed (attempt {attempt + 1}), retrying with error context")
                            continue
                        safety.abort_task_branch(branch)
                        self._fail_task(task, f"Validation failed: {validation.summary}")
                        self.notify(f"❌ *Validation Failed*\n{validation.summary}")
                        _log_progress({
                            "task_id": task.id, "status": "validation_failed",
                            "summary": validation.summary,
                        })
                        return False

                    # ── Step 4: Independent review ──
                    # Skip LLM review for low-risk tasks that pass validation.
                    # This saves ~30-60s per task (1 LLM call eliminated).
                    # High-risk tasks and tasks with test failures still get reviewed.
                    skip_review = (
                        self.config.auto_review
                        and task.risk == "low"
                        and validation.passed
                        and not any(s.output for s in validation.steps if s.name == "tests")
                    )
                    if self.config.auto_review and not skip_review:
                        self.queue.update_task(task.id, status=TaskStatus.REVIEW.value)
                        test_output = "\n".join(
                            s.output for s in validation.steps if s.name == "tests"
                        )
                        review = review_change(
                            task_description=task.description,
                            acceptance_criteria=task.acceptance_criteria,
                            test_output=test_output,
                            call_llm_fn=self.call_llm,
                        )

                        if not review.passed:
                            previous_errors.append(f"Review failed: {review.summary}")
                            if attempt < max_attempts - 1:
                                self.notify(f"⚠️ Review failed (attempt {attempt + 1}), retrying with error context")
                                continue
                            safety.abort_task_branch(branch)
                            self._fail_task(task, f"Review failed: {review.summary}")
                            self.notify(f"❌ *Review Failed*\n{review.summary}")
                            _log_progress({
                                "task_id": task.id, "status": "review_skipped",
                                "summary": review.summary,
                            })
                            return False
                    elif skip_review:
                        self.notify("⏭️ *Review Skipped* (low-risk, validation passed)")

                    # All steps passed — break out of retry loop
                    break
                else:
                    # Exhausted all retries
                    safety.abort_task_branch(branch)
                    self._fail_task(task, f"Failed after {max_attempts} attempts: {'; '.join(previous_errors[-2:])}")
                    self.notify(f"❌ *Exhausted Retries*\n{task.description[:50]}")
                    return False

                # ── Step 5: Commit on branch, then merge into main ──
                msg = f"nightwatch({task.project}): {task.description[:80]}"
                branch_commit = _git_commit(msg)
                if not branch_commit:
                    # Validation/review passed but the commit itself failed —
                    # don't leave an unmerged branch behind, don't report
                    # success with no actual commit.
                    safety.abort_task_branch(branch)
                    self._fail_task(task, "git commit failed on task branch after validation passed")
                    self.notify("❌ *Commit Failed*\nValidation passed but git commit did not")
                    _log_progress({"task_id": task.id, "status": "commit_failed"})
                    return False
                commit_sha = safety.merge_task_branch(branch)
                cp.record_operation("commit", commit_sha is not None)

                # ── Step 6: Complete ──
                task.complete(commit_sha)
                self.loop_detector.reset(task.id)  # Clear loop tracking on success
                self.mission.total_tasks_completed += 1
                if commit_sha:
                    self.mission.total_commits += 1

                # Platform observability: log execution stats
                try:
                    from nightwatch.platform_bridge import log_task_execution
                    log_task_execution(
                        task_id=task.id,
                        persona=getattr(task, 'persona', 'unknown'),
                        model_tier=getattr(task, 'model_tier', 'medium'),
                        project=task.project,
                        status="completed",
                        duration_seconds=time.time() - task_start,
                    )
                except Exception:
                    pass

                self.notify(
                    f"✅ *Task Complete*\n{task.description[:50]}\n"
                    f"Commit: {commit_sha[:8] if commit_sha else 'N/A'}"
                )
                self._emit("task_completed", task_id=task.id, commit=commit_sha, files=applied_files)

                _log_progress({
                    "task_id": task.id, "status": "completed",
                    "commit": commit_sha, "files": applied_files,
                })

                return True

        except Exception as e:
            cp.record_operation("error", False, str(e))
            error_msg = str(e)
            failure_type = classify_failure(error_msg, task.status)
            self._fail_task(task, error_msg)
            self.notify(
                f"❌ *Task Error* [{failure_type.value}]\n{error_msg[:100]}"
            )
            self._emit("task_failed", task_id=task.id, error=error_msg[:100], failure_type=failure_type.value)
            _log_progress({
                "task_id": task.id, "status": "error",
                "error": error_msg, "failure_type": failure_type.value,
            })
            # Revert on error — abort the isolated branch, main untouched
            if branch:
                safety.abort_task_branch(branch)
            else:
                _git_revert(applied_files if 'applied_files' in dir() else None)

            # Anti-loop detection
            in_loop = self.loop_detector.record_attempt(task.id, success=False)
            if in_loop:
                task.block(f"Anti-loop: {self.config.loop_max_attempts} failures in {self.config.loop_window_seconds}s")
                self.notify(f"🔄 *Loop Detected* — task {task.id} blocked after {self.config.loop_max_attempts} attempts")
                self._emit("loop_detected", task_id=task.id, attempts=self.loop_detector.get_stats(task.id))
                _log_progress({
                    "task_id": task.id, "status": "loop_detected",
                    "attempts": self.loop_detector.get_stats(task.id),
                })
                return False

            # Retry logic for transient/tool failures
            if failure_type in (FailureType.TRANSIENT, FailureType.TOOL_FAILURE):
                retries = getattr(task, '_retry_count', 0)
                if retries < self.config.max_retries:
                    task._retry_count = retries + 1
                    wait = min(2 ** retries * 5, 60)  # exponential backoff, max 60s
                    self.notify(f"🔁 Retrying in {wait}s (attempt {retries + 1}/{self.config.max_retries})")
                    time.sleep(wait)
                    # Don't count as executed — retry same task
                    return self.execute_task(task)

            return False

    # ── Main Run ───────────────────────────────────────────────────────────

    def run(self) -> HarnessResult:
        """Run the harness.

        Flow:
            1. Check for recovery context
            2. Recover stuck tasks
            3. Discover tasks (scripted + LLM) across projects
            4. Execute tasks through pipeline
            5. Switch projects periodically
            6. Report results
        """
        start = time.time()
        result = HarnessResult()

        self.mission.active = True
        self.mission.started_at = time.time()

        # Prune stale tasks from previous runs (>1h old, still non-terminal)
        pruned = self.queue.prune_stale(max_age_seconds=3600)
        if pruned > 0:
            self.notify(f"🧹 Pruned {pruned} stale tasks from previous runs")

        projects_str = ", ".join(self.config.projects[:3])
        self.notify(f"🌙 *Nightwatch Started*\nProjects: {projects_str}")
        self._emit("run_started", projects=self.config.projects)

        # ── Recovery ──
        recovery = get_recovery_context(project=self.config.project)
        if recovery and recovery.get("task_id"):
            self.notify(f"♻️ *Recovering*: {recovery.get('task_description', '')[:50]}")
            self._emit("recovery", task_id=recovery.get("task_id"), description=recovery.get("task_description", "")[:50])

        # ── Discover across all projects ──
        self.notify("🔍 Discovering tasks...")
        new_tasks = self.discover_tasks()
        for task in new_tasks:
            self.queue.add_task(task)

        self.notify(f"📋 Found {len(new_tasks)} tasks across {len(self.config.projects)} projects")

        # ── Execute ──
        executed = 0
        tasks_since_switch = 0
        current_project_idx = 0

        while executed < self.config.max_tasks:
            if (time.time() - start) > self.config.max_minutes * 60:
                self.notify(f"⏰ Time limit ({self.config.max_minutes} min)")
                break

            task = self.queue.get_next_task()
            if not task:
                # Try discovering more tasks
                if self.config.projects:
                    proj = self.config.projects[current_project_idx % len(self.config.projects)]
                    more = self.discover_tasks(project=proj)
                    for t in more:
                        self.queue.add_task(t)
                    task = self.queue.get_next_task()
                if not task:
                    self.notify("✅ No more tasks")
                    break

            success = self.execute_task(task)

            if success:
                result.tasks_completed += 1
                result.files_changed.extend(task.target_files)
                if task.commit_sha:
                    result.commits.append(task.commit_sha)
                # Update project state
                self.project_registry.update_state(
                    task.project,
                    tasks_completed=self.project_registry.get_state(task.project).tasks_completed + 1
                    if self.project_registry.get_state(task.project) else 1,
                )
            elif task.status == TaskStatus.BLOCKED.value:
                result.tasks_blocked += 1
            elif task.status == TaskStatus.ABANDONED.value:
                result.tasks_skipped += 1
            else:
                result.tasks_failed += 1
                self.project_registry.update_state(
                    task.project,
                    tasks_failed=(self.project_registry.get_state(task.project).tasks_failed + 1
                                  if self.project_registry.get_state(task.project) else 1),
                    last_error=task.last_error or "",
                )

            executed += 1
            tasks_since_switch += 1

            # Switch projects periodically
            if (tasks_since_switch >= self.config.project_switch_interval
                    and len(self.config.projects) > 1):
                current_project_idx = (current_project_idx + 1) % len(self.config.projects)
                tasks_since_switch = 0
                new_proj = self.config.projects[current_project_idx]
                self.notify(f"🔄 Switching to project: {new_proj}")

        # ── Summary ──
        elapsed = time.time() - start
        result.duration_seconds = elapsed

        self.mission.active = False
        self.mission.last_checkpoint = time.time()

        # Per-project stats
        project_stats = []
        for proj_name in self.config.projects:
            stats = self.queue.get_stats(project=proj_name)
            project_stats.append(f"  {proj_name}: {stats['completed']} done, {stats['ready']} ready")

        overall_stats = self.queue.get_stats()
        context_stats = self.context_budget.get_stats()

        summary = f"""🌙 *Nightwatch Complete*

📊 Results:
- Completed: {result.tasks_completed}
- Failed: {result.tasks_failed}
- Blocked: {result.tasks_blocked}
- Skipped: {result.tasks_skipped}
- Files changed: {len(result.files_changed)}
- Commits: {len(result.commits)}
- Duration: {int(elapsed // 60)}m {int(elapsed % 60)}s
- Success rate: {result.success_rate:.0%}

📈 Projects:
{chr(10).join(project_stats)}

🧠 Context:
- LLM calls: {context_stats.get('total_llm_calls', 0)}
- Compactions: {context_stats.get('total_compactions', 0)}
- Tokens processed: {context_stats.get('total_tokens_processed', 0)}"""

        self.notify(summary)

        _log_progress({
            "event": "run_complete",
            "completed": result.tasks_completed,
            "failed": result.tasks_failed,
            "blocked": result.tasks_blocked,
            "commits": len(result.commits),
            "duration_s": elapsed,
            "projects": self.config.projects,
            "context_stats": context_stats,
        })

        return result


# ═══════════════════════════════════════════════════════════════════════════════
# Public API
# ═══════════════════════════════════════════════════════════════════════════════

def run_nightwatch(
    max_tasks: int = 10,
    max_minutes: int = 180,
    report_telegram: bool = False,
    dry_run: bool = False,
    use_llm: bool = True,
    use_scripted: bool = True,
    projects: list[str] | None = None,
    context_budget: int = 0,  # 0 = auto-detect from server
) -> HarnessResult:
    """Convenience function to run nightwatch.

    This replaces both:
    - orchestrator.run_nightwatch()
    - llm_loop.run_llm_nightwatch()
    """
    config = HarnessConfig(
        max_tasks=max_tasks,
        max_minutes=max_minutes,
        telegram_notifications=report_telegram,
        dry_run=dry_run,
        use_llm_discovery=use_llm,
        use_scripted_discovery=use_scripted,
        projects=projects or [],
        context_budget=context_budget,
    )
    harness = Harness(config=config)
    return harness.run()
