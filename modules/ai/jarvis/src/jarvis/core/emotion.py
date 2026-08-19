"""Detecção de emoção — porta do `emotional_state.py` do legado (Manjaro).

Inteligência barata (zero LLM): keywords PT/EN → perfil de resposta
(tone/speed/emoji) que o TTS Kokoro usa via `speed`. Estado persistente em
`~/.local/state/jarvis/emotion.json` com TTL de 5 min (como o legado).

Validado por pesquisa 2026: o Kokoro-82M aceita `speed` no pipeline — a
emoção vira prosódia sem modelos extras.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

STATE_TTL_SECONDS = 300  # 5 min (igual ao legado)

# Perfis: tone (texto), emoji (feedback visual), speed (prosódia Kokoro)
EMOTION_PROFILES: dict[str, dict[str, Any]] = {
    "neutral": {"tone": "professional", "emoji": "😊", "speed": 1.0},
    "concerned": {"tone": "supportive", "emoji": "🤔", "speed": 0.95},
    "positive": {"tone": "enthusiastic", "emoji": "😄", "speed": 1.1},
    "frustrated": {"tone": "empathetic", "emoji": "😢", "speed": 0.9},
    "urgent": {"tone": "focused", "emoji": "😡", "speed": 1.2},
}

# Keywords PT + EN (arrays inline, como os .rive do legado)
_URGENT = ("urgente", "rápido", "agora", "crítico", "erro grave", "já", "imediatamente", "urgent", "asap", "critical", "right now")
_FRUSTRATED = ("não funciona", "erro", "falhou", "problema", "quebrado", "de novo", "again", "broken", "failed", "not working")
_CONCERNED = ("ajuda", "preciso", "como faço", "não sei", "help", "need", "how do", "don't know")
_POSITIVE = ("obrigado", "ótimo", "legal", "bom", "perfeito", "excelente", "valeu", "thanks", "great", "awesome", "perfect", "excellent")


def _state_path() -> Path:
    base = os.environ.get("JARVIS_STATE_DIR", "")
    if base:
        return Path(base) / "emotion.json"
    return Path.home() / ".local" / "state" / "jarvis" / "emotion.json"


def detect_emotion(text: str) -> str:
    """Detecta a emoção do texto por keywords (ordem de prioridade do legado)."""
    low = text.lower()
    for name, keywords in (
        ("urgent", _URGENT),
        ("frustrated", _FRUSTRATED),
        ("concerned", _CONCERNED),
        ("positive", _POSITIVE),
    ):
        if any(k in low for k in keywords):
            return name
    return "neutral"


def profile(emotion: str | None = None) -> dict[str, Any]:
    """Perfil da emoção (default neutral)."""
    return EMOTION_PROFILES.get(emotion or "neutral", EMOTION_PROFILES["neutral"])


def get_state() -> dict[str, Any]:
    """Estado emocional persistente, com TTL de 5 min (reset para neutral)."""
    path = _state_path()
    if path.exists():
        try:
            data = json.loads(path.read_text())
            ts = datetime.fromisoformat(data["timestamp"])
            if (datetime.now(timezone.utc) - ts).total_seconds() <= STATE_TTL_SECONDS:
                return profile(data.get("emotion", "neutral"))
        except (OSError, ValueError, KeyError):
            pass
    return profile("neutral")


def update_state(user_input: str) -> dict[str, Any]:
    """Atualiza o estado emocional a partir da entrada do usuário (porta do legado)."""
    emotion = detect_emotion(user_input)
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "emotion": emotion,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }))
    except OSError:
        pass
    return profile(emotion)


def speed_for(text: str) -> float:
    """Speed do Kokoro para o texto (emoção → prosódia)."""
    return profile(detect_emotion(text))["speed"]


def main_emotion(argv: list[str] | None = None) -> int:
    """Entry point CLI: jarvis emotion [texto] — detecta/atualiza estado."""
    import argparse
    import sys

    parser = argparse.ArgumentParser(prog="jarvis emotion", description="Detecta emoção de um texto (keywords, zero LLM)")
    parser.add_argument("text", nargs="*", help="texto para detectar; sem texto, mostra o estado atual")
    args = parser.parse_args(argv)

    if args.text:
        text = " ".join(args.text)
        state = update_state(text)
        print(json.dumps({"emotion": detect_emotion(text), "profile": state}, ensure_ascii=False))
    else:
        print(json.dumps(get_state(), ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main_emotion())
