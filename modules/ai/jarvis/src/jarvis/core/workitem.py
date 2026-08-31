"""
Work Item Engine — Kanban/Scrum agnostic work management.

Persists work items as JSON, supports different workflow policies,
and enables agent-driven task management.
"""

import json
import os
import uuid
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Optional


class WorkItemType(str, Enum):
    EPIC = "epic"
    FEATURE = "feature"
    TASK = "task"
    BUG = "bug"
    SPIKE = "spike"
    INCIDENT = "incident"
    RESEARCH = "research"
    REFACTOR = "refactor"


class WorkItemStatus(str, Enum):
    BACKLOG = "backlog"
    READY = "ready"
    IN_PROGRESS = "in_progress"
    REVIEW = "review"
    TESTING = "testing"
    DONE = "done"
    BLOCKED = "blocked"
    CANCELLED = "cancelled"


class WorkItemPriority(str, Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class WorkItem:
    """A unit of work in the system."""
    id: str = ""
    project: str = ""
    type: str = "task"
    title: str = ""
    description: str = ""
    priority: str = "medium"
    status: str = "backlog"
    owner: str = ""  # persona ID
    agent: str = ""  # agent instance ID
    persona: str = ""  # persona ID
    dependencies: list = field(default_factory=list)  # other work item IDs
    acceptance_criteria: list = field(default_factory=list)
    artifacts: list = field(default_factory=list)  # file paths created/modified
    commits: list = field(default_factory=list)  # git commit hashes
    tests: list = field(default_factory=list)  # test file paths
    decisions: list = field(default_factory=list)  # ADR references
    history: list = field(default_factory=list)  # status change log
    tags: list = field(default_factory=list)
    created_at: str = ""
    updated_at: str = ""
    started_at: str = ""
    completed_at: str = ""
    estimated_hours: float = 0
    actual_hours: float = 0
    attempts: int = 0
    max_attempts: int = 3
    error_log: list = field(default_factory=list)

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:8]
        now = datetime.now(timezone.utc).isoformat()
        if not self.created_at:
            self.created_at = now
        if not self.updated_at:
            self.updated_at = now

    def transition(self, new_status: str, note: str = ""):
        """Transition to a new status with audit trail."""
        now = datetime.now(timezone.utc).isoformat()
        self.history.append({
            "from": self.status,
            "to": new_status,
            "timestamp": now,
            "note": note,
        })
        self.status = new_status
        self.updated_at = now

        if new_status == WorkItemStatus.IN_PROGRESS and not self.started_at:
            self.started_at = now
        elif new_status == WorkItemStatus.DONE:
            self.completed_at = now

    def add_commit(self, commit_hash: str):
        """Record a git commit."""
        self.commits.append(commit_hash)
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def add_artifact(self, path: str):
        """Record an artifact (file created/modified)."""
        if path not in self.artifacts:
            self.artifacts.append(path)
            self.updated_at = datetime.now(timezone.utc).isoformat()

    def record_error(self, error: str):
        """Record an error attempt."""
        self.attempts += 1
        self.error_log.append({
            "attempt": self.attempts,
            "error": error,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        })
        self.updated_at = datetime.now(timezone.utc).isoformat()

    def is_blocked(self) -> bool:
        """Check if this item is blocked by dependencies."""
        return self.status == WorkItemStatus.BLOCKED

    def can_start(self, completed_items: set) -> bool:
        """Check if all dependencies are met."""
        return all(dep in completed_items for dep in self.dependencies)

    def to_dict(self):
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "WorkItem":
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


# Workflow policies
KANBAN_COLUMNS = [
    WorkItemStatus.BACKLOG,
    WorkItemStatus.READY,
    WorkItemStatus.IN_PROGRESS,
    WorkItemStatus.REVIEW,
    WorkItemStatus.TESTING,
    WorkItemStatus.DONE,
]

SCRUM_COLUMNS = [
    WorkItemStatus.BACKLOG,
    WorkItemStatus.READY,
    WorkItemStatus.IN_PROGRESS,
    WorkItemStatus.REVIEW,
    WorkItemStatus.TESTING,
    WorkItemStatus.DONE,
]

WIP_LIMITS = {
    WorkItemStatus.IN_PROGRESS: 3,
    WorkItemStatus.REVIEW: 2,
    WorkItemStatus.TESTING: 2,
}


class WorkItemEngine:
    """Persistent work item management."""

    def __init__(self, state_dir: str = None):
        if state_dir is None:
            state_dir = os.path.expanduser("~/.local/state/jarvis/work")
        self._state_dir = Path(state_dir)
        self._state_dir.mkdir(parents=True, exist_ok=True)
        self._items: dict[str, WorkItem] = {}
        self._load()

    def _items_file(self) -> Path:
        return self._state_dir / "items.json"

    def _load(self):
        """Load items from disk."""
        f = self._items_file()
        if f.exists():
            try:
                with open(f) as fh:
                    data = json.load(fh)
                for item_data in data:
                    item = WorkItem.from_dict(item_data)
                    self._items[item.id] = item
            except Exception:
                pass

    def _save(self):
        """Save items to disk."""
        data = [item.to_dict() for item in self._items.values()]
        with open(self._items_file(), "w") as f:
            json.dump(data, f, indent=2, default=str)

    def create(self, **kwargs) -> WorkItem:
        """Create a new work item."""
        item = WorkItem(**kwargs)
        self._items[item.id] = item
        self._save()
        return item

    def get(self, item_id: str) -> Optional[WorkItem]:
        """Get a work item by ID."""
        return self._items.get(item_id)

    def update(self, item_id: str, **kwargs) -> Optional[WorkItem]:
        """Update a work item."""
        item = self._items.get(item_id)
        if not item:
            return None

        for key, value in kwargs.items():
            if hasattr(item, key) and key not in ("id", "created_at"):
                setattr(item, key, value)

        item.updated_at = datetime.now(timezone.utc).isoformat()
        self._save()
        return item

    def transition(self, item_id: str, new_status: str, note: str = "") -> Optional[WorkItem]:
        """Transition a work item to a new status."""
        item = self._items.get(item_id)
        if not item:
            return None

        item.transition(new_status, note)
        self._save()
        return item

    def list_items(
        self,
        project: str = None,
        status: str = None,
        priority: str = None,
        persona: str = None,
        item_type: str = None,
    ) -> list[WorkItem]:
        """List items with optional filters."""
        items = list(self._items.values())

        if project:
            items = [i for i in items if i.project == project]
        if status:
            items = [i for i in items if i.status == status]
        if priority:
            items = [i for i in items if i.priority == priority]
        if persona:
            items = [i for i in items if i.persona == persona]
        if item_type:
            items = [i for i in items if i.type == item_type]

        return sorted(items, key=lambda i: (
            {"critical": 0, "high": 1, "medium": 2, "low": 3}.get(i.priority, 4),
            i.created_at,
        ))

    def get_next_task(self, completed_ids: set = None) -> Optional[WorkItem]:
        """Get the next task to work on (priority-sorted, dependencies met)."""
        if completed_ids is None:
            completed_ids = {
                i.id for i in self._items.values()
                if i.status == WorkItemStatus.DONE
            }

        ready = [
            i for i in self._items.values()
            if i.status in (WorkItemStatus.BACKLOG, WorkItemStatus.READY)
            and i.can_start(completed_ids)
            and i.attempts < i.max_attempts
        ]

        if not ready:
            return None

        # Sort by priority, then by created date
        priority_order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        ready.sort(key=lambda i: (
            priority_order.get(i.priority, 4),
            i.created_at,
        ))

        return ready[0]

    def check_wip_limits(self) -> dict:
        """Check if any WIP limits are exceeded."""
        status_counts = {}
        for item in self._items.values():
            status_counts[item.status] = status_counts.get(item.status, 0) + 1

        violations = {}
        for status, limit in WIP_LIMITS.items():
            count = status_counts.get(status, 0)
            if count > limit:
                violations[status.value] = {"count": count, "limit": limit}

        # status_counts keys may be strings or enums
        normalized_counts = {}
        for k, v in status_counts.items():
            normalized_counts[k.value if hasattr(k, 'value') else str(k)] = v

        return {
            "counts": normalized_counts,
            "violations": violations,
        }

    def get_burndown(self) -> dict:
        """Get work item burndown data."""
        total = len(self._items)
        done = sum(1 for i in self._items.values() if i.status == WorkItemStatus.DONE)
        in_progress = sum(1 for i in self._items.values() if i.status == WorkItemStatus.IN_PROGRESS)
        blocked = sum(1 for i in self._items.values() if i.status == WorkItemStatus.BLOCKED)

        return {
            "total": total,
            "done": done,
            "in_progress": in_progress,
            "blocked": blocked,
            "remaining": total - done,
            "progress_pct": round(done / total * 100, 1) if total > 0 else 0,
        }

    def summary(self) -> str:
        """Human-readable summary."""
        burndown = self.get_burndown()
        wip = self.check_wip_limits()

        lines = [
            f"Work Items: {burndown['total']} total",
            f"  Done: {burndown['done']} ({burndown['progress_pct']}%)",
            f"  In Progress: {burndown['in_progress']}",
            f"  Blocked: {burndown['blocked']}",
        ]

        if wip["violations"]:
            lines.append("  ⚠️ WIP LIMIT VIOLATIONS:")
            for status, info in wip["violations"].items():
                lines.append(f"    {status}: {info['count']}/{info['limit']}")

        return "\n".join(lines)
