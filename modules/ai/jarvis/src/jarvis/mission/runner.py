"""MissionRunner — the canonical mission execution path, with EFFECTIVE personas.

Contract: the runner owns NO cognitive loop of its own. Every task goes
through `AgentRuntime` — the same loop the CLI/voice/MCP use. What the
runner adds is what the loop lacks: a dependency-aware queue, a per-task
diff snapshot, personas actually applied, verification before completion,
and persistence on every transition.

What "persona actually applied" means here (the explicit requirement, and
what was missing before):

- `persona_id` reaches `AgentRuntime.run(persona_id=...)`, so `Agent`
  injects the persona's `system_prompt_additions` into the context;
- `model_preference` is translated to `stage` and passed as
  `model_requirements`, which is what `model_policy.select_model` consumes.
  Before, the only mapping was `route_for_persona`, marked DEPRECATED with
  0 callers — meaning `model_preference` was decorative;
- tools are resolved from `ToolRegistry` and filtered by
  `filter_tools(persona)`, so `can_write`/`can_execute` are enforced IN
  CODE, not in the prompt;
- what was really used (persona, model, tools) is recorded on the task.

Everything that reaches the model is English on purpose: the local small
model loses non-English instructions (measured in this repo — the harness
is English by consensus, PT-BR only as a courtesy).
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from jarvis.mission.models import (
    FailureClass, Mission, MissionState, MissionTask, TaskState,
)
from jarvis.mission.store import MissionStore
from jarvis.mission.verify import head_sha, take_snapshot, verify_task


# model_preference (cheap/medium/strong) -> minimum capabilities per role.
# `select_model` filters by capabilities; without declaring them, a model
# without tools could be chosen for a persona that needs to write.
_ROLE_CAPS: dict[str, frozenset[str]] = {
    "read_only": frozenset({"knowledge.retrieve"}),
    "writes": frozenset({"knowledge.retrieve", "filesystem.read",
                         "filesystem.write"}),
    "executes": frozenset({"knowledge.retrieve", "filesystem.read",
                           "filesystem.write", "system.execute"}),
}


def _caps_for(persona: Any) -> frozenset[str]:
    pol = getattr(persona, "policies", None)
    if pol is None:
        return _ROLE_CAPS["executes"]
    if getattr(pol, "can_execute", False) and getattr(pol, "can_write", False):
        return _ROLE_CAPS["executes"]
    if getattr(pol, "can_write", False):
        return _ROLE_CAPS["writes"]
    return _ROLE_CAPS["read_only"]


def _requires_write(task: MissionTask, project_root: str) -> bool:
    """Does satisfying this task's criteria REQUIRE writing something?

    Not a keyword guess: criteria kinds that inherently change the world
    count, and `file_exists` counts only when the target does NOT exist yet
    (a `file_exists` criterion on an existing file is satisfied by
    inspection, so it needs no write capability).
    """
    for c in task.acceptance:
        if c.kind in ("content_contains", "command_ok", "test_passes",
                      "diff_present"):
            return True
        if c.kind == "file_exists" and c.target:
            p = Path(c.target)
            full = p if p.is_absolute() else Path(project_root or ".") / c.target
            if not full.exists():
                return True
    return False


@dataclass
class RunOutcome:
    mission_id: str
    state: str
    done: int = 0
    failed: int = 0
    blocked: int = 0
    pending: int = 0
    report: str = ""
    asks: list[str] = field(default_factory=list)   # questions for the owner

    @property
    def ok(self) -> bool:
        return self.state == MissionState.DONE.value


class MissionRunner:
    """Runs missions: decompose, execute, verify, persist, report."""

    def __init__(
        self,
        store: MissionStore | None = None,
        *,
        emit: Callable[[str, dict[str, Any]], None] | None = None,
    ) -> None:
        self.store = store or MissionStore()
        self._emit = emit or (lambda ev, data: None)
        self._cancel: dict[str, threading.Event] = {}
        self._paused: set[str] = set()

    # -- lifecycle control (called by the channel) ------------------------

    def _cancel_event(self, mission_id: str) -> threading.Event:
        ev = self._cancel.get(mission_id)
        if ev is None:
            ev = self._cancel[mission_id] = threading.Event()
        return ev

    def cancel(self, mission_id: str) -> int:
        """Cancels for real: the event reaches the execution loop.

        Only marking `status=CANCELLED` in the store would leave the thread
        alive and still writing files — the requirement is that cancellation
        reaches the real execution, not just the interface.
        """
        n = 0
        for m in self.store.list():
            if m.id != mission_id:
                continue
            self._cancel_event(m.id).set()
            for t in m.tasks:
                if not t.is_terminal and t.transition(TaskState.CANCELLED):
                    n += 1
            m.state = MissionState.CANCELLED.value
            m.finished_at = time.time()
            self.store.save(m)
        return n

    def pause(self, mission_id: str, reason: str = "manual") -> bool:
        for m in self.store.list():
            if m.id == mission_id and m.state not in (
                    MissionState.DONE.value, MissionState.CANCELLED.value):
                self._paused.add(mission_id)
                m.state = MissionState.PAUSED.value
                m.summary = f"paused: {reason}"
                self.store.save(m)
                return True
        return False

    def resume(self, mission_id: str) -> bool:
        for m in self.store.list():
            if m.id == mission_id and m.state == MissionState.PAUSED.value:
                self._paused.discard(mission_id)
                m.state = MissionState.RUNNING.value
                m.summary = "resumed"
                self.store.save(m)
                return True
        return False

    def steer(self, mission_id: str, message: str) -> bool:
        """Inject guidance into the mission (applied on the task's next turn)."""
        for m in self.store.list():
            if m.id == mission_id:
                m.steering.append(message[:500])
                self.store.save(m)
                return True
        return False

    # -- persona -> execution requirements --------------------------------

    def _resolve_persona(self, task: MissionTask) -> Any:
        try:
            from jarvis.core.persona import PersonaRegistry
            reg = PersonaRegistry()
            p = reg.get(task.persona_id) or reg.select_for_task(task.description)
            return p or reg.get("jarvis")
        except Exception:
            return None

    def _tool_names(self) -> list[str]:
        try:
            from jarvis.runtime.registry import ToolRegistry
            return ToolRegistry.build_default().names()
        except Exception:
            return []

    def _plan_for(self, task: MissionTask) -> dict[str, Any]:
        """Builds what the persona NEEDS (not what it is allowed to do)."""
        persona = self._resolve_persona(task)
        pol = getattr(persona, "policies", None)
        writes = bool(getattr(pol, "can_write", False))
        executes = bool(getattr(pol, "can_execute", False))
        return {
            "persona": persona,
            "caps": _caps_for(persona),
            "wants_write": writes,
            "wants_exec": executes,
            "stage": (getattr(persona, "model_preference", "") or "").strip(),
        }

    # -- executing one task ------------------------------------------------

    def _execute_one(self, mission: Mission, task: MissionTask) -> str:
        """Execute ONE task through AgentRuntime. -> textual outcome."""
        task.transition(TaskState.RUNNING)
        self.store.save(mission)          # persist BEFORE the work

        plan = self._plan_for(task)
        persona = plan["persona"]

        # A persona that must write but lacks the capability does not get
        # the tools: we filter in code and record the divergence.
        allowed = self._tool_names()
        try:
            from jarvis.core.persona import filter_tools
            allowed = filter_tools(allowed, persona)
        except Exception:
            pass
        wants_write = plan["wants_write"]
        wants_exec = plan["wants_exec"]
        needs_write = _requires_write(task, mission.project_root)
        if needs_write and not wants_write:
            task.verification_evidence.append(
                "WARNING: task requires writing but the persona lacks can_write")
        if needs_write and wants_write and not wants_exec:
            task.verification_evidence.append(
                "WARNING: persona has can_write but not can_execute")

        task.persona_applied = getattr(persona, "id", "") or task.persona_id
        task.tools_used = list(allowed[:12])

        requirements: dict[str, Any] = {"capabilities": sorted(plan["caps"])}
        if plan["stage"]:
            requirements["stage"] = plan["stage"]

        # Real snapshot for attribution: a global `git diff HEAD` would
        # attribute other tasks'/sessions' work to this one.
        before = take_snapshot(mission.project_root or ".")
        task.diff_before = sorted(before.paths)

        instr = self._build_instruction(mission, task, persona, allowed)

        try:
            from jarvis.core.config import get_config
            from jarvis.runtime.agent_runtime import AgentRuntime
            rt = AgentRuntime(get_config())
            result = rt.run(
                instr,
                model_requirements=requirements,
                persona_id=task.persona_applied or None,
                approve=bool(wants_exec and wants_write),
            )
        except Exception as exc:  # noqa: BLE001
            task.record_failure(str(exc), FailureClass.TOOL)
            task.transition(TaskState.FAILED)
            self.store.save(mission)
            return f"{task.id}: execution error ({exc})"

        session = getattr(result, "session", None)
        task.model_used = getattr(session, "model_id", "") or ""
        used = getattr(session, "tools_used", None)
        if used:
            task.tools_used = list(used)

        # Verify against the WORLD (not the LLM's report).
        task.transition(TaskState.VERIFYING)
        self.store.save(mission)
        vr = verify_task(task, mission.project_root or ".")
        after = take_snapshot(mission.project_root or ".")
        touched = before.changed_paths(after)
        task.files_attributed = touched
        task.commit_sha = head_sha(mission.project_root or ".") or None
        task.verification_evidence.extend(vr.evidence)

        if vr.verified:
            task.transition(TaskState.DONE)
            task.failure_class = ""
            self.store.save(mission)
            return f"{task.id}: DONE - {vr.summary()} / {len(touched)} file(s)"

        # Verification failed -> retry with the failure evidence in context.
        task.verification_evidence.extend(vr.missing)
        fc = FailureClass.VALIDATION
        low = " ".join(vr.missing).lower()
        if "timeout" in low:
            fc = FailureClass.TRANSIENT
        elif "permission" in low or "policy" in low:
            fc = FailureClass.PERMISSION
        task.record_failure("; ".join(vr.missing[:3]), fc)
        if task.can_retry():
            task.transition(TaskState.READY)
            self.store.save(mission)
            return f"{task.id}: RETRY (verification failed: {vr.missing[:1]})"
        task.transition(TaskState.FAILED)
        self.store.save(mission)
        return f"{task.id}: FAILED - {vr.missing[:2]}"

    def _build_instruction(self, mission: Mission, task: MissionTask,
                           persona: Any, allowed: list[str]) -> str:
        """Everything here is model-facing, so it is English by design."""
        files = "\n".join(f"  {f}" for f in (task.target_files or [])) or \
            "  (derive from the repository)"
        criteria = "\n".join(
            f"  - {c.kind}({c.target or '-'}) {c.description}".rstrip()
            for c in task.acceptance) or "  (none given - discover and state them)"
        lines = [
            f"PROJECT: {mission.project} (root: {mission.project_root})",
            "IMPORTANT: work ONLY inside this project. Do not read or write in another repository.",
            "",
            f"TASK {task.id}: {task.title}",
            task.description,
            "",
            "FILES IN SCOPE:",
            files,
            "",
            "ACCEPTANCE CRITERIA (the machine checks these - never claim success without them):",
            criteria,
            "",
            "AVAILABLE TOOLS (everything else is blocked by policy):",
            ("  " + ", ".join(allowed[:12])) if allowed else "  (read only)",
        ]
        if mission.steering:
            lines += ["", "OWNER GUIDANCE (apply now):", "  " + mission.steering[-1]]
        if persona is not None and getattr(persona, "responsibilities", None):
            lines += ["", f"ROLE ({persona.name}): " +
                      "; ".join(persona.responsibilities[:4])]
        lines += ["", "Deliver the result. Do not ask permission to continue."]
        return "\n".join(lines)

    # -- main loop ---------------------------------------------------------

    def run(self, mission_id: str, *, max_steps: int = 60) -> RunOutcome:
        mission = self.store.load(mission_id)
        if mission is None:
            return RunOutcome(mission_id, "MISSING",
                              report=f"mission {mission_id} not found")

        cancel = self._cancel_event(mission_id)
        if mission.state == MissionState.CANCELLED.value:
            return RunOutcome(mission_id, mission.state)

        if not mission.project_root or not Path(mission.project_root).is_dir():
            mission.state = MissionState.FAILED.value
            mission.summary = "invalid or missing project root - cannot execute"
            mission.finished_at = time.time()
            self.store.save(mission)
            return RunOutcome(mission_id, mission.state, report=mission.summary)

        if mission.state in (MissionState.PLANNING.value, ""):
            mission.state = MissionState.RUNNING.value

        steps = 0
        while steps < max_steps:
            steps += 1
            if cancel.is_set():
                mission.state = MissionState.CANCELLED.value
                mission.finished_at = time.time()
                self.store.save(mission)
                break
            if mission_id in self._paused:
                mission.state = MissionState.PAUSED.value
                self.store.save(mission)
                break

            mission.refresh_blocked()
            ready = mission.ready_tasks()
            if not ready:
                if mission.is_complete():
                    mission.state = (MissionState.FAILED.value
                                     if mission.has_failures()
                                     else MissionState.DONE.value)
                    mission.finished_at = time.time()
                elif any(t.status == TaskState.AWAITING_APPROVAL.value
                         for t in mission.tasks):
                    mission.state = MissionState.WAITING_DECISION.value
                self.store.save(mission)
                break

            task = ready[0]
            self._emit("task_started", {"mission": mission_id, "task": task.id,
                                        "title": task.title})
            self._execute_one(mission, task)
            mission.state = MissionState.RUNNING.value
            self.store.save(mission)

        prog = mission.progress()
        return RunOutcome(
            mission_id=mission_id,
            state=mission.state,
            done=prog.get(TaskState.DONE.value, 0),
            failed=prog.get(TaskState.FAILED.value, 0),
            blocked=prog.get(TaskState.BLOCKED.value, 0),
            pending=prog.get(TaskState.PENDING.value, 0),
            report=self.render_report(mission),
            asks=[mission.pending_question] if mission.pending_question else [],
        )

    # -- report ------------------------------------------------------------

    def render_report(self, mission: Mission) -> str:
        lines = [f"MISSION {mission.id}",
                 f"objective: {mission.objective[:120]}",
                 f"project: {mission.project} ({mission.project_root})",
                 f"state: {mission.state}", ""]
        for t in mission.tasks:
            icon = {"DONE": "[ok]", "FAILED": "[x]", "BLOCKED": "[!]",
                    "CANCELLED": "[-]", "RUNNING": "[>]"}.get(t.status, "[ ]")
            lines.append(f"{icon} [{t.id}] {t.title[:60]} - {t.status}")
            if t.persona_applied:
                lines.append(f"     persona={t.persona_applied} "
                             f"model={t.model_used or '-'}")
            if t.files_attributed:
                lines.append(f"     changed: {', '.join(t.files_attributed[:6])}")
            for ev in (t.verification_evidence or [])[:3]:
                lines.append(f"     evidence: {ev[:100]}")
            if t.last_error:
                lines.append(f"     error: {t.last_error[:120]}")
        prog = mission.progress()
        lines += ["", "summary: " + " / ".join(
            f"{k.lower()}={v}" for k, v in prog.items() if v)]
        return "\n".join(lines)[:3500]