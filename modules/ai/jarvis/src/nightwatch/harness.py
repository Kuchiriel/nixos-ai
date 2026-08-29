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
    """Call the local LLM via llama.cpp API."""
    import requests
    url = os.environ.get("LLAMA_CPP_URL", "http://127.0.0.1:8080")
    payload = {
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0.3,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    try:
        resp = requests.post(
            f"{url}/v1/chat/completions",
            json=payload,
            timeout=300,
        )
        resp.raise_for_status()
        data = resp.json()
        msg = data["choices"][0]["message"]
        return msg.get("content", "") or msg.get("reasoning_content", "")
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
    """Use the LLM to discover improvement tasks in the codebase."""
    # Get codebase overview
    try:
        result = subprocess.run(
            ["find", str(REPO_ROOT / "modules/ai/jarvis/src"), "-name", "*.py", "-type", "f"],
            capture_output=True, text=True, timeout=10,
        )
        files = result.stdout.strip().split("\n")[:20]
    except Exception:
        files = []

    prompt = f"""Analyze this Python codebase and identify 3-5 improvement tasks.

Key files:
{chr(10).join(files[:15])}

For each task provide JSON:
{{
  "description": "what to do",
  "target_files": ["file.py"],
  "acceptance_criteria": "how to verify",
  "priority": 1-10,
  "risk": "low/medium/high"
}}

Focus on: error handling, code quality, security, missing tests, documentation.
Return JSON array."""

    response = call_llm_fn(prompt, 1500)

    tasks = []
    try:
        start = response.find("[")
        end = response.rfind("]") + 1
        if start >= 0 and end > start:
            items = json.loads(response[start:end])
            for i, item in enumerate(items):
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

def _read_file_for_llm(path: str) -> str:
    """Read a file for LLM context, with path resolution."""
    try:
        if path.startswith("/"):
            full_path = Path(path)
        else:
            # Try multiple prefixes
            for prefix in ["modules/ai/jarvis/src/", "src/jarvis/", "jarvis/", "src/"]:
                if path.startswith(prefix):
                    path = path[len(prefix):]
                    break
            full_path = REPO_ROOT / "modules/ai/jarvis/src" / path

        if not full_path.exists():
            # Try alternative locations
            for alt in [
                REPO_ROOT / path,
                REPO_ROOT / "modules/ai/jarvis/src" / path,
            ]:
                if alt.exists():
                    full_path = alt
                    break

        return full_path.read_text(encoding="utf-8")[:8000]
    except Exception as e:
        return f"ERROR: Could not read {path}: {e}"


def _resolve_file_path(path: str) -> Path:
    """Resolve a file path to an absolute path."""
    if path.startswith("/"):
        return Path(path)

    for prefix in ["modules/ai/jarvis/src/", "src/jarvis/", "jarvis/", "src/"]:
        if path.startswith(prefix):
            path = path[len(prefix):]
            break

    # Try multiple locations
    candidates = [
        REPO_ROOT / "modules/ai/jarvis/src" / path,
        REPO_ROOT / path,
        REPO_ROOT / "modules/ai/jarvis" / path,
    ]
    for c in candidates:
        if c.exists():
            return c
    return candidates[0]  # Return first candidate even if not exists


def _request_patch_from_llm(
    task_description: str,
    target_files: list[str],
    call_llm_fn: Callable,
) -> tuple[bool, dict[str, str], list[str]]:
    """Request a patch from the LLM. Returns (success, {file: new_content}, errors)."""
    # Read target files
    file_contents = {}
    for path in target_files:
        content = _read_file_for_llm(path)
        if not content.startswith("ERROR"):
            file_contents[path] = content

    if not file_contents:
        return False, {}, ["No readable target files"]

    files_section = "\n\n".join(
        f"=== FILE: {path} ===\n```\n{content}\n```"
        for path, content in file_contents.items()
    )

    # Inject recovery context if available
    recovery_ctx = ""
    try:
        from nightwatch.checkpoint import generate_recovery_summary
        recovery_ctx = generate_recovery_summary()
    except Exception:
        pass

    prompt = f"""Improve this code for the given task.

{recovery_ctx + chr(10) + chr(10) if recovery_ctx else ""}TASK: {task_description}

FILES:
{files_section}

For each file you want to change, return:
=== FILE: path/to/file.py ===
REASON: why this change is needed
--- new content ---
The complete improved file content
--- end ---

Return only files that need changes. If no changes needed, return "NO_CHANGES"."""

    response = call_llm_fn(prompt, 4096)

    if "ERROR" in response:
        return False, {}, [response]

    if "NO_CHANGES" in response:
        return True, {}, []

    # Parse response
    new_contents = {}
    errors = []

    # Split by === FILE: markers
    parts = response.split("=== FILE:")
    for part in parts[1:]:  # Skip first empty part
        lines = part.strip().split("\n")
        if not lines:
            continue

        file_path = lines[0].strip().rstrip("=").strip()
        # Find content between --- new content --- and --- end ---
        content_start = -1
        content_end = -1
        for i, line in enumerate(lines):
            if "--- new content ---" in line:
                content_start = i + 1
            elif "--- end ---" in line:
                content_end = i
                break

        if content_start >= 0 and content_end > content_start:
            new_content = "\n".join(lines[content_start:content_end])
            new_contents[file_path] = new_content
        else:
            errors.append(f"Could not parse patch for {file_path}")

    return bool(new_contents), new_contents, errors


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


def _git_revert() -> None:
    """Revert all uncommitted changes."""
    try:
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
        self.queue = TaskQueue()
        self.editor = SafeEditor()
        self.checkpoint = Checkpoint.load()
        self.mission = self.queue.mission
        self.project_registry = ProjectRegistry()
        self.loop_detector = LoopDetector(
            max_attempts=self.config.loop_max_attempts,
            window_seconds=self.config.loop_window_seconds,
        )
        # Event Bus — decouple notification from harness
        self._bus = EventBus()
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
            budget=budget,
            compaction_threshold=self.config.compaction_threshold,
        )
        # Auto-discover projects if none specified
        if not self.config.projects:
            self._discover_projects()
        # Recover stuck tasks from previous run
        recovered = self.queue.recover_stuck_tasks()
        if recovered > 0:
            self.notify(f"♻️ Recovered {recovered} stuck tasks")

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
        """
        tasks = []
        projects = [project] if project else self.config.projects
        
        for proj_name in projects:
            # Scripted discovery (per-project if project has a root)
            if self.config.use_scripted_discovery:
                tasks.extend(_discover_scripted_tasks())
            
            # LLM discovery (per-project)
            if self.config.use_llm_discovery:
                tasks.extend(_discover_llm_tasks(self.call_llm, proj_name))
        
        # Deduplicate by description
        seen = set()
        unique = []
        for t in tasks:
            key = t.description[:80]
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

        try:
            # ── Step 0: Context budget check ──
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

            # ── Step 1: Request patch from LLM ──
            success, new_contents, errors = _request_patch_from_llm(
                task_description=task.description,
                target_files=task.target_files,
                call_llm_fn=self.call_llm,
            )

            cp.record_operation("patch", success, "; ".join(errors) if errors else "")

            if not success:
                task.fail("; ".join(errors))
                self.notify(f"❌ *Patch Failed*\n{errors[0][:100] if errors else 'unknown'}")
                _log_progress({
                    "task_id": task.id, "status": "patch_failed",
                    "error": errors[0] if errors else "unknown",
                })
                return False

            if not new_contents:
                # LLM decided no changes needed
                task.skip("no_changes_needed")
                self.notify(f"⏭️ *No Changes*\n{task.description[:50]}")
                return False

            # ── Step 2: Apply via SafeEditor ──
            self.queue.update_task(task.id, status=TaskStatus.VALIDATING.value)
            applied_files = []
            apply_errors = []

            for file_path, new_content in new_contents.items():
                resolved = _resolve_file_path(file_path)
                edit_result: EditResult = self.editor.apply_edit(
                    resolved, new_content, validate=True
                )
                if edit_result.success:
                    applied_files.append(file_path)
                    cp.record_operation(f"write:{file_path}", True)
                else:
                    apply_errors.extend(edit_result.errors)
                    cp.record_operation(f"write:{file_path}", False, "; ".join(edit_result.errors))

            if not applied_files:
                task.fail(f"SafeEditor rejected all changes: {'; '.join(apply_errors)}")
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
                _git_revert()
                task.fail(f"Validation failed: {validation.summary}")
                self.notify(f"❌ *Validation Failed*\n{validation.summary}")
                _log_progress({
                    "task_id": task.id, "status": "validation_failed",
                    "summary": validation.summary,
                })
                return False

            # ── Step 4: Independent review ──
            if self.config.auto_review:
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
                    _git_revert()
                    task.fail(f"Review failed: {review.summary}")
                    self.notify(f"❌ *Review Failed*\n{review.summary}")
                    _log_progress({
                        "task_id": task.id, "status": "review_failed",
                        "summary": review.summary,
                    })
                    return False

            # ── Step 5: Commit ──
            msg = f"nightwatch({task.project}): {task.description[:80]}"
            commit_sha = _git_commit(msg)
            cp.record_operation("commit", commit_sha is not None)

            # ── Step 6: Complete ──
            task.complete(commit_sha)
            self.loop_detector.reset(task.id)  # Clear loop tracking on success
            self.mission.total_tasks_completed += 1
            if commit_sha:
                self.mission.total_commits += 1

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
            task.fail(error_msg)
            self.notify(
                f"❌ *Task Error* [{failure_type.value}]\n{error_msg[:100]}"
            )
            self._emit("task_failed", task_id=task.id, error=error_msg[:100], failure_type=failure_type.value)
            _log_progress({
                "task_id": task.id, "status": "error",
                "error": error_msg, "failure_type": failure_type.value,
            })
            # Revert on error
            _git_revert()

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

        projects_str = ", ".join(self.config.projects[:3])
        self.notify(f"🌙 *Nightwatch Started*\nProjects: {projects_str}")
        self._emit("run_started", projects=self.config.projects)

        # ── Recovery ──
        recovery = get_recovery_context()
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
