"""Mission models — the persisted contract of an objective in flight.

A mission is NOT a thread nor an in-memory dict: it is this structure,
serialized to disk before any prolonged work starts (the resume
requirement). Field names follow what `nightwatch.task_queue.Task` already
does (id, status, attempts, dependencies, evidence, commit_sha...) and ADD
what nightwatch lacks: the binding to the Telegram origin, the persona
actually applied, the spent approval, the checkpoint, and verification
evidence kept separate from "the LLM said it did it".
"""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field, asdict
from enum import Enum
from typing import Any


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:10]}"


class TaskState(str, Enum):
    """States of a task inside a mission.

    Deliberately RICHER than nightwatch's `TaskStatus`, because here it
    matters to distinguish "done" from "done AND VERIFIED" — completion
    must derive from evidence, not from an LLM report.
    """

    PENDING = "PENDING"          # created, dependencies unmet
    BLOCKED = "BLOCKED"          # dependency failed / needs a decision
    READY = "READY"              # eligible now
    RUNNING = "RUNNING"          # executing
    AWAITING_APPROVAL = "AWAITING_APPROVAL"  # high-impact operation
    VERIFYING = "VERIFYING"      # verification running
    DONE = "DONE"                # executed AND verified
    FAILED = "FAILED"            # errored, attempts exhausted
    CANCELLED = "CANCELLED"      # cancelled by decision
    PAUSED = "PAUSED"            # explicitly paused


TERMINAL = frozenset({TaskState.DONE, TaskState.FAILED, TaskState.CANCELLED})

# Valid transitions. Anything else is a bug (or corrupted state) and is
# refused by `Task.can_transition_to` — the store records the refusal
# instead of accepting an impossible state.
TRANSITIONS: dict[TaskState, frozenset[TaskState]] = {
    TaskState.PENDING: frozenset({TaskState.READY, TaskState.BLOCKED,
                                  TaskState.CANCELLED}),
    TaskState.BLOCKED: frozenset({TaskState.READY, TaskState.CANCELLED,
                                  TaskState.FAILED}),
    TaskState.READY: frozenset({TaskState.RUNNING, TaskState.CANCELLED,
                                TaskState.BLOCKED}),
    TaskState.RUNNING: frozenset({TaskState.AWAITING_APPROVAL,
                                  TaskState.VERIFYING, TaskState.FAILED,
                                  TaskState.READY, TaskState.CANCELLED}),
    TaskState.AWAITING_APPROVAL: frozenset({TaskState.RUNNING,
                                            TaskState.READY,
                                            TaskState.CANCELLED,
                                            TaskState.FAILED}),
    TaskState.VERIFYING: frozenset({TaskState.DONE, TaskState.READY,
                                    TaskState.FAILED}),
    TaskState.DONE: frozenset(),
    TaskState.FAILED: frozenset({TaskState.READY}),   # explicit retry
    TaskState.CANCELLED: frozenset(),
}


class MissionState(str, Enum):
    PLANNING = "PLANNING"
    RUNNING = "RUNNING"
    PAUSED = "PAUSED"
    WAITING_DECISION = "WAITING_DECISION"
    VERIFYING = "VERIFYING"
    DONE = "DONE"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"


class FailureClass(str, Enum):
    """Failure classification — decides retry vs. stop."""

    TRANSIENT = "transient"            # network/timeout: cheap retry
    CONTEXT_EXHAUSTION = "context"     # needs compaction/restart
    VALIDATION = "validation"          # wrong code: retry with evidence
    PERMISSION = "permission"          # persona lacks capability
    TOOL = "tool"                      # the tool itself failed
    TASK_DEFECT = "task_defect"        # task is malformed: do not retry
    UNRECOVERABLE = "unrecoverable"    # protected path / policy violation


# Failures worth retrying (the rest need intervention or a new task).
RETRYABLE = frozenset({FailureClass.TRANSIENT, FailureClass.TOOL,
                       FailureClass.VALIDATION, FailureClass.CONTEXT_EXHAUSTION})


@dataclass
class AcceptanceCriterion:
    """A verifiable criterion — never the objective restated.

    The requirement is explicit: "acceptance criteria filled in with the
    objective itself" does not count. So each criterion carries a
    machine-checkable TYPE and a target, and `verify.py` checks it against
    the world.
    """

    kind: str                 # file_exists | content_contains | test_passes
                              # | command_ok | file_absent | diff_present
                              # | evidence_present
    target: str = ""          # path, command, or needle
    description: str = ""
    optional: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> AcceptanceCriterion:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class MissionTask:
    """One task inside a mission."""

    id: str
    title: str
    project: str
    project_root: str = ""
    description: str = ""
    persona_id: str = "jarvis"
    # Persona ACTUALLY used — filled at execution time. If it diverges from
    # the plan, the report shows it (a persona without capability must not
    # silently receive extra permissions).
    persona_applied: str = ""
    model_used: str = ""
    tools_used: list[str] = field(default_factory=list)

    status: str = TaskState.PENDING.value
    priority: int = 5
    dependencies: list[str] = field(default_factory=list)
    parent_id: str | None = None

    acceptance: list[AcceptanceCriterion] = field(default_factory=list)
    target_files: list[str] = field(default_factory=list)

    attempt: int = 0
    max_attempts: int = 2
    failure_class: str = ""
    last_error: str = ""

    # Per-task attribution: dirty-tree snapshot before and after. This is
    # what stops "git diff HEAD" from reporting another task's work as ours.
    diff_before: list[str] = field(default_factory=list)
    files_attributed: list[str] = field(default_factory=list)
    commit_sha: str | None = None

    approval_ticket: str | None = None
    approval_operation: str = ""

    checkpoint_ref: str = ""
    verification_evidence: list[str] = field(default_factory=list)
    report: str = ""

    telegram_chat_id: int | None = None
    telegram_message_id: int | None = None

    created_at: float = field(default_factory=time.time)
    started_at: float | None = None
    updated_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    # -----------------------------------------------------------------

    @property
    def state(self) -> TaskState:
        try:
            return TaskState(self.status)
        except ValueError:
            return TaskState.PENDING

    @property
    def is_terminal(self) -> bool:
        return self.state in TERMINAL

    def can_transition_to(self, new: TaskState) -> bool:
        if new is self.state:
            return True
        return new in TRANSITIONS.get(self.state, frozenset())

    def transition(self, new: TaskState) -> bool:
        """Apply a transition if valid. Returns False (and changes nothing) if not."""
        if not self.can_transition_to(new):
            return False
        self.status = new.value
        self.updated_at = time.time()
        if new is TaskState.RUNNING and self.started_at is None:
            self.started_at = time.time()
        if new in TERMINAL and self.finished_at is None:
            self.finished_at = time.time()
        return True

    def record_failure(self, error: str, failure_class: FailureClass) -> None:
        self.attempt += 1
        self.last_error = error[:2000]
        self.failure_class = failure_class.value

    def can_retry(self) -> bool:
        return (self.attempt < self.max_attempts
                and FailureClass(self.failure_class or "task_defect") in RETRYABLE
                and self.state is not TaskState.CANCELLED)

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["acceptance"] = [c.to_dict() for c in self.acceptance]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> MissionTask:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        kw = {k: v for k, v in d.items() if k in known}
        kw["acceptance"] = [AcceptanceCriterion.from_dict(c)
                            for c in d.get("acceptance", [])]
        return cls(**kw)


@dataclass
class Mission:
    """An objective in flight, with everything it references."""

    id: str
    objective: str
    project: str
    project_root: str = ""
    state: str = MissionState.PLANNING.value
    tasks: list[MissionTask] = field(default_factory=list)
    requested_by: str = ""            # identity label
    telegram_chat_id: int | None = None

    summary: str = ""
    pending_question: str = ""        # while WAITING_DECISION
    steering: list[str] = field(default_factory=list)

    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    finished_at: float | None = None

    # -----------------------------------------------------------------

    @staticmethod
    def new_id() -> str:
        return _new_id("msn")

    def task(self, task_id: str) -> MissionTask | None:
        for t in self.tasks:
            if t.id == task_id:
                return t
        return None

    def by_state(self, *states: TaskState) -> list[MissionTask]:
        want = {s.value for s in states}
        return [t for t in self.tasks if t.status in want]

    def ready_tasks(self) -> list[MissionTask]:
        """Tasks eligible NOW: state allows running AND dependencies met.

        A dependency only counts as met when the task it points at is DONE.
        A FAILED dependency becomes BLOCKED rather than "already ran",
        otherwise the orchestrator would build on top of work that
        verification rejected.
        """
        done = {t.id for t in self.tasks if t.status == TaskState.DONE.value}
        dead = {t.id for t in self.tasks
                if t.status in (TaskState.FAILED.value, TaskState.CANCELLED.value)}
        out: list[MissionTask] = []
        for t in self.tasks:
            if t.status not in (TaskState.READY.value, TaskState.PENDING.value):
                continue
            if any(d in dead for d in t.dependencies):
                continue
            if all(d in done for d in t.dependencies):
                out.append(t)
        out.sort(key=lambda t: (t.priority, t.created_at))
        return out

    def refresh_blocked(self) -> list[MissionTask]:
        """Promote PENDING->READY and BLOCK tasks whose dependency died."""
        done = {t.id for t in self.tasks if t.status == TaskState.DONE.value}
        dead = {t.id for t in self.tasks
                if t.status in (TaskState.FAILED.value, TaskState.CANCELLED.value)}
        changed: list[MissionTask] = []
        for t in self.tasks:
            if any(d in dead for d in t.dependencies) and t.status in (
                    TaskState.PENDING.value, TaskState.READY.value):
                if t.transition(TaskState.BLOCKED):
                    t.last_error = f"dependency failed: {', '.join(t.dependencies)}"
                    changed.append(t)
            elif all(d in done for d in t.dependencies) and t.status == TaskState.PENDING.value:
                if t.transition(TaskState.READY):
                    changed.append(t)
        if changed:
            self.updated_at = time.time()
        return changed

    def is_complete(self) -> bool:
        return bool(self.tasks) and all(t.is_terminal for t in self.tasks)

    def has_failures(self) -> bool:
        return any(t.status in (TaskState.FAILED.value, TaskState.BLOCKED.value)
                   for t in self.tasks)

    def progress(self) -> dict[str, int]:
        out = {s.value: 0 for s in TaskState}
        for t in self.tasks:
            out[t.status] = out.get(t.status, 0) + 1
        return out

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["tasks"] = [t.to_dict() for t in self.tasks]
        return d

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> Mission:
        known = {f.name for f in cls.__dataclass_fields__.values()}
        kw = {k: v for k, v in d.items() if k in known}
        kw["tasks"] = [MissionTask.from_dict(t) for t in d.get("tasks", [])]
        return cls(**kw)