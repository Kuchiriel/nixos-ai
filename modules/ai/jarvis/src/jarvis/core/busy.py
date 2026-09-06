"""Load shedding — detecta quando o LLM está sobrecarregado e responde sem LLM.

Melhores práticas (referência: Release It!, Nygard):
  1. **Check before call**: verifica /slots antes de enviar prompt
  2. **Circuit breaker**: se o servidor falhou 4x seguidas, desiste por 15s
  3. **Graceful degradation**: fastpath ou resposta "busy" via TTS
  4. **Feedback loop**: notifica o usuário via feedback.py (waybar + som)

Fluxo no voice_loop:
  transcribe → is_busy? → S/TTS("Estou ocupado") : roteador → LLM → TTS
"""

from __future__ import annotations

import time
from typing import Any

from jarvis.core.feedback import set_status


# Respostas busy pré-definidas (variações para não repetir sempre)
_BUSY_RESPONSES = [
    "Estou processando outra tarefa. Tente daqui a pouco.",
    "O modelo está ocupado no momento. Aguarde um instante.",
    "Sistema sobrecarregado. Tente novamente em breve.",
    "Estou com a fila cheia. Que tal daqui a uns minutos?",
]


def _busy_response() -> str:
    """Resposta busy variada (não repete a mesma toda vez)."""
    idx = int(time.time()) % len(_BUSY_RESPONSES)
    return _BUSY_RESPONSES[idx]


def check_load(
    llm_client: Any,
    *,
    ctx_threshold: float = 80.0,
) -> dict[str, Any]:
    """Verifica a carga do LLM e retorna status detalhado.

    Returns:
        {
            "busy": bool,
            "reason": str,
            "slots": {...},  # detalhes do /slots
            "response": str,  # resposta para o usuário (se busy)
        }
    """
    slots = llm_client.get_slots_status()
    busy = llm_client.is_busy(ctx_threshold=ctx_threshold)

    if not busy:
        return {"busy": False, "reason": "", "slots": slots, "response": ""}

    # Determina o motivo
    if not slots:
        reason = "servidor inalcançável"
    elif slots.get("slots_busy", 0) >= slots.get("slots_total", 1):
        reason = f"todos os {slots['slots_total']} slots ocupados"
    elif slots.get("ctx_pct", 0) > ctx_threshold:
        reason = f"contexto em {slots['ctx_pct']:.0f}%"
    else:
        reason = "circuit breaker aberto"

    return {
        "busy": True,
        "reason": reason,
        "slots": slots,
        "response": _busy_response(),
    }


def handle_busy(load_status: dict[str, Any], *, tts: bool = True) -> int:
    """Processa resposta busy: feedback visual + TTS + log.

    Retorna 0 (sucesso — o usuário foi informado).
    """
    response = load_status["response"]
    reason = load_status["reason"]

    # Atualiza waybar (feedback visual)
    set_status("busy", f"Sobrecarregado: {reason}")

    # Log
    from jarvis.core.logging import get_logger
    log = get_logger("busy")
    log.warn("load_shed", detail={
        "reason": reason,
        "slots": load_status.get("slots", {}),
    })

    # TTS
    if tts:
        from jarvis.core.voice import speak
        wav = speak(response)
        if wav.startswith("ERROR"):
            print(f"[busy] TTS falhou: {wav}", flush=True)
        else:
            print(f"[busy] 🔊 {response}", flush=True)
    else:
        print(f"[busy] 💬 {response}", flush=True)

    # Limpa status após 3s
    time.sleep(3)
    set_status("idle", "")

    return 0
