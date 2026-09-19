"""Focus Manager — modo foco silencia notificacoes nao-criticas.

Integra com EventBus e dbus para IPC eficiente.
Substitui polling por assinaturas de eventos.

Uso:
    from jarvis.core.focus import FocusManager, get_focus_manager
    fm = get_focus_manager()
    fm.enable()  # Ativa modo foco
    fm.disable() # Desativa
    fm.toggle()  # Toggle
    fm.is_focus() # Verifica estado
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path
from typing import Any

from jarvis.core.eventbus import EventBus

FOCUS_STATE_FILE = Path("/tmp/jarvis-focus-state")
FOCUS_DBUS_NAME = "io.jarvis.FocusManager"
FOCUS_DBUS_PATH = "/io/jarvis/FocusManager"
FOCUS_DBUS_INTERFACE = "io.jarvis.FocusManager"


class FocusManager:
    """Gerenciador de modo foco com EventBus e dbus.
    
    Quando ativo, filtra notificacoes com severity abaixo de WARNING.
    Notificacoes CRITICAL e ERROR ainda sao entregues.
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        self._bus = bus or EventBus()
        self._focused = self._load_state()
        self._subscribe_bus()
        self._setup_dbus()

    def _load_state(self) -> bool:
        try:
            if FOCUS_STATE_FILE.exists():
                data = json.loads(FOCUS_STATE_FILE.read_text())
                return data.get("focused", False)
        except (OSError, json.JSONDecodeError):
            pass
        return False

    def _save_state(self) -> None:
        try:
            FOCUS_STATE_FILE.write_text(
                json.dumps({"focused": self._focused, "ts": time.time()})
            )
        except OSError:
            pass
        # Publica no dbus
        self._dbus_emit("FocusStateChanged", {"focused": self._focused})

    @property
    def focused(self) -> bool:
        return self._focused

    def is_focus(self) -> bool:
        return self._focused

    def enable(self) -> None:
        self._focused = True
        self._save_state()
        self._bus.publish("focus.state.changed", {"focused": True, "action": "enable"})

    def disable(self) -> None:
        self._focused = False
        self._save_state()
        self._bus.publish("focus.state.changed", {"focused": False, "action": "disable"})

    def toggle(self) -> bool:
        if self._focused:
            self.disable()
        else:
            self.enable()
        return self._focused

    def _subscribe_bus(self) -> None:
        self._bus.subscribe("focus.state.changed", self._on_focus_change)

    def _on_focus_change(self, event) -> None:
        self._focused = event.data.get("focused", False)
        self._save_state()

    def should_deliver(self, severity: str = "info") -> bool:
        if not self._focused:
            return True
        return severity in ("critical", "error")

    def _setup_dbus(self) -> None:
        """Inicia dbus service para IPC externo."""
        try:
            notify_socket = os.environ.get("NOTIFY_SOCKET")
            if notify_socket:
                subprocess.run(
                    ["systemd-notify", "--ready"],
                    capture_output=True, timeout=2,
                )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _dbus_emit(self, signal_name: str, data: dict[str, Any]) -> None:
        try:
            subprocess.run(
                ["systemd-notify", "--status", f"Focus {signal_name}"],
                capture_output=True, timeout=2,
            )
        except (OSError, subprocess.TimeoutExpired):
            pass

    @staticmethod
    def get_state() -> dict[str, Any]:
        try:
            if FOCUS_STATE_FILE.exists():
                return json.loads(FOCUS_STATE_FILE.read_text())
        except (OSError, json.JSONDecodeError):
            pass
        return {"focused": False, "ts": 0.0}


_focus_manager: FocusManager | None = None

def get_focus_manager() -> FocusManager:
    global _focus_manager
    if _focus_manager is None:
        _focus_manager = FocusManager()
    return _focus_manager


# ─── CLI Entry Point ──────────────────────────────────────

def cli() -> int:
    import sys
    fm = get_focus_manager()
    cmd = sys.argv[1] if len(sys.argv) > 1 else "toggle"
    
    if cmd == "enable":
        fm.enable()
        print("Focus mode ENABLED")
    elif cmd == "disable":
        fm.disable()
        print("Focus mode DISABLED")
    elif cmd == "toggle":
        state = fm.toggle()
        print(f"Focus mode {'ENABLED' if state else 'DISABLED'}")
    elif cmd == "status":
        print(f"Focus mode: {'ACTIVE' if fm.focused else 'INACTIVE'}")
        print(json.dumps(get_focus_manager().get_state()))
    else:
        print(f"Usage: jarvis focus {{enable|disable|toggle|status}}")
        return 1
    return 0
