"""Checkpoint — Recovery system for the Nightwatch harness.

Survives:
- Process crashes
- Context condensing
- LLM failures
- Test failures
- Rollbacks

Stores:
- Current task state
- Last successful operation
- Git state
- Validation results
- Error history
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any
import os


STATE_DIR = Path(os.environ.get("JARVIS_STATE_DIR", str(Path.home() / ".local/state/jarvis/nightwatch")))


def _checkpoint_file_for_project(project: str = "nixos-ai") -> Path:
    """Return per-project checkpoint file to prevent cross-project state corruption."""
    # Sanitize project name for filesystem
    safe_name = project.replace("/", "_").replace("..", "_")
    return STATE_DIR / f"checkpoint-{safe_name}.json"


# Legacy single-file path — kept for backward compat reads only
CHECKPOINT_FILE = STATE_DIR / "checkpoint.json"


@dataclass
class Checkpoint:
    """Recovery checkpoint.
    
    Survives process crashes and context condensing.
    Tracks per-project state for multi-project execution.
    """
    task_id: str | None = None
    task_description: str = ""
    project: str = "nixos-ai"
    started_at: float = field(default_factory=time.time)
    last_operation: str = ""
    last_success: float = 0.0
    last_failure: float = 0.0
    last_error: str = ""
    files_read: list[str] = field(default_factory=list)
    files_written: list[str] = field(default_factory=list)
    git_branch: str = "main"
    git_clean: bool = True
    validation_results: list[dict] = field(default_factory=list)
    retry_count: int = 0
    max_retries: int = 3
    context_tokens_used: int = 0
    history: list[dict] = field(default_factory=list)
    # Multi-project state
    repository: str = ""  # absolute path to repo root
    # Context instrumentation
    context_compactions: int = 0
    context_tokens_before_compaction: int = 0
    context_tokens_after_compaction: int = 0
    context_compaction_events: list[dict] = field(default_factory=list)
    # Recovery state
    recovery_state: dict[str, Any] = field(default_factory=dict)
    # Session tracking
    session_id: str = ""
    session_started_at: float = 0.0
    total_llm_calls: int = 0
    total_tool_calls: int = 0
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> Checkpoint:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)
    
    def save(self) -> None:
        """Save checkpoint to disk (per-project file)."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        target = _checkpoint_file_for_project(self.project)
        target.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    
    @classmethod
    def load(cls, project: str = "nixos-ai") -> Checkpoint:
        """Load checkpoint from disk (per-project file, with legacy fallback)."""
        target = _checkpoint_file_for_project(project)
        # Try per-project file first
        if target.exists():
            try:
                data = json.loads(target.read_text(encoding="utf-8"))
                return cls.from_dict(data)
            except Exception:
                pass
        # Fallback: legacy single file (migrate on next save)
        if CHECKPOINT_FILE.exists():
            try:
                data = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
                cp = cls.from_dict(data)
                cp.project = project
                cp.save()  # Migrate to per-project file
                return cp
            except Exception:
                pass
        return cls(project=project)
    
    def record_operation(self, operation: str, success: bool, error: str = "") -> None:
        """Record an operation."""
        entry = {
            "timestamp": time.time(),
            "operation": operation,
            "success": success,
            "error": error,
        }
        self.history.append(entry)
        
        if success:
            self.last_success = time.time()
        else:
            self.last_failure = time.time()
            self.last_error = error
        
        self.last_operation = operation
        self.save()
    
    def get_git_state(self) -> dict[str, Any]:
        """Get current git state."""
        try:
            branch = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                capture_output=True, text=True, timeout=5,
                cwd=str(Path.home() / "projects" / self.project),
            ).stdout.strip()
            
            status = subprocess.run(
                ["git", "status", "--porcelain"],
                capture_output=True, text=True, timeout=5,
                cwd=str(Path.home() / "projects" / self.project),
            ).stdout.strip()
            
            return {
                "branch": branch,
                "clean": len(status) == 0,
                "modified_files": status.split("\n") if status else [],
            }
        except Exception:
            return {"branch": "unknown", "clean": False, "modified_files": []}
    
    def can_retry(self) -> bool:
        """Check if we can retry the current operation."""
        return self.retry_count < self.max_retries
    
    def increment_retry(self) -> None:
        """Increment retry counter."""
        self.retry_count += 1
        self.save()
    
    def reset_retry(self) -> None:
        """Reset retry counter on success."""
        self.retry_count = 0
        self.save()
    
    def clear(self) -> None:
        """Clear checkpoint."""
        self.task_id = None
        self.task_description = ""
        self.files_read = []
        self.files_written = []
        self.validation_results = []
        self.retry_count = 0
        self.history = []
        self.save()
    
    def record_compaction(self, tokens_before: int, tokens_after: int, reason: str = "") -> None:
        """Record a context compaction event."""
        self.context_compactions += 1
        self.context_tokens_before_compaction = tokens_before
        self.context_tokens_after_compaction = tokens_after
        event = {
            "timestamp": time.time(),
            "tokens_before": tokens_before,
            "tokens_after": tokens_after,
            "tokens_saved": tokens_before - tokens_after,
            "reason": reason,
        }
        self.context_compaction_events.append(event)
        self.save()
    
    def record_llm_call(self, tokens_used: int = 0) -> None:
        """Record an LLM call for context tracking."""
        self.total_llm_calls += 1
        self.context_tokens_used += tokens_used
        self.save()
    
    def record_tool_call(self) -> None:
        """Record a tool call."""
        self.total_tool_calls += 1
        self.save()
    
    def set_recovery_state(self, key: str, value: Any) -> None:
        """Set a recovery state value."""
        self.recovery_state[key] = value
        self.save()
    
    def get_recovery_state(self, key: str, default: Any = None) -> Any:
        """Get a recovery state value."""
        return self.recovery_state.get(key, default)
    
    def get_context_stats(self) -> dict[str, Any]:
        """Get context instrumentation stats."""
        return {
            "total_tokens_used": self.context_tokens_used,
            "total_compactions": self.context_compactions,
            "last_compaction_before": self.context_tokens_before_compaction,
            "last_compaction_after": self.context_tokens_after_compaction,
            "compaction_events": len(self.context_compaction_events),
            "total_llm_calls": self.total_llm_calls,
            "total_tool_calls": self.total_tool_calls,
            "tokens_per_llm_call": (
                self.context_tokens_used // self.total_llm_calls
                if self.total_llm_calls > 0 else 0
            ),
        }


def create_checkpoint_for_task(task_id: str, description: str, project: str = "nixos-ai") -> Checkpoint:
    """Create a new checkpoint for a task."""
    cp = Checkpoint(
        task_id=task_id,
        task_description=description,
        project=project,
    )
    git_state = cp.get_git_state()
    cp.git_branch = git_state.get("branch", "main")
    cp.git_clean = git_state.get("clean", False)
    cp.save()
    return cp


def generate_recovery_summary(project: str = "nixos-ai") -> str:
    """Generate a text summary for context re-injection after compaction.

    This is injected into the LLM context after compaction to remind it
    what it was doing. Without this, the agent forgets its task state.
    """
    cp = Checkpoint.load(project=project)
    if not cp.task_id:
        return ""

    lines = [
        "[RECOVERY CONTEXT — injected after compaction]",
        f"Current task: {cp.task_description[:100]}",
        f"Project: {cp.project}",
        f"Last operation: {cp.last_operation or 'none'}",
    ]

    if cp.last_error:
        lines.append(f"Last error: {cp.last_error[:200]}")
    if cp.files_written:
        lines.append(f"Files modified: {', '.join(cp.files_written[-5:])}")
    if cp.files_read:
        lines.append(f"Files read: {len(cp.files_read)} files")
    if cp.history:
        recent = cp.history[-3:]
        for h in recent:
            status = "✓" if h.get("success") else "✗"
            lines.append(f"  {status} {h.get('operation', '?')} — {h.get('error', '')[:80]}")

    return "\n".join(lines)


def get_recovery_context(project: str = "nixos-ai") -> dict[str, Any] | None:
    """Get context needed to recover from a crash."""
    cp = Checkpoint.load(project=project)
    
    if not cp.task_id:
        return None
    
    return {
        "task_id": cp.task_id,
        "task_description": cp.task_description,
        "project": cp.project,
        "last_operation": cp.last_operation,
        "last_error": cp.last_error,
        "files_read": cp.files_read,
        "files_written": cp.files_written,
        "retry_count": cp.retry_count,
        "can_retry": cp.can_retry(),
        "git_branch": cp.git_branch,
        "history": cp.history[-10:],  # Last 10 operations
    }
