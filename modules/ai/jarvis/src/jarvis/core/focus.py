"""Focus Manager — modo foco silencia notificações não-críticas.

Integra com EventBus e NotificationManager:
- Focus state persiste em /tmp/jarvis-focus-state
- NotificationManager verifica focus antes de deliverar
- dbus/systemd signals para mudanças de estado
- Toggle via jarvis focus command ou hyprkeybind

Uso:
    from jarvis.core.focus import FocusManager
    fm = FocusManager()
    fm.enable()   # Ativa modo foco
    fm.disable()  # Desativa modo foco
    fm.is_focus() # Verifica se está em foco
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


class FocusManager:
    """Gerenciador de modo foco.
    
    Quando ativo, silencia notificações com severity abaixo de WARNING.
    Notificações CRITICAL e ERROR ainda são entregues.
    """

    def __init__(self, bus: EventBus | None = None) -> None:
        self._state_file = FOCUS_STATE_FILE
        self._bus = bus or EventBus()
        self._focused = self._load_state()

    def _load_state(self) -> bool:
        """Carrega estado do arquivo."""
        try:
            if self._state_file.exists():
                data = json.loads(self._state_file.read_text())
                return data.get("focused", False)
        except (OSError, json.JSONDecodeError):
            pass
        return False

    def _save_state(self) -> None:
        """Salva estado no arquivo."""
        try:
            self._state_file.write_text(
                json.dumps({"focused": self._focused, "ts": time.time()})
            )
        except OSError:
            pass

    @property
    def focused(self) -> bool:
        """Retorna True se modo foco está ativo."""
        return self._focused

    def is_focus(self) -> bool:
        """Verifica se modo foco está ativo."""
        return self._focused

    def enable(self) -> None:
        """Ativa modo foco."""
        self._focused = True
        self._save_state()
        # Publica evento no bus
        self._bus.publish("focus.state.changed", {"focused": True, "action": "enable"})
        # dbus signal via systemd notification
        self._dbus_emit("FocusEnabled")
        # Sound feedback
        self._play_sound("info")

    def disable(self) -> None:
        """Desativa modo foco."""
        self._focused = False
        self._save_state()
        # Publica evento no bus
        self._bus.publish("focus.state.changed", {"focused": False, "action": "disable"})
        # dbus signal via systemd notification
        self._dbus_emit("FocusDisabled")
        # Sound feedback
        self._play_sound("success")

    def toggle(self) -> bool:
        """Toggle do modo foco. Retorna novo estado."""
        if self._focused:
            self.disable()
        else:
            self.enable()
        return self._focused

    def _dbus_emit(self, signal_name: str) -> None:
        """Emite sinal dbus via systemd-notify."""
        try:
            # Usa systemd NOTIFY_SOCKET para dbus-like signaling
            notify_socket = os.environ.get("NOTIFY_SOCKET")
            if notify_socket:
                # systemd watchdog — notifica que a unidade está pronta
                subprocess.run(
                    ["systemd-notify", "--status", f"Focus {signal_name}"],
                    capture_output=True, timeout=2,
                )
        except (OSError, subprocess.TimeoutExpired):
            pass

    def _play_sound(self, sound: str) -> None:
        """Toca som de feedback."""
        try:
            import shutil
            binary = shutil.which("paplay") or shutil.which("canberra-gtk-play")
            if binary:
                sound_path = Path(f"/run/current-system/sw/share/sounds/freedesktop/stereo/{sound}.oga")
                if not sound_path.exists():
                    # Busca no nix store
                    candidates = list(Path("/nix/store").glob(
                        f"*-sound-theme-freedesktop*/share/sounds/freedesktop/stereo/{sound}.oga"
                    ))
                    if candidates:
                        sound_path = candidates[0]
                if sound_path.exists():
                    subprocess.run([binary, str(sound_path)], capture_output=True, timeout=3)
        except (OSError, subprocess.TimeoutExpired):
            pass

    def should_deliver(self, severity: str = "info") -> bool:
        """Verifica se notificação deve ser entregue.
        
        Em modo foco: apenas CRITICAL e ERROR são entregues.
        Fora de foco: todas são entregues.
        """
        if not self._focused:
            return True
        return severity in ("critical", "error")


# ─── Singleton ──────────────────────────────────────────────────

_focus_manager: FocusManager | None = None


def get_focus_manager() -> FocusManager:
    """Get or create the global focus manager."""
    global _focus_manager
    if _focus_manager is None:
        _focus_manager = FocusManager()
    return _focus_manager


# ─── CLI Entry Point ────────────────────────────────────────────

def cli() -> None:
    """CLI para toggle/enable/disable focus mode."""
    import sys
    fm = get_focus_manager()
    
    cmd = sys.argv[1] if len(sys.argv) > 1 else "toggle"
    
    if cmd == "enable":
        fm.enable()
        print("Focus mode ENABLED. Notificações críticas apenas.")
    elif cmd == "disable":
        fm.disable()
        print("Focus mode DISABLED. Todas as notificações ativas.")
    elif cmd == "toggle":
        state = fm.toggle()
        print(f"Focus mode {'ENABLED' if state else 'DISABLED'}.")
    elif cmd == "status":
        print(f"Focus mode: {'ACTIVE' if fm.focused else 'INACTIVE'}")
        print(f"State file: {fm._state_file}")
    else:
        print(f"Usage: jarvis focus {{enable|disable|toggle|status}}. Current: {'ACTIVE' if fm.focused else 'INACTIVE'}")
