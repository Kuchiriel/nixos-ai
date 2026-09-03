"""Integration layer — wires existing components to the Control Plane.

This module bridges the gap between existing components (doctor, heal,
watchdog, gaming, idle, voice, nightwatch) and the new Control Plane
(Events, State, Commands, Notifications) WITHOUT modifying their internals.

Architecture:
    Existing component → EventBus (already publishes)
        → Integration layer (subscribes)
            → State Store (updates operational state)
            → Notification Manager (routes to channels)
            → Command Registry (registers component commands)

This is a gradual migration path. As components are updated to use the
Control Plane directly, the integration layer subscriptions can be removed.
"""

from __future__ import annotations

import time
from typing import Any

from jarvis.control_plane.events import Events, Severity
from jarvis.control_plane.state import Sections, get_state_store
from jarvis.control_plane.commands import Risk, get_command_registry
from jarvis.control_plane.notifications import get_notification_manager
from jarvis.core.eventbus import get_bus


def setup_integration() -> None:
    """Wire existing components to the Control Plane.

    Call this once at startup (after ControlPlane.setup()).
    """
    bus = get_bus()
    state = get_state_store()
    notifications = get_notification_manager()

    # ─── Doctor → State + Notifications ────────────────────────────
    # doctor.py already publishes "doctor.report" to EventBus
    # We subscribe to update State Store and route notifications

    def _on_doctor_report(event: Any) -> None:
        data = event.data
        overall = data.get("overall", "ok")
        state.update(Sections.HEALTH, "overall", overall)
        state.update(Sections.HEALTH, "down_count", data.get("down", 0))
        state.update(Sections.HEALTH, "degraded_count", data.get("degraded", 0))
        state.update(Sections.HEALTH, "last_check", time.time())

        if overall == "down":
            notifications.notify_event(Events.DOCTOR_DOWN, {
                "severity": Severity.CRITICAL,
                "down": data.get("down", 0),
            })
        elif overall == "degraded":
            notifications.notify_event(Events.DOCTOR_DEGRADED, {
                "severity": Severity.WARNING,
                "degraded": data.get("degraded", 0),
            })

    bus.subscribe("doctor.report", _on_doctor_report, name="cp-doctor")

    # ─── Heal → State + Notifications ──────────────────────────────
    # heal.py publishes "heal.service" and "heal.recovered"

    def _on_heal_service(event: Any) -> None:
        data = event.data
        service = data.get("service", "?")
        healed = data.get("healed", False)
        state.update(Sections.SERVICES, f"{service}.status",
                     "active" if healed else "failed")
        state.update(Sections.SERVICES, f"{service}.last_heal", time.time())

    def _on_heal_recovered(event: Any) -> None:
        data = event.data
        service = data.get("service", "?")
        state.update(Sections.SERVICES, f"{service}.status", "active")

    bus.subscribe("heal.service", _on_heal_service, name="cp-heal")
    bus.subscribe("heal.recovered", _on_heal_recovered, name="cp-heal-recovered")

    # ─── Idle → State ──────────────────────────────────────────────
    # idle.py publishes "idle.task"

    def _on_idle_task(event: Any) -> None:
        data = event.data
        task = data.get("task", "?")
        ok = data.get("ok", False)
        state.update(Sections.SYSTEM, "last_idle_task", task)
        state.update(Sections.SYSTEM, "last_idle_ok", ok)
        state.update(Sections.SYSTEM, "last_idle_time", time.time())

    bus.subscribe("idle.task", _on_idle_task, name="cp-idle")

    # ─── Triggers → State ──────────────────────────────────────────
    # triggers.py publishes "trigger.fired"

    def _on_trigger_fired(event: Any) -> None:
        data = event.data
        state.update(Sections.SYSTEM, "last_trigger", data.get("name", ""))
        state.update(Sections.SYSTEM, "last_trigger_time", time.time())

    bus.subscribe("trigger.fired", _on_trigger_fired, name="cp-trigger")

    # ─── Voice → State ─────────────────────────────────────────────
    # voice.py publishes "voice.tts"

    def _on_voice_tts(event: Any) -> None:
        data = event.data
        state.update(Sections.VOICE, "last_tts_len", data.get("text_len", 0))
        state.update(Sections.VOICE, "last_tts_time", time.time())

    bus.subscribe("voice.tts", _on_voice_tts, name="cp-voice")

    # ─── Register Gaming Commands ──────────────────────────────────

    registry = get_command_registry()

    def _toggle_gaming() -> dict[str, Any]:
        from jarvis.core.gaming import toggle_gaming
        result = toggle_gaming()
        profile = result.get("profile", "normal")
        state.update(Sections.GAMING, "profile", profile)
        state.update(Sections.GAMING, "last_toggle", time.time())
        event = Events.GAMING_ENABLED if profile == "gaming" else Events.GAMING_DISABLED
        notifications.notify_event(event, {"profile": profile})
        return result

    def _get_gaming_status() -> dict[str, Any]:
        from jarvis.core.gaming import get_current_profile, get_gpu_state
        return {
            "profile": get_current_profile(),
            "gpu": get_gpu_state(),
        }

    registry.register(
        name="gaming.toggle",
        description="Toggle gaming mode on/off",
        risk=Risk.LOW,
        handler=_toggle_gaming,
        category="gaming",
    )
    registry.register(
        name="gaming.status",
        description="Get current gaming mode status",
        risk=Risk.SAFE,
        handler=_get_gaming_status,
        category="gaming",
    )

    # ─── Register Doctor Command ───────────────────────────────────

    def _run_doctor() -> dict[str, Any]:
        from jarvis.core.doctor import doctor_report
        from jarvis.core.config import get_config
        return doctor_report(get_config())

    registry.register(
        name="doctor.run",
        description="Run system health check",
        risk=Risk.SAFE,
        handler=_run_doctor,
        category="health",
    )

    # ─── Register Heal Command ─────────────────────────────────────

    def _run_heal() -> dict[str, Any]:
        from jarvis.core.heal import heal_report
        return heal_report(alerts=False)

    registry.register(
        name="heal.run",
        description="Run self-heal check and repair",
        risk=Risk.LOW,
        handler=_run_heal,
        category="health",
    )

    # ─── Register Idle Commands ────────────────────────────────────

    def _idle_status() -> dict[str, Any]:
        from jarvis.core.idle import IdleWorker, is_idle, user_is_idle
        import os
        worker = IdleWorker()
        due = worker.due_tasks()
        return {
            "idle": is_idle(),
            "load_1min": round(os.getloadavg()[0], 2),
            "logind_idle": user_is_idle(),
            "due_tasks": [t.name for t in due],
        }

    registry.register(
        name="idle.status",
        description="Get idle mode status",
        risk=Risk.SAFE,
        handler=_idle_status,
        category="system",
    )

    # ─── Register Voice Commands ───────────────────────────────────

    def _speak_text(text: str = "") -> dict[str, Any]:
        if not text:
            return {"error": "No text provided"}
        from jarvis.core.voice import speak
        result = speak(text, play=True)
        return {"success": not result.startswith("ERROR"), "result": result}

    registry.register(
        name="voice.speak",
        description="Speak text via TTS",
        risk=Risk.SAFE,
        handler=_speak_text,
        args_schema={"text": "Text to speak"},
        category="voice",
    )

    # ─── Register Task Commands ─────────────────────────────────────

    def _task_retry(task_id: str = "") -> dict[str, Any]:
        """Retry a failed task by resetting it to READY."""
        from pathlib import Path
        import json
        queue_file = Path.home() / ".local/state/jarvis/nightwatch" / "task_queue.json"
        if not queue_file.exists():
            return {"error": "No task queue found"}
        tasks = json.loads(queue_file.read_text(encoding="utf-8"))
        for t in tasks:
            if t["id"] == task_id:
                if t["status"] not in ("FAILED", "BLOCKED"):
                    return {"error": f"Cannot retry task in status {t['status']}"}
                t["status"] = "READY"
                t["attempts"] = 0
                t["last_error"] = None
                t["updated_at"] = time.time()
                # Atomic write
                tmp = queue_file.with_suffix(".tmp")
                tmp.write_text(json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8")
                tmp.rename(queue_file)
                return {"success": True, "task_id": task_id, "new_status": "READY"}
        return {"error": f"Task {task_id} not found"}

    def _task_cancel(task_id: str = "") -> dict[str, Any]:
        """Cancel/abandon a task."""
        from pathlib import Path
        import json
        queue_file = Path.home() / ".local/state/jarvis/nightwatch" / "task_queue.json"
        if not queue_file.exists():
            return {"error": "No task queue found"}
        tasks = json.loads(queue_file.read_text(encoding="utf-8"))
        for t in tasks:
            if t["id"] == task_id:
                if t["status"] in ("COMPLETED", "ABANDONED"):
                    return {"error": f"Task already {t['status']}"}
                t["status"] = "ABANDONED"
                t["last_error"] = "cancelled by user"
                t["updated_at"] = time.time()
                tmp = queue_file.with_suffix(".tmp")
                tmp.write_text(json.dumps(tasks, indent=2, ensure_ascii=False), encoding="utf-8")
                tmp.rename(queue_file)
                return {"success": True, "task_id": task_id, "new_status": "ABANDONED"}
        return {"error": f"Task {task_id} not found"}

    registry.register(
        name="task.retry",
        description="Retry a failed/blocked task",
        risk=Risk.LOW,
        handler=_task_retry,
        args_schema={"task_id": "Task ID to retry"},
        category="tasks",
    )
    registry.register(
        name="task.cancel",
        description="Cancel/abandon a task",
        risk=Risk.MEDIUM,
        handler=_task_cancel,
        requires_confirmation=True,
        args_schema={"task_id": "Task ID to cancel"},
        category="tasks",
    )

    # ─── Register RAG Commands ─────────────────────────────────────

    def _rag_search(query: str = "", top_k: int = 5) -> dict[str, Any]:
        from jarvis.core.rag import HybridSearch
        from jarvis.core.config import get_config
        search = HybridSearch(get_config())
        hits = search.search(query, top_k=top_k)
        return {
            "query": query,
            "hits": [
                {"path": h.path, "score": round(h.score, 4)}
                for h in hits
            ],
        }

    registry.register(
        name="rag.search",
        description="Search code index via RAG",
        risk=Risk.SAFE,
        handler=_rag_search,
        args_schema={"query": "Search query", "top_k": "Number of results"},
        category="rag",
    )

    # ─── Register Memory Commands ──────────────────────────────────

    def _memory_recall(query: str = "", top_k: int = 5) -> dict[str, Any]:
        from jarvis.core.memory import EpisodicMemory
        from jarvis.core.config import get_config
        mem = EpisodicMemory(get_config())
        hits = mem.recall(query, top_k=top_k)
        return {"query": query, "hits": hits}

    registry.register(
        name="memory.recall",
        description="Recall from episodic memory",
        risk=Risk.SAFE,
        handler=_memory_recall,
        args_schema={"query": "Search query", "top_k": "Number of results"},
        category="memory",
    )

    # ─── Harness/Agent → State ─────────────────────────────────────
    # harness.py publishes task lifecycle events via the global EventBus.
    # We subscribe to update the Agent section of StateStore.

    def _on_harness_task(event: Any) -> None:
        data = event.data
        event_type = data.get("event_type", "")
        task_id = data.get("task_id", "")

        if event_type == "task_started":
            state.update(Sections.AGENT, "active_task", task_id)
            state.update(Sections.AGENT, "active_persona", data.get("persona", ""))
            state.update(Sections.AGENT, "active_project", data.get("project", ""))
            state.update(Sections.AGENT, "status", "running")
            state.update(Sections.AGENT, "last_started", time.time())
            notifications.notify_event(Events.AGENT_TASK_STARTED, {
                "task_id": task_id,
                "description": data.get("description", ""),
            })
        elif event_type == "task_completed":
            state.update(Sections.AGENT, "active_task", "")
            state.update(Sections.AGENT, "status", "idle")
            state.update(Sections.AGENT, "last_completed", time.time())
            state.update(Sections.AGENT, "last_commit", data.get("commit", ""))
            notifications.notify_event(Events.AGENT_TASK_COMPLETED, {
                "task_id": task_id,
                "commit": data.get("commit", ""),
                "files": data.get("files", []),
            })
        elif event_type == "task_failed":
            state.update(Sections.AGENT, "active_task", "")
            state.update(Sections.AGENT, "status", "error")
            state.update(Sections.AGENT, "last_error", data.get("error", "")[:200])
            state.update(Sections.AGENT, "last_failed", time.time())
            notifications.notify_event(Events.AGENT_TASK_FAILED, {
                "task_id": task_id,
                "error": data.get("error", ""),
            })
        elif event_type == "loop_detected":
            state.update(Sections.AGENT, "status", "blocked")
            state.update(Sections.AGENT, "last_error", f"Loop detected: {task_id}")

    bus.subscribe("harness.task", _on_harness_task, name="cp-harness")

    # ─── Initial State Population ──────────────────────────────────
    # NOTE: No blocking HTTP calls at startup. Health state is populated
    # lazily when doctor.run command is executed or first doctor report
    # event arrives via EventBus.

    # Populate state from current gaming profile (fast, no I/O)
    try:
        from jarvis.core.gaming import get_current_profile
        state.update(Sections.GAMING, "profile", get_current_profile())
    except Exception:  # noqa: BLE001
        pass

    # Set health to unknown until first doctor report
    state.update(Sections.HEALTH, "overall", "unknown")
