"""Notification Manager — centralized event-to-channel routing.

Replaces scattered notify-send/paplay/Telegram calls with a single
event-driven notification system.

Architecture:
    EventBus event
        -> NotificationManager
            -> routes to channels based on severity/event type
            -> each channel adapter handles delivery
            -> audit trail of all notifications

Channels:
    web: WebUI (SSE/WebSocket)
    desktop: notify-send
    sound: canberra-gtk-play / paplay
    waybar: /tmp/jarvis-status.json
    telegram: Telegram bot
    voice: TTS (Kokoro)
    wav: pre-generated WAV files (fast, no TTS overhead)
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
from jarvis.core.eventbus import EventBus, Event
from jarvis.core.focus import get_focus_manager

STATUS_FILE = Path(os.environ.get("JARVIS_STATUS_FILE", "/tmp/jarvis-status.json"))
NOTIFY_LAST_FILE = Path(os.environ.get("JARVIS_NOTIFY_LAST", "/tmp/jarvis-notify-last.json"))


# ─── Notification ──────────────────────────────────────────────

@dataclass
class Notification:
    title: str
    body: str = ""
    severity: str = Severity.INFO
    channel: str = "web"
    source: str = ""
    ts: float = 0.0
    event: str = ""
    data: dict[str, Any] = field(default_factory=dict)


# ─── Channel Adapters ──────────────────────────────────────────

def _send_desktop(title: str, body: str, urgency: str = "normal") -> bool:
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
    _SOUNDS = {
        "success": "freedesktop/stereo/complete.oga",
        "error": "freedesktop/stereo/dialog-error.oga",
        "warning": "freedesktop/stereo/message.oga",
        "info": "freedesktop/stereo/service-login.oga",
    }
    sound_file = _SOUNDS.get(name, _SOUNDS["info"])
    for player in ("canberra-gtk-play", "paplay"):
        binary = shutil.which(player)
        if binary is None:
            continue
        sound_path = Path(f"/run/current-system/sw/share/sounds/{sound_file}")
        if not sound_path.exists():
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
    try:
        payload = {
            "state": state, "text": text,
            "ts": time.time(), "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        }
        STATUS_FILE.write_text(json.dumps(payload, ensure_ascii=False))
    except OSError:
        pass


def _send_telegram(message: str) -> bool:
    try:
        from jarvis.providers.telegram import send_notification
        return send_notification(message)
    except Exception:
        return False


def _speak(message: str) -> bool:
    try:
        from jarvis.core.voice import speak
        result = speak(message, play=True)
        return not result.startswith("ERROR")
    except Exception:
        return False


def _play_wav(wav_path: str) -> bool:
    """Play pre-generated WAV file (fast, no TTS overhead)."""
    try:
        binary = shutil.which("aplay") or shutil.which("paplay")
        if binary and os.path.exists(wav_path):
            subprocess.run([binary, "-q", wav_path], capture_output=True, timeout=5)
            return True
    except (OSError, subprocess.TimeoutExpired):
        pass
    return False


# ─── Severity -> Sound/Urgency Mapping ──────────────────────────

_SEVERITY_SOUNDS = {
    Severity.SUCCESS: "success", Severity.WARNING: "warning",
    Severity.ERROR: "error", Severity.CRITICAL: "error", Severity.INFO: "info",
}
_SEVERITY_URGENCY = {
    Severity.INFO: "low", Severity.SUCCESS: "normal",
    Severity.WARNING: "normal", Severity.ERROR: "critical", Severity.CRITICAL: "critical",
}
_SEVERITY_WAV = {
    Severity.CRITICAL: "critical", Severity.ERROR: "error",
    Severity.WARNING: "warning", Severity.INFO: "info", Severity.SUCCESS: "success",
}


# ─── Notification Manager ──────────────────────────────────────

class NotificationManager:
    """Centralized notification routing with EventBus integration."""

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus = bus or EventBus()
        self._channels: dict[str, Callable[[Notification], bool]] = {
            "desktop": self._deliver_desktop,
            "sound": self._deliver_sound,
            "waybar": self._deliver_waybar,
            "telegram": self._deliver_telegram,
            "voice": self._deliver_voice,
            "wav": self._deliver_wav,
            "web": self._deliver_web,
        }
        self._audit_log: list[dict[str, Any]] = []
        self._max_audit = 1000
        self._focus = get_focus_manager()
        self._subscribe_bus()

    def _subscribe_bus(self) -> None:
        """Subscribe to EventBus for automatic notification routing."""
        self._bus.subscribe_many([
            "watchdog.alert", "doctor.down", "doctor.degraded",
            "service.failed", "system.error", "trigger.fired",
            "battery.low", "battery.critical",
            "network.down", "network.up", "bluetooth.disconnect",
            "charger.connect", "charger.disconnect",
        ], self._on_event)

    def _on_event(self, event: Event) -> None:
        """Route EventBus events to NotificationManager."""
        self.notify_event(
            event_name=event.topic,
            data=event.data,
            title=event.data.get("title", ""),
            body=event.data.get("body", ""),
            severity=event.data.get("severity", Severity.INFO),
        )

    def notify_event(
        self, event_name: str, data: dict[str, Any] | None = None,
        *, title: str = "", body: str = "", severity: str = "",
    ) -> list[str]:
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
                title=title, body=body, severity=severity,
                channel=channel, source=data.get("source", ""),
                ts=time.time(), event=event_name, data=data,
            )
            if self._deliver(channel, notif):
                notified.append(channel)
        self._audit(event_name, notified, data)
        self._update_notify_last(event_name, severity, title)
        return notified

    def notify(
        self, title: str, body: str = "", severity: str = Severity.INFO,
        channels: list[str] | None = None,
    ) -> list[str]:
        if channels is None:
            channels = ["desktop", "web", "sound"]
        notified = []
        for channel in channels:
            notif = Notification(
                title=title, body=body, severity=severity,
                channel=channel, ts=time.time(),
            )
            if self._deliver(channel, notif):
                notified.append(channel)
        return notified

    def _deliver(self, channel: str, notif: Notification) -> bool:
        if not self._focus.should_deliver(notif.severity):
            return False
        handler = self._channels.get(channel)
        if handler is None:
            return False
        try:
            return handler(notif)
        except Exception:
            return False

    def _deliver_desktop(self, notif: Notification) -> bool:
        return _send_desktop(notif.title, notif.body, _SEVERITY_URGENCY.get(notif.severity, "normal"))

    def _deliver_sound(self, notif: Notification) -> bool:
        return _play_sound(_SEVERITY_SOUNDS.get(notif.severity, "info"))

    def _deliver_wav(self, notif: Notification) -> bool:
        """Deliver pre-generated WAV for fast audio notification."""
        severity_name = _SEVERITY_WAV.get(notif.severity, "info")
        wav_path = Path(f"/home/{os.environ.get('USER', 'nixos')}/.local/state/jarvis/notify-{severity_name}.wav")
        return _play_wav(str(wav_path))

    def _deliver_waybar(self, notif: Notification) -> bool:
        state_map = {
            Severity.INFO: "idle", Severity.SUCCESS: "done",
            Severity.WARNING: "error", Severity.ERROR: "error", Severity.CRITICAL: "error",
        }
        state = state_map.get(notif.severity, "idle")
        _update_waybar(state, notif.body or notif.title)
        return True

    def _deliver_telegram(self, notif: Notification) -> bool:
        if notif.severity not in (Severity.WARNING, Severity.ERROR, Severity.CRITICAL):
            return False
        msg = f"{notif.title}"
        if notif.body:
            msg += f"\n{notif.body}"
        return _send_telegram(msg)

    def _deliver_voice(self, notif: Notification) -> bool:
        if notif.severity not in (Severity.WARNING, Severity.ERROR, Severity.CRITICAL):
            return False
        return _speak(notif.body or notif.title)

    def _deliver_web(self, notif: Notification) -> bool:
        try:
            from jarvis.webui.api import _push_to_sse
            _push_to_sse({"type": "notification", "title": notif.title, "body": notif.body, "severity": notif.severity})
            return True
        except (ImportError, Exception):
            return False

    def _update_notify_last(self, event: str, priority: str, title: str) -> None:
        """Update notify-last.json for waybar notification module."""
        try:
            NOTIFY_LAST_FILE.write_text(json.dumps({
                "event": event, "priority": priority,
                "text": title, "focused": self._focus.focused,
                "ts": time.time(),
            }))
        except OSError:
            pass

    def _auto_body(self, event_name: str, data: dict[str, Any]) -> str:
        mapping = {
            "service.restarted": lambda d: f"Service {d.get('service','?')} restarted",
            "service.failed": lambda d: f"Service {d.get('service','?')} is down",
            "watchdog.alert": lambda d: d.get("message", "Watchdog alert"),
            "system.error": lambda d: d.get("error", "System error"),
            "battery.low": lambda d: "Battery low",
            "battery.critical": lambda d: "Battery critical",
            "network.down": lambda d: "Network lost",
            "network.up": lambda d: "Network restored",
        }
        if event_name in mapping:
            return mapping[event_name](data)
        return data.get("message", "")

    def _audit(self, event: str, channels: list[str], data: dict[str, Any]) -> None:
        entry = {"ts": time.time(), "event": event, "channels": channels, "data_keys": list(data.keys())}
        self._audit_log.append(entry)
        if len(self._audit_log) > self._max_audit:
            self._audit_log = self._audit_log[-self._max_audit:]


_manager: NotificationManager | None = None

def get_notification_manager() -> NotificationManager:
    global _manager
    if _manager is None:
        _manager = NotificationManager()
    return _manager
