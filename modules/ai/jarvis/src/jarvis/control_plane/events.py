"""Event taxonomy — standardized event names and schemas.

All events follow the pattern: <domain>.<entity>.<action>

Examples:
    agent.task.started
    service.llama-cpp.restarted
    voice.tts.completed
    system.gaming.enabled

Usage:
    from jarvis.control_plane.events import Events, EventSchema

    bus.publish(Events.AGENT_TASK_STARTED, {
        "task_id": "abc123",
        "project": "nixos-ai",
        "persona": "backend_engineer",
    })
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


# ─── Event Names ───────────────────────────────────────────────────────

class Events:
    """All event names in the Jarvis system.

    Naming convention: <domain>.<entity>.<action>
    """

    # Agent lifecycle
    AGENT_TASK_STARTED = "agent.task.started"
    AGENT_TASK_PROGRESS = "agent.task.progress"
    AGENT_TASK_COMPLETED = "agent.task.completed"
    AGENT_TASK_FAILED = "agent.task.failed"
    AGENT_TASK_CANCELLED = "agent.task.cancelled"

    # Tool calls
    AGENT_TOOL_STARTED = "agent.tool.started"
    AGENT_TOOL_COMPLETED = "agent.tool.completed"
    AGENT_TOOL_FAILED = "agent.tool.failed"

    # Nightwatch
    NIGHTWATCH_STARTED = "nightwatch.started"
    NIGHTWATCH_COMPLETED = "nightwatch.completed"
    NIGHTWATCH_FAILED = "nightwatch.failed"
    NIGHTWATCH_CYCLE = "nightwatch.cycle"

    # Validation
    VALIDATION_STARTED = "validation.started"
    VALIDATION_PASSED = "validation.passed"
    VALIDATION_FAILED = "validation.failed"
    VALIDATION_ROLLBACK = "validation.rollback"

    # Services (systemd)
    SERVICE_STARTED = "service.started"
    SERVICE_STOPPED = "service.stopped"
    SERVICE_FAILED = "service.failed"
    SERVICE_RESTARTED = "service.restarted"

    # Health
    DOCTOR_COMPLETED = "doctor.completed"
    DOCTOR_DEGRADED = "doctor.degraded"
    DOCTOR_DOWN = "doctor.down"
    HEAL_STARTED = "heal.started"
    HEAL_COMPLETED = "heal.completed"
    HEAL_FAILED = "heal.failed"
    HEAL_RECOVERED = "heal.recovered"

    # Voice
    VOICE_LISTENING = "voice.listening"
    VOICE_TRANSCRIBING = "voice.transcribing"
    VOICE_THINKING = "voice.thinking"
    VOICE_SPEAKING = "voice.speaking"
    VOICE_COMPLETED = "voice.completed"
    VOICE_ERROR = "voice.error"

    # TTS
    TTS_STARTED = "tts.started"
    TTS_COMPLETED = "tts.completed"
    TTS_FAILED = "tts.failed"

    # Gaming
    GAMING_ENABLED = "system.gaming.enabled"
    GAMING_DISABLED = "system.gaming.disabled"

    # Idle
    IDLE_TASK_STARTED = "idle.task.started"
    IDLE_TASK_COMPLETED = "idle.task.completed"
    IDLE_TASK_FAILED = "idle.task.failed"

    # Triggers
    TRIGGER_FIRED = "trigger.fired"
    TRIGGER_FAILED = "trigger.failed"

    # Watchdog
    WATCHDOG_ALERT = "watchdog.alert"
    WATCHDOG_CYCLE = "watchdog.cycle"

    # Memory / RAG
    MEMORY_STORED = "memory.stored"
    MEMORY_RECALLED = "memory.recalled"
    RAG_SEARCHED = "rag.searched"

    # Audiobook
    AUDIOBOOK_PLAYING = "audiobook.playing"
    AUDIOBOOK_PAUSED = "audiobook.paused"
    AUDIOBOOK_STOPPED = "audiobook.stopped"

    # REPL / Dev
    REPL_OPENED = "repl.opened"
    REPL_COMMAND = "repl.command"
    REPL_CLOSED = "repl.closed"

    # System
    SYSTEM_BOOT = "system.boot"
    SYSTEM_SHUTDOWN = "system.shutdown"
    SYSTEM_ERROR = "system.error"

    # Notifications (meta)
    NOTIFICATION_CREATED = "notification.created"


# ─── Event Schema ──────────────────────────────────────────────────────

@dataclass
class EventData:
    """Standard fields for all events."""
    event: str
    ts: float = 0.0
    source: str = ""
    correlation_id: str = ""
    task_id: str = ""
    project: str = ""
    severity: str = "info"  # info | success | warning | error | critical
    data: dict[str, Any] = field(default_factory=dict)


# ─── Event Severity ────────────────────────────────────────────────────

class Severity:
    INFO = "info"
    SUCCESS = "success"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


# ─── Event → Notification Routing ──────────────────────────────────────

# Default routing: which events go to which channels
# Can be overridden by policy

DEFAULT_EVENT_ROUTES: dict[str, list[str]] = {
    # Agent events → WebUI + Desktop
    Events.AGENT_TASK_COMPLETED: ["web", "desktop"],
    Events.AGENT_TASK_FAILED: ["web", "desktop", "sound"],
    Events.AGENT_TASK_CANCELLED: ["web"],

    # Validation
    Events.VALIDATION_PASSED: ["web"],
    Events.VALIDATION_FAILED: ["web", "desktop", "sound"],
    Events.VALIDATION_ROLLBACK: ["web", "desktop"],

    # Services
    Events.SERVICE_FAILED: ["web", "desktop", "sound", "telegram"],
    Events.SERVICE_RESTARTED: ["web", "desktop"],

    # Health
    Events.DOCTOR_DEGRADED: ["web", "desktop"],
    Events.DOCTOR_DOWN: ["web", "desktop", "sound", "telegram"],
    Events.HEAL_COMPLETED: ["web", "desktop"],
    Events.HEAL_FAILED: ["web", "desktop", "sound", "telegram"],
    Events.HEAL_RECOVERED: ["web", "desktop"],

    # Voice
    Events.VOICE_LISTENING: ["waybar"],
    Events.VOICE_TRANSCRIBING: ["waybar"],
    Events.VOICE_THINKING: ["waybar"],
    Events.VOICE_SPEAKING: ["waybar"],
    Events.VOICE_COMPLETED: ["waybar"],
    Events.VOICE_ERROR: ["waybar", "desktop"],

    # Gaming
    Events.GAMING_ENABLED: ["web", "desktop", "sound"],
    Events.GAMING_DISABLED: ["web", "desktop", "sound"],

    # Idle
    Events.IDLE_TASK_COMPLETED: ["web"],

    # Nightwatch
    Events.NIGHTWATCH_COMPLETED: ["web", "desktop"],
    Events.NIGHTWATCH_FAILED: ["web", "desktop", "telegram"],

    # Watchdog
    Events.WATCHDOG_ALERT: ["web", "desktop", "telegram"],

    # System
    Events.SYSTEM_ERROR: ["web", "desktop", "sound", "telegram"],
}


def get_event_routes(event_name: str) -> list[str]:
    """Get the channels an event should be routed to."""
    return DEFAULT_EVENT_ROUTES.get(event_name, ["web"])
