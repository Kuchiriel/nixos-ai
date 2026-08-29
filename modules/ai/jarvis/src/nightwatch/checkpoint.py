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


STATE_DIR = Path.home() / ".local/state/jarvis/nightwatch"
CHECKPOINT_FILE = STATE_DIR / "checkpoint.json"


@dataclass
class Checkpoint:
    """Recovery checkpoint."""
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
    
    def to_dict(self) -> dict:
        return asdict(self)
    
    @classmethod
    def from_dict(cls, data: dict) -> Checkpoint:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known}
        return cls(**filtered)
    
    def save(self) -> None:
        """Save checkpoint to disk."""
        STATE_DIR.mkdir(parents=True, exist_ok=True)
        CHECKPOINT_FILE.write_text(
            json.dumps(self.to_dict(), indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
    
    @classmethod
    def load(cls) -> Checkpoint:
        """Load checkpoint from disk."""
        if CHECKPOINT_FILE.exists():
            try:
                data = json.loads(CHECKPOINT_FILE.read_text(encoding="utf-8"))
                return cls.from_dict(data)
            except Exception:
                pass
        return cls()
    
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


def get_recovery_context() -> dict[str, Any] | None:
    """Get context needed to recover from a crash."""
    cp = Checkpoint.load()
    
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
