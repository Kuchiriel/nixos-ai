"""TaskQueue — Persistent task queue for the Nightwatch harness.

Survives:
- Context condensing
- Process restart
- Task failures
- LLM failures
- Test failures
- Rollbacks

Each task has a full lifecycle with state machine.
"""

from __future__ import annotations
import os

import json
import time
from dataclasses import dataclass, field, asdict
from enum import Enum
from pathlib import Path
from typing import Any


STATE_DIR = Path(os.environ.get("JARVIS_STATE_DIR", str(Path.home() / ".local/state/jarvis/nightwatch")))
TASK_QUEUE_FILE = STATE_DIR / "task_queue.json"
MISSION_STATE_FILE = STATE_DIR / "mission_state.json"


class TaskStatus(str, Enum):
    DISCOVERED = "DISCOVERED"
    READY = "READY"
    IN_PROGRESS = "IN_PROGRESS"
    VALIDATING = "VALIDATING"
    REVIEW = "REVIEW"
    COMPLETED = "COMPLETED"
    BLOCKED = "BLOCKED"
    FAILED = "FAILED"
    ABANDONED = "ABANDONED"


class LoopDetector:
    """Detects when a task is stuck in a failure loop.
    
    Tracks attempts per task with timestamps. A task is considered
    in a loop if it fails N times within a time window.
    """
    
    def __init__(self, max_attempts: int = 3, window_seconds: float = 300.0):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._history: dict[str, list[float]] = {}
    
    def record_attempt(self, task_id: str, success: bool) -> bool:
        """Record an attempt. Returns True if task is in a loop."""
        now = time.time()
        if task_id not in self._history:
            self._history[task_id] = []
        
        # Clean old entries outside window
        self._history[task_id] = [
            t for t in self._history[task_id]
            if now - t < self.window_seconds
        ]
        
        self._history[task_id].append(now)
        
        # Check if too many failures in window
        if len(self._history[task_id]) >= self.max_attempts:
            return True  # in loop
        
        return False
    
    def reset(self, task_id: str) -> None:
        """Reset tracking for a task (e.g., after successful completion)."""
        self._history.pop(task_id, None)
    
    def get_stats(self, task_id: str) -> dict:
        """Get attempt stats for a task."""
        now = time.time()
        recent = [
            t for t in self._history.get(task_id, [])
            if now - t < self.window_seconds
        ]
        return {
            "attempts_in_window": len(recent),
            "max_attempts": self.max_attempts,
            "window_seconds": self.window_seconds,
            "in_loop": len(recent) >= self.max_attempts,
        }

@dataclass
class Task:
    """A single task in the queue.
    
    Supports multi-project via `repository` field.
    Supports recovery via `recovery_state` field.
    Supports dependency ordering via `dependencies` field.
    """
    id: str
    project: str
    description: str
    priority: int = 5  # 1=highest, 10=lowest
    risk: str = "low"  # low, medium, high
    target_files: list[str] = field(default_factory=list)
    acceptance_criteria: str = ""
    status: str = TaskStatus.DISCOVERED.value
    attempts: int = 0
    max_attempts: int = 3
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    parent_task: str | None = None
    dependencies: list[str] = field(default_factory=list)
    last_error: str | None = None
    last_validation: str | None = None
    commit_sha: str | None = None
    evidence: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    # Multi-project support
    repository: str = ""  # absolute path to repo root
    language: str = ""  # python, nix, shell, etc.
    # Recovery state
    recovery_state: dict[str, Any] = field(default_factory=dict)
    # Context tracking
    context_tokens_used: int = 0
    last_context_compaction: float | None = None
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> Task:
        # Remove unknown fields
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)
    
    def block(self, reason: str) -> None:
        self.status = TaskStatus.BLOCKED.value
        self.last_error = reason
        self.updated_at = time.time()
    
    def fail(self, error: str) -> None:
        self.attempts += 1
        self.last_error = error
        self.updated_at = time.time()
        if self.attempts >= self.max_attempts:
            self.status = TaskStatus.FAILED.value
        else:
            self.status = TaskStatus.READY.value
    
    def complete(self, commit_sha: str | None = None) -> None:
        self.status = TaskStatus.COMPLETED.value
        self.commit_sha = commit_sha
        self.updated_at = time.time()
    
    def abandon(self, reason: str) -> None:
        self.status = TaskStatus.ABANDONED.value
        self.last_error = reason
        self.updated_at = time.time()
    
    def skip(self, reason: str) -> None:
        """Skip this task (e.g. dry-run, no changes needed)."""
        self.status = TaskStatus.ABANDONED.value
        self.last_error = f"skipped: {reason}"
        self.updated_at = time.time()
    
    @property
    def is_terminal(self) -> bool:
        return self.status in (
            TaskStatus.COMPLETED.value,
            TaskStatus.FAILED.value,
            TaskStatus.ABANDONED.value,
        )
    
    @property
    def can_retry(self) -> bool:
        return self.attempts < self.max_attempts and not self.is_terminal


@dataclass
class MissionState:
    """Overall mission state."""
    active: bool = False
    project: str = "nixos-ai"
    started_at: float | None = None
    last_checkpoint: float | None = None
    total_tasks_completed: int = 0
    total_tasks_failed: int = 0
    total_commits: int = 0
    current_focus: str | None = None
    blocked_reasons: list[str] = field(default_factory=list)
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> MissionState:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)


class TaskQueue:
    """Persistent task queue with state management."""
    
    def __init__(self):
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        self._tasks: list[Task] = []
        self._mission = MissionState()
        self._load()
    
    def _load(self) -> None:
        """Load state from disk."""
        # Load tasks
        if TASK_QUEUE_FILE.exists():
            try:
                data = json.loads(TASK_QUEUE_FILE.read_text(encoding="utf-8"))
                self._tasks = [Task.from_dict(t) for t in data]
            except Exception:
                self._tasks = []
        
        # Load mission state
        if MISSION_STATE_FILE.exists():
            try:
                data = json.loads(MISSION_STATE_FILE.read_text(encoding="utf-8"))
                self._mission = MissionState.from_dict(data)
            except Exception:
                self._mission = MissionState()
    
    def _save(self) -> None:
        """Save state to disk."""
        TASK_QUEUE_FILE.write_text(
            json.dumps([t.to_dict() for t in self._tasks], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        MISSION_STATE_FILE.write_text(
            json.dumps(self._mission.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    
    @property
    def mission(self) -> MissionState:
        return self._mission
    
    def add_task(self, task: Task) -> None:
        """Add a task to the queue."""
        # Check for duplicates
        existing = [t for t in self._tasks if t.description == task.description and not t.is_terminal]
        if existing:
            return
        
        self._tasks.append(task)
        self._save()
    
    def get_next_task(self) -> Task | None:
        """Get the next task to execute."""
        ready = [
            t for t in self._tasks
            if t.status in (TaskStatus.READY.value, TaskStatus.DISCOVERED.value)
            and not t.is_terminal
        ]
        
        if not ready:
            return None
        
        # Sort by priority (lower number = higher priority)
        ready.sort(key=lambda t: (t.priority, t.created_at))
        
        # Check dependencies
        for task in ready:
            if task.dependencies:
                deps_met = all(
                    any(t.id == dep and t.status == TaskStatus.COMPLETED.value 
                        for t in self._tasks)
                    for dep in task.dependencies
                )
                if not deps_met:
                    continue
            return task
        
        return None
    
    def update_task(self, task_id: str, **kwargs: Any) -> None:
        """Update a task's fields."""
        for task in self._tasks:
            if task.id == task_id:
                for key, value in kwargs.items():
                    if hasattr(task, key):
                        setattr(task, key, value)
                task.updated_at = time.time()
                break
        self._save()
    
    def get_task(self, task_id: str) -> Task | None:
        """Get a task by ID."""
        for task in self._tasks:
            if task.id == task_id:
                return task
        return None
    
    def get_all_tasks(self, status: str | None = None) -> list[Task]:
        """Get all tasks, optionally filtered by status."""
        if status:
            return [t for t in self._tasks if t.status == status]
        return list(self._tasks)
    
    def get_stats(self, project: str | None = None) -> dict[str, Any]:
        """Get queue statistics, optionally filtered by project."""
        tasks = self._tasks
        if project:
            tasks = [t for t in tasks if t.project == project]
        return {
            "total": len(tasks),
            "completed": len([t for t in tasks if t.status == TaskStatus.COMPLETED.value]),
            "failed": len([t for t in tasks if t.status == TaskStatus.FAILED.value]),
            "blocked": len([t for t in tasks if t.status == TaskStatus.BLOCKED.value]),
            "in_progress": len([t for t in tasks if t.status == TaskStatus.IN_PROGRESS.value]),
            "ready": len([t for t in tasks if t.status in (TaskStatus.READY.value, TaskStatus.DISCOVERED.value)]),
        }
    
    def get_projects(self) -> list[str]:
        """Get all unique projects in the queue."""
        return list({t.project for t in self._tasks})
    
    def get_tasks_by_project(self, project: str) -> list[Task]:
        """Get all tasks for a specific project."""
        return [t for t in self._tasks if t.project == project]
    
    def get_in_progress_tasks(self) -> list[Task]:
        """Get all tasks currently in progress (for recovery)."""
        return [t for t in self._tasks if t.status == TaskStatus.IN_PROGRESS.value]
    
    def recover_stuck_tasks(self, max_age_seconds: float = 3600) -> int:
        """Recover tasks stuck IN_PROGRESS for too long (e.g. after crash).
        
        Returns number of tasks recovered.
        """
        now = time.time()
        recovered = 0
        for task in self._tasks:
            if task.status == TaskStatus.IN_PROGRESS.value:
                age = now - task.updated_at
                if age > max_age_seconds:
                    # Reset to READY so it can be retried
                    task.status = TaskStatus.READY.value
                    task.last_error = f"Recovered from stuck state after {age:.0f}s"
                    task.updated_at = now
                    recovered += 1
        if recovered > 0:
            self._save()
        return recovered
    
    def prune_completed(self, keep_last: int = 50) -> int:
        """Remove old completed tasks, keeping recent ones."""
        completed = [t for t in self._tasks if t.is_terminal]
        if len(completed) <= keep_last:
            return 0
        
        completed.sort(key=lambda t: t.updated_at)
        to_remove = completed[:-keep_last]
        self._tasks = [t for t in self._tasks if t.id not in {r.id for r in to_remove}]
        self._save()
        return len(to_remove)
