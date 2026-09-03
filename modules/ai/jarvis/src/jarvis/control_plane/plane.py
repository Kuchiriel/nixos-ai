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

from jarvis.control_plane.events import Events, Severity, EventData
from jarvis.control_plane.state import StateStore, Sections, get_state_store
from jarvis.control_plane.commands import CommandRegistry, Risk, get_command_registry
from jarvis.control_plane.notifications import (
    NotificationManager, get_notification_manager,
)
from jarvis.core.eventbus import EventBus, Event, get_bus


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
        """Subscribe to EventBus events for state updates and notifications."""
        # Health events → state + notifications
        self.bus.subscribe("doctor.report", self._on_doctor_report)
        self.bus.subscribe("heal.service", self._on_heal_event)
        self.bus.subscribe("heal.recovered", self._on_heal_recovered)

        # Agent events → state + notifications
        self.bus.subscribe("orchestrator.agent.assigned", self._on_agent_assigned)

        # Idle events → state
        self.bus.subscribe("idle.task", self._on_idle_task)

        # Trigger events → state
        self.bus.subscribe("trigger.fired", self._on_trigger_fired)

        # Watchdog events → notifications
        self.bus.subscribe("watchdog.alert", self._on_watchdog_alert)

    def _setup_state_subscriptions(self) -> None:
        """Subscribe to state changes for derived state."""
        pass  # Will be used for derived state computation

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
            description="Get recent events from EventBus",
            risk=Risk.SAFE,
            handler=lambda: self.bus.stats,
            category="system",
        )

    # ─── Event Handlers ────────────────────────────────────────────

    def _on_doctor_report(self, event: Event) -> None:
        """Handle doctor report events."""
        data = event.data
        overall = data.get("overall", "ok")
        self.state.update(Sections.HEALTH, "overall", overall)
        self.state.update(Sections.HEALTH, "down", data.get("down", 0))
        self.state.update(Sections.HEALTH, "degraded", data.get("degraded", 0))

        # Route to notifications based on severity
        if overall == "down":
            self.notifications.notify_event(Events.DOCTOR_DOWN, data)
        elif overall == "degraded":
            self.notifications.notify_event(Events.DOCTOR_DEGRADED, data)
        else:
            self.notifications.notify_event(Events.DOCTOR_COMPLETED, data)

    def _on_heal_event(self, event: Event) -> None:
        """Handle heal events."""
        data = event.data
        service = data.get("service", "?")
        healed = data.get("healed", False)

        if healed:
            self.state.update(Sections.SERVICES, service, "active")
            self.notifications.notify_event(Events.HEAL_COMPLETED, {
                "service": service,
                "severity": Severity.SUCCESS,
            })
        else:
            self.state.update(Sections.SERVICES, service, "failed")
            self.notifications.notify_event(Events.HEAL_FAILED, {
                "service": service,
                "severity": Severity.ERROR,
            })

    def _on_heal_recovered(self, event: Event) -> None:
        """Handle service recovery events."""
        data = event.data
        service = data.get("service", "?")
        self.state.update(Sections.SERVICES, service, "active")
        self.notifications.notify_event(Events.HEAL_RECOVERED, {
            "service": service,
            "severity": Severity.SUCCESS,
        })

    def _on_agent_assigned(self, event: Event) -> None:
        """Handle agent assignment events."""
        data = event.data
        self.state.update(Sections.AGENT, "active_task", data.get("task_id", ""))
        self.state.update(Sections.AGENT, "active_persona", data.get("persona", ""))
        self.state.update(Sections.AGENT, "active_project", data.get("project", ""))

    def _on_idle_task(self, event: Event) -> None:
        """Handle idle task completion events."""
        data = event.data
        task_name = data.get("task", "?")
        ok = data.get("ok", False)
        self.state.update(Sections.SYSTEM, "last_idle_task", task_name)
        self.state.update(Sections.SYSTEM, "last_idle_ok", ok)

    def _on_trigger_fired(self, event: Event) -> None:
        """Handle trigger events."""
        data = event.data
        self.state.update(Sections.SYSTEM, "last_trigger", data.get("name", ""))

    def _on_watchdog_alert(self, event: Event) -> None:
        """Handle watchdog alerts."""
        data = event.data
        self.notifications.notify_event(Events.WATCHDOG_ALERT, data)

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
