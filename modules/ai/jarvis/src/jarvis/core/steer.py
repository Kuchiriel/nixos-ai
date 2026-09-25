"""Steering — redirecionar (ou parar) um run no meio, até pelo celular.

Arquivo bem-conhecido (não socket, não thread): qualquer processo com
acesso ao STATE_DIR escreve, o loop do Agent lê no topo de cada turno.
Origens: terminal (`echo msg > $JARVIS_STATE_DIR/steer.md`), Telegram
(`/steer`, `/stop`), vault. Consumo é destrutivo (lê+limpa) — cada
mensagem entra exatamente 1x.

STOP: conteúdo `stop` (case-insensitive, sozinho) encerra o run com
veredito honesto (não crash, não STUCK falso).
"""

from __future__ import annotations

import os
from pathlib import Path

STOP_WORDS = frozenset({"stop", "/stop", "para", "pare"})


def steer_path() -> Path:
    base = os.environ.get("JARVIS_STATE_DIR") or str(
        Path.home() / ".local" / "state" / "jarvis")
    return Path(base) / "steer.md"


def send_steer(message: str) -> dict:
    """Enfileira steering p/ o run ativo (append; criado se ausente)."""
    message = (message or "").strip()
    if not message:
        return {"ok": False, "error": "mensagem vazia"}
    p = steer_path()
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a", encoding="utf-8") as f:
            f.write(message + "\n")
        return {"ok": True, "path": str(p)}
    except OSError as e:
        return {"ok": False, "error": f"steer falhou: {e}"}


def check_steer() -> str | None:
    """Lê+limpa steering pendente (None = nada)."""
    p = steer_path()
    try:
        if not p.exists():
            return None
        text = p.read_text(encoding="utf-8").strip()
        p.unlink(missing_ok=True)
        return text or None
    except OSError:
        return None


def is_stop(message: str) -> bool:
    """Conteúdo é ordem de parada?"""
    return (message or "").strip().lower() in STOP_WORDS
