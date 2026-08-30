"""Feedback ao usuário — porta do legado (waybar-jarvis-status + notificações).

O legado (Manjaro) mostrava o estado da pipeline de voz no Waybar via
`/tmp/jarvis-status.json` (idle/listening/transcribing/thinking/speaking/
error), com emojis e cores, além de notificações. Este módulo generaliza:

  - `set_status(state, text)` — escreve /tmp/jarvis-status.json (qualquer
    processo do JARVIS pode atualizar; o Waybar lê e estiliza).
  - `notify(title, body)` — notificação via notify-send (fallback silencioso).
  - `play_sound(name)` — som de feedback (wake/erro/sucesso) via
    canberra-gtk-play ou paplay.

Estados padrão (mesma semântica do legado):
  idle | listening | transcribing | thinking | speaking | error | done
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from typing import Any

STATUS_FILE = Path(os.environ.get("JARVIS_STATUS_FILE", "/tmp/jarvis-status.json"))

# Sons de feedback (mapeia nome → arquivo de som)
_SOUNDS: dict[str, str] = {
    "wake": "freedesktop/stereo/service-login.oga",
    "error": "freedesktop/stereo/dialog-error.oga",
    "success": "freedesktop/stereo/complete.oga",
    "notification": "freedesktop/stereo/message.oga",
}


def set_status(state: str, text: str = "", **extra: Any) -> None:
    """Escreve o status compartilhado (Waybar lê e estiliza)."""
    payload: dict[str, Any] = {
        "state": state,
        "text": text,
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        **extra,
    }
    try:
        STATUS_FILE.write_text(json.dumps(payload, ensure_ascii=False))
    except OSError:
        pass


def get_status() -> dict[str, Any]:
    try:
        return json.loads(STATUS_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {"state": "idle", "text": ""}


def clear_status() -> None:
    set_status("idle", "")


def notify(title: str, body: str = "", urgency: str = "normal") -> bool:
    """Notificação via notify-send. Retorna True se enviou."""
    binary = shutil.which("notify-send")
    if binary is None:
        return False
    try:
        subprocess.run(
            [binary, "-u", urgency, title, body],
            capture_output=True, timeout=5,
        )
        return True
    except (OSError, subprocess.TimeoutExpired):
        return False


def play_sound(name: str, sound_theme: str | None = None) -> bool:
    """Toca um som de feedback. Retorna True se tocou."""
    if name not in _SOUNDS:
        return False
    theme = sound_theme or "/run/current-system/sw/share/sounds"
    sound_path = Path(theme) / _SOUNDS[name]
    if not sound_path.exists():
        # fallback: procura no nix store do sound-theme-freedesktop
        candidates = sorted(Path("/nix/store").glob("*-sound-theme-freedesktop*/share/sounds/*"))
        if candidates:
            sound_path = candidates[0] / _SOUNDS[name]
    if not sound_path.exists():
        return False
    for player in ("canberra-gtk-play", "paplay"):
        binary = shutil.which(player)
        if binary is None:
            continue
        try:
            args = [binary, "--file", str(sound_path)] if player == "canberra-gtk-play" else [binary, str(sound_path)]
            subprocess.run(args, capture_output=True, timeout=5)
            return True
        except (OSError, subprocess.TimeoutExpired):
            continue
    return False


def waybar_format() -> dict[str, Any]:
    """Formato JSON para o module custom/jarvis do Waybar (porta do legado).

    Ícones minimalistas Nerd Font estilo cyberpunk (cyan).
    """
    import re

    status = get_status()
    state = status.get("state", "idle")
    text = status.get("text", "")

    # Remove Nerd Font glyphs e emoji do text (evita duplicação)
    # NF Private Use: U+E000-U+F8FF | NF Supplementary: U+F0000+ | Emoji: U+1F300+
    nf_emoji_re = re.compile(
        r'['
        r'\U0000E000-\U0000F8FF'   # BMP Private Use (Nerd Font)
        r'\U000F0000-\U000FFFFF'   # Supplementary Private Use Area-A
        r'\U00100000-\U0010FFFF'   # Supplementary Private Use Area-B
        r'\U0001F300-\U0001F9FF'   # Emoticons + Misc Symbols
        r'\u2600-\u27BF'           # Misc Symbols + Dingbats
        r']'
    )
    text_clean = nf_emoji_re.sub('', text).strip()

    # Ícones + labels Nerd Font (cyberpunk)
    # Formato: ícone + label curto visível na barra
    state_map = {
        "idle":          ("󰆪", "IDLE"),
        "listening":     ("󰍬", "REC"),
        "transcribing":  ("󰈙", "STT"),
        "thinking":      ("󰐕", "..."),
        "speaking":      ("󰕾", "TTS"),
        "error":         ("󰅙", "ERR"),
        "done":          ("󰄬", "OK"),
        "initializing":  ("󰚌", "INIT"),
    }
    icon, label = state_map.get(state, ("󰆪", state.upper()))

    # Show icon + short label in the bar; full text in tooltip
    display = f"{icon} {label}"
    detail = text_clean or text

    return {
        "text": display,
        "tooltip": f"{state}: {detail}",
        "class": state,
        "alt": state,
    }
