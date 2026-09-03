"""Notification Manager — centralized event-to-channel routing.

Replaces scattered notify-send/paplay/Telegram calls with a single
event-driven notification system.

Architecture:
    EventBus event
        → NotificationManager
            → routes to channels based on severity/event type
            → each channel adapter handles delivery
            → audit trail of all notifications

Channels:
    web: WebUI (SSE/WebSocket)
    desktop: notify-send
    sound: canberra-gtk-play / paplay
    waybar: /tmp/jarvis-status.json
    telegram: Telegram bot
    voice: TTS (Kokoro)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from jarvis.control_plane.events import Events, Severity, get_event_routes


# ─── Notification ──────────────────────────────────────────────────────

@dataclass
class Notification:
    """A single notification to be delivered."""
    title: str
    body: str = ""
    severity: str = Severity.INFO
    channel: str = "web"
    source: str = ""
    ts: float = 0.0
    event: str = ""
    data: dict[str, Any] = field(default_factory=dict)


# ─── Channel Adapters ──────────────────────────────────────────────────

def _send_desktop(title: str, body: str, urgency: str = "normal") -> bool:
    """Send desktop notification via notify-send."""
    binary = shutil.which("notify-send")
    if binary is None:
        return False
    try:
        subprocess.run(
            [binary, "-u", urgency, "-t", "5000", title, body],
            capture_output=True, timeout=5,
        )
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def _play_sound(name: str) -> bool:
    """Play a notification sound."""
    _SOUNDS = {
        "success": "freedesktop/stereo/complete.oga",
        "error": "freedesktop/stereo/dialog-error.oga",
        "warning": "freedesktop/stereo/message.oga",
        "info": "freedesktop/stereo/service-login.oga",
    }
    sound_file = _SOUNDS.get(name, _SOUNDS["info"])

    # Try multiple sound players
    for player in ("canberra-gtk-play", "paplay"):
        binary = shutil.which(player)
        if binary is None:
            continue
        sound_path = Path(f"/run/current-system/sw/share/sounds/{sound_file}")
        if not sound_path.exists():
            # Fallback: search nix store
            candidates = sorted(Path("/nix/store").glob(
                f"*-sound-theme-freedesktop*/share/sounds/{sound_file}"
            ))
            if candidates:
                sound_path = candidates[0]
            else:
                continue
        try:
            args = (
                [binary, "--file", str(sound_path)]
                if player == "canberra-gtk-play"
                else [binary, str(sound_path)]
            )
            subprocess.run(args, capture_output=True, timeout=5)
            return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False


def _update_waybar(state: str, text: str = "") -> None:
    """Update Waybar status via feedback.py's STATUS_FILE."""
    try:
        status_file = Path(os.environ.get(
            "JARVIS_STATUS_FILE", "/tmp/jarvis-status.json"
        ))
        payload = {
            "state": state,
            "text": text,
            "ts": time.time(),
            "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        status_file.write_text(json.dumps(payload, ensure_ascii=False))
    except OSError:
        pass


def _send_telegram(message: str) -> bool:
    """Send Telegram notification."""
    try:
        from jarvis.providers.telegram import send_notification
        return send_notification(message)
    except Exception:
        return False


def _speak(message: str) -> bool:
    """Speak via TTS."""
    try:
        from jarvis.core.voice import speak
        result = speak(message, play=True)
        return not result.startswith("ERROR")
    except Exception:
        return False


# ─── Severity → Sound Mapping ──────────────────────────────────────────

_SEVERITY_SOUNDS = {
    Severity.SUCCESS: "success",
    Severity.WARNING: "warning",
    Severity.ERROR: "error",
    Severity.CRITICAL: "error",
    Severity.INFO: "info",
}

# ─── Severity → Desktop Urgency ────────────────────────────────────────

_SEVERITY_URGENCY = {
    Severity.INFO: "low",
    Severity.SUCCESS: "normal",
    Severity.WARNING: "normal",
    Severity.ERROR: "critical",
    Severity.CRITICAL: "critical",
}


# ─── Notification Manager ─────────────────────────────────────────────

class NotificationManager:
    """Centralized notification routing.

    Subscribes to EventBus and routes events to appropriate channels
    based on severity and event type.

    Usage:
        manager = NotificationManager()
        # Auto-routes an event to appropriate channels
        manager.notify_event(Events.AGENT_TASK_COMPLETED, {
            "task_id": "abc", "project": "nixos-ai"
        })

        # Direct notification
        manager.notify("JARVIS", "Service restarted", severity=Severity.SUCCESS)
    """

    def __init__(self) -> None:
        self._channels: dict[str, Callable[[Notification], bool]] = {
            "desktop": self._deliver_desktop,
            "sound": self._deliver_sound,
            "waybar": self._deliver_waybar,
            "telegram": self._deliver_telegram,
            "voice": self._deliver_voice,
            "web": self._deliver_web,
        }
        self._audit_log: list[dict[str, Any]] = []
        self._max_audit = 1000

    def notify_event(
        self,
        event_name: str,
        data: dict[str, Any] | None = None,
        *,
        title: str = "",
        body: str = "",
        severity: str = "",
    ) -> list[str]:
        """Route an event to appropriate notification channels.

        Returns list of channels that were notified.
        """
        data = data or {}
        channels = get_event_routes(event_name)

        if not severity:
            severity = data.get("severity", Severity.INFO)

        if not title:
            title = event_name.replace(".", " ").title()

        if not body:
            body = self._auto_body(event_name, data)

        notified = []
        for channel in channels:
            notif = Notification(
                title=title,
                body=body,
                severity=severity,
                channel=channel,
                source=data.get("source", ""),
                ts=time.time(),
                event=event_name,
                data=data,
            )
            if self._deliver(channel, notif):
                notified.append(channel)

        self._audit(event_name, notified, data)
        return notified

    def notify(
        self,
        title: str,
        body: str = "",
        severity: str = Severity.INFO,
        channels: list[str] | None = None,
    ) -> list[str]:
        """Send a direct notification to specific channels."""
        if channels is None:
            channels = ["desktop", "web"]

        notified = []
        for channel in channels:
            notif = Notification(
                title=title,
                body=body,
                severity=severity,
                channel=channel,
                ts=time.time(),
            )
            if self._deliver(channel, notif):
                notified.append(channel)
        return notified

    def _deliver(self, channel: str, notif: Notification) -> bool:
        """Deliver to a specific channel."""
        handler = self._channels.get(channel)
        if handler is None:
            return False
        try:
            return handler(notif)
        except Exception:
            return False

    def _deliver_desktop(self, notif: Notification) -> bool:
        urgency = _SEVERITY_URGENCY.get(notif.severity, "normal")
        return _send_desktop(notif.title, notif.body, urgency)

    def _deliver_sound(self, notif: Notification) -> bool:
        sound_name = _SEVERITY_SOUNDS.get(notif.severity, "info")
        return _play_sound(sound_name)

    def _deliver_waybar(self, notif: Notification) -> bool:
        state_map = {
            Severity.INFO: "idle",
            Severity.SUCCESS: "done",
            Severity.WARNING: "error",
            Severity.ERROR: "error",
            Severity.CRITICAL: "error",
        }
        state = state_map.get(notif.severity, "idle")
        _update_waybar(state, notif.body or notif.title)
        return True

    def _deliver_telegram(self, notif: Notification) -> bool:
        if notif.severity not in (Severity.WARNING, Severity.ERROR, Severity.CRITICAL):
            return False  # Don't spam Telegram for info/success
        msg = f"{notif.title}"
        if notif.body:
            msg += f"\n{notif.body}"
        return _send_telegram(msg)

    def _deliver_voice(self, notif: Notification) -> bool:
        if notif.severity not in (Severity.WARNING, Severity.ERROR, Severity.CRITICAL):
            return False  # Don't speak for info/success
        return _speak(notif.body or notif.title)

    def _deliver_web(self, notif: Notification) -> bool:
        """Web delivery — stub for now (WebUI will consume via SSE)."""
        # Will be connected to SSE/WebSocket later
        return True

    def _auto_body(self, event_name: str, data: dict[str, Any]) -> str:
        """Auto-generate body text from event data."""
        if event_name == Events.SERVICE_RESTARTED:
            return f"Service {data.get('service', '?')} restarted"
        elif event_name == Events.SERVICE_FAILED:
            return f"Service {data.get('service', '?')} is down"
        elif event_name == Events.AGENT_TASK_COMPLETED:
            return f"Task {data.get('task_id', '?')} completed on {data.get('project', '?')}"
        elif event_name == Events.AGENT_TASK_FAILED:
            return f"Task {data.get('task_id', '?')} failed: {data.get('error', '?')}"
        elif event_name == Events.GAMING_ENABLED:
            return "Gaming mode activated — heavy services paused"
        elif event_name == Events.GAMING_DISABLED:
            return "Normal mode restored"
        elif event_name == Events.DOCTOR_DEGRADED:
            return f"System degraded: {data.get('degraded', '?')}"
        elif event_name == Events.DOCTOR_DOWN:
            return f"System DOWN: {data.get('down', '?')}"
        elif event_name == Events.HEAL_COMPLETED:
            return f"Heal completed: {data.get('service', '?')} restored"
        elif event_name == Events.HEAL_FAILED:
            return f"Heal failed: {data.get('service', '?')} could not be restored"
        elif event_name == Events.NIGHTWATCH_COMPLETED:
            return f"Nightwatch completed: {data.get('tasks_completed', 0)} tasks"
        elif event_name == Events.WATCHDOG_ALERT:
            return data.get("message", "Watchdog alert")
        elif event_name == Events.SYSTEM_ERROR:
            return data.get("error", "System error")
        return data.get("message", "")

    def _audit(self, event: str, channels: list[str], data: dict[str, Any]) -> None:
        """Log notification to audit trail."""
        entry = {
            "ts": time.time(),
            "event": event,
            "channels": channels,
            "data_keys": list(data.keys()),
        }
        self._audit_log.append(entry)
        if len(self._audit_log) > self._max_audit:
            self._audit_log = self._audit_log[-self._max_audit:]


# ─── Singleton ─────────────────────────────────────────────────────────

_manager: NotificationManager | None = None


def get_notification_manager() -> NotificationManager:
    """Get or create the global notification manager."""
    global _manager
    if _manager is None:
        _manager = NotificationManager()
    return _manager
