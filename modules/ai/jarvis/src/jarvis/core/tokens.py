"""Abstração de contagem de tokens — interface única p/ jarvis + outros CLIs.

Hierarquia (audit §3.5 — nunca heurística cega quando há dado real):
  1. API `usage.prompt_tokens` (via record_pair / SessionTelemetry)
  2. llama.cpp `/slots` (via ContextBudget.sync_from_slots)
  3. tokenizer real (quando disponível — hook futuro)
  4. heurística calibrada `chars / (4 * ratio)` — fallback grosseiro

Uso por outros CLIs:
  python -m jarvis.core.tokens --text "..."
  python -m jarvis.core.tokens --messages msgs.json
  from jarvis.core.tokens import estimate, estimate_messages, calibrate

Toda estimativa pública do repo deve passar por este módulo
(ContextBudget.estimate_tokens e dev.py:_estimate_tokens delegam p/ cá).
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any

# Heurística base (~4 chars/token p/ tokenizers GPT-like). Nunca usada pura:
# estimate() aplica a calibração acumulada via calibrate().
CHARS_PER_TOKEN = 4

# Calibração global do processo: soma pareada estimado×real.
_est_total: int = 0
_real_total: int = 0


def calibration_ratio() -> float:
    """Razão estimado/real — 1.0 sem amostras (heurística pura)."""
    if _real_total <= 0 or _est_total <= 0:
        return 1.0
    return min(3.0, max(0.33, _est_total / _real_total))


def calibrate(text: str, real_tokens: int) -> None:
    """Pareia uma estimativa com o valor real (ex: usage.prompt_tokens)."""
    global _est_total, _real_total
    if real_tokens > 0 and text:
        _est_total += max(1, len(text) // CHARS_PER_TOKEN)
        _real_total += real_tokens


def estimate(text: str) -> int:
    """Estima tokens de um texto (heurística calibrada, mínimo 1)."""
    if not text:
        return 1
    return max(1, int(len(text) // (CHARS_PER_TOKEN * calibration_ratio())))


def _message_text(msg: dict[str, Any]) -> str:
    content = msg.get("content", "")
    if isinstance(content, list):
        return " ".join(p.get("text", "") for p in content if isinstance(p, dict))
    return content if isinstance(content, str) else str(content)


def estimate_messages(messages: list[dict[str, Any]]) -> int:
    """Estima tokens de uma lista de mensagens (inclui tool_calls)."""
    total = 0
    for msg in messages:
        total += estimate(_message_text(msg))
        for tc in msg.get("tool_calls") or []:
            func = tc.get("function", {}) if isinstance(tc, dict) else {}
            total += estimate(func.get("name", ""))
            total += estimate(func.get("arguments", ""))
    return total


def stats() -> dict[str, Any]:
    """Estado da calibração (p/ debug e /stats)."""
    return {
        "ratio": round(calibration_ratio(), 3),
        "est_total": _est_total,
        "real_total": _real_total,
        "pairs": _est_total > 0 and _real_total > 0,
    }


def _reset() -> None:
    """Zera a calibração — hook EXCLUSIVO p/ testes (isolamento)."""
    global _est_total, _real_total
    _est_total = 0
    _real_total = 0


def main(argv: list[str] | None = None) -> int:
    """CLI: outros CLIs usam sem importar (ex: aider, opencode hooks)."""
    ap = argparse.ArgumentParser(description="Contagem de tokens do jarvis")
    ap.add_argument("--text", default="", help="texto para estimar")
    ap.add_argument("--messages", default="", help="JSON array de mensagens")
    ap.add_argument("--stats", action="store_true", help="mostra calibração")
    args = ap.parse_args(argv)
    if args.stats:
        print(json.dumps(stats()))
        return 0
    if args.messages:
        try:
            msgs = json.loads(args.messages)
        except ValueError as exc:
            print(json.dumps({"error": f"JSON inválido: {exc}"}))
            return 1
        print(json.dumps({"tokens": estimate_messages(msgs)}))
        return 0
    print(json.dumps({"tokens": estimate(args.text)}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
