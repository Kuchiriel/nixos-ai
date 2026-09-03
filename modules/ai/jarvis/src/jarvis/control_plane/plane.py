"""Control Plane — unified orchestration layer for Jarvis.

Ties together:
    - EventBus (events between components)
    - State Store (operational state)
    - Command Registry (typed operations)
    - Notification Manager (event → channel routing)
    - Systemd Adapter (safe service management)

This module initializes the Control Plane and provides the entry point
for all interfaces (CLI, WebUI, Telegram, Voice).
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from jarvis.control_plane.events import Events, Severity
from jarvis.control_plane.state import Sections, get_state_store
from jarvis.control_plane.commands import Risk, get_command_registry
from jarvis.control_plane.notifications import get_notification_manager
from jarvis.core.eventbus import Event, get_bus


class ControlPlane:
    """The Jarvis Control Plane.

    Initialization:
        plane = ControlPlane()
        plane.setup()  # wires EventBus → Notifications, registers commands

    After setup:
        - All components publish events via EventBus
        - Control Plane routes events to notifications and state updates
        - CLI/WebUI/Telegram/Voice all use CommandRegistry for operations
    """

    def __init__(self) -> None:
        self.bus = get_bus()
        self.state = get_state_store()
        self.commands = get_command_registry()
        self.notifications = get_notification_manager()
        self._systemd = None  # Lazy init
        self._event_history: list[dict[str, Any]] = []

    def setup(self) -> None:
        """Wire everything together."""
        self._setup_systemd()
        self._setup_event_subscriptions()
        self._setup_state_subscriptions()
        self._register_core_commands()
        self.state.update(Sections.SYSTEM, "boot_time", time.time())
        self.state.update(Sections.SYSTEM, "status", "running")

    def _setup_systemd(self) -> None:
        """Initialize systemd adapter (registers commands)."""
        from jarvis.control_plane.systemd_adapter import get_systemd_adapter
        self._systemd = get_systemd_adapter()

    def _setup_event_subscriptions(self) -> None:
        """Subscribe to EventBus events for state updates and notifications.

        NOTE: Component-specific subscriptions (doctor, heal, idle, triggers,
        voice) are handled by integration.py to avoid duplication.
        This method only handles Core-level subscriptions.
        """
        # Core event history — every published event gets recorded
        self.bus.subscribe("", self._record_event, name="cp-event-history")

    def _setup_state_subscriptions(self) -> None:
        """Subscribe to state changes for derived state."""
        pass

    def _register_core_commands(self) -> None:
        """Register core Control Plane commands."""
        self.commands.register(
            name="system.status",
            description="Get full system status",
            risk=Risk.SAFE,
            handler=self.get_full_status,
            category="system",
        )
        self.commands.register(
            name="system.state",
            description="Get current state snapshot",
            risk=Risk.SAFE,
            handler=self.state.get_state,
            category="system",
        )
        self.commands.register(
            name="system.events",
            description="Get recent event history",
            risk=Risk.SAFE,
            handler=self.get_event_history,
            category="system",
        )
        self.commands.register(
            name="system.event_stats",
            description="Get event bus statistics",
            risk=Risk.SAFE,
            handler=lambda: self.bus.stats,
            category="system",
        )

    # ─── Event History ─────────────────────────────────────────────

    def _record_event(self, event: Event) -> None:
        """Record every EventBus event to history."""
        entry = {
            "topic": event.topic,
            "ts": event.ts,
            "source": event.source,
            "data_keys": list(event.data.keys()) if event.data else [],
            "data_summary": self._summarize_event(event),
        }
        self._event_history.append(entry)
        # Keep last 500 events in memory
        if len(self._event_history) > 500:
            self._event_history = self._event_history[-500:]

    def _summarize_event(self, event: Event) -> str:
        """Create a human-readable summary of an event."""
        data = event.data or {}
        topic = event.topic
        if "service" in data:
            return f"{data['service']}"
        if "task" in data:
            return f"{data['task']}"
        if "name" in data:
            return f"{data['name']}"
        if "overall" in data:
            return f"{data['overall']}"
        return ""

    def get_event_history(self, limit: int = 100) -> list[dict[str, Any]]:
        """Get recent event history."""
        return list(self._event_history[-limit:])

    # ─── Full Status ───────────────────────────────────────────────

    def get_full_status(self) -> dict[str, Any]:
        """Get complete system status (for CLI/WebUI)."""
        state = self.state.get_state()
        bus_stats = self.bus.stats

        # Service statuses
        services = {}
        try:
            from jarvis.control_plane.systemd_adapter import get_systemd_adapter
            adapter = get_systemd_adapter()
            for name, status in adapter.get_all_status().items():
                services[name] = {
                    "active": status.active,
                    "enabled": status.enabled,
                    "status": status.status,
                }
        except Exception:
            pass

        return {
            "state": state,
            "events": bus_stats,
            "services": services,
            "timestamp": time.time(),
        }

    def __repr__(self) -> str:
        return (
            f"ControlPlane("
            f"bus={self.bus.stats}, "
            f"sections={len(self.state.get_state())}, "
            f"commands={len(self.commands.list_commands())}"
            f")"
        )


# ─── Singleton ─────────────────────────────────────────────────────────

_plane: ControlPlane | None = None


def get_control_plane() -> ControlPlane:
    """Get or create the global Control Plane."""
    global _plane
    if _plane is None:
        _plane = ControlPlane()
        _plane.setup()
    return _plane
