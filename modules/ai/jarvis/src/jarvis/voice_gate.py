"""Gate de endereçamento da voz (a decisão "respondo ou não?").

Problema medido (03/11, `docs/auditoria/LAYA-GATE-2026-11-03.md`): com
`GATE_MODE="on"`, a voz só respondia quando a fala continha a palavra
"Jarvis" (heurística de string) → **recall 15,4%** (11 de 13 pedidos do dono
descartados). O sintoma do dono: *"o JARVIS ignora quase tudo e raramente
responde"*.

Este módulo é a **decisão**, pura e testável (sem I/O, sem modelo): quem
chama passa os rótulos que já sabe calcular (o LoRA `classify_turn` e o
intent `classify_intent`) e recebe a decisão + o motivo, auditável.

Forma da decisão (inspirada em arXiv:2609.27037, "intelligent wakeup"):
o paper modela o wakeup como **classificação de turno** com três classes —
invocação direta, ativação contextual (follow-up sem palavra-chave) e fala
não endereçada — e mede que o **erro restante está na classe contextual**
(direct recall ≈ 0,99; contextual recall ≤ 0,794). O mesmo paper mostra que
um LLM puro **sobre-ativa** (gpt-realtime-mini: recall 0,993 com **F1 0,179**
— milliona os 3 348 turnos não endereçados). Daí a estrutura: a decisão exige
o **LoRA** (âncora de precisão) **e** um sinal semântico (contexto).

Medido no nosso dataset (27 falas PT-BR, `benchmarks/voice/bench_gate.py`):

| gate | recall | F1 | FP |
|---|---|---|---|
| `explicit` (o de hoje) | 0,154 | 0,267 | 0 |
| `intent` (sozinho) | 0,923 | 0,857 | 3 |
| `lora_and_addr_or_intent` (este módulo) | **0,923** | **0,889** | **2** |

Regra de ouro: **nunca piorar o que já funciona** — se o classificador de
intenção falhar, o módulo degrada (motivo `degraded-no-intent`) em vez de
voltar ao gate que descarta 11 de 13 pedidos.
"""

from __future__ import annotations

import difflib
from dataclasses import dataclass, field

# Rótulos do classificador de turno (LoRA micro-turn).
LORA_RESPOND = "RESPOND"
LORA_WAIT = "WAIT"
LORA_SILENCE = "SILENCE"
LORA_BARGE = "BARGE"

# Intenções que pedem resposta (GBNF do classificador de intenção).
REQUEST_INTENTS = ("QUESTION", "COMMAND")

# Motivos possíveis (auditoria: o log precisa dizer POR QUE não respondeu).
REASON_EXPLICIT = "explicit-address"          # a pessoa disse "Jarvis"
REASON_CONTEXTUAL = "contextual-request"      # pedido implícito, com LoRA+intent
REASON_LORA_ONLY = "lora-only"                # LoRA RESPOND, sem intent
REASON_DEGRADED = "degraded-no-intent"        # LoRA RESPOND, intent indisponível
REASON_NOT_ADDRESSED = "not-addressed"        # ninguém está falando com a gente
REASON_WAIT = "wait"                          # frase incompleta: segura o merge
REASON_BARGE = "barge"                        # interrupção: não é resposta

# Política padrão: o LoRA é a âncora de precisão e o intent traz o contexto.
POLICY_LORA_AND_CONTEXT = "lora_and_addr_or_intent"
POLICY_EXPLICIT = "explicit"                  # o comportamento de hoje (A/B)


@dataclass(frozen=True)
class GateDecision:
    """Decisão do gate: responder, segurar ou ignorar — e por quê."""

    respond: bool
    reason: str
    explicit: bool = False
    intent: str | None = None
    lora: str | None = None
    hold: bool = False          # WAIT: frase incompleta (o merge deve segurar)
    notes: list[str] = field(default_factory=list)

    @property
    def action(self) -> str:
        """Ação de alto nível: RESPOND | WAIT | IGNORE."""
        if self.hold:
            return "WAIT"
        return "RESPOND" if self.respond else "IGNORE"

    def as_line(self) -> str:
        """Uma linha para o log (o dono quer ver arazão do silêncio)."""
        return (
            f"[gate] {self.action} reason={self.reason} "
            f"explicit={int(self.explicit)} intent={self.intent or '-'} "
            f"lora={self.lora or '-'}"
        )


def addressed_explicit(text: str, name: str = "jarvis", threshold: float = 0.62) -> bool:
    """A heurística de hoje: a pessoa disse o nome do assistente.

    Mantida como fallback (e como via de acesso direto). Medido: recall
    15,4% no dataset de voz — por isso ela não pode ser a decisão sozinha.
    """
    tl = (text or "").lower()
    if name in tl:
        return True
    return any(
        difflib.SequenceMatcher(None, w, name).ratio() >= threshold
        for w in tl.replace(",", " ").split()
    )


def intent_is_request(intent: str | None) -> bool:
    """A intenção pede resposta? (QUESTION/COMMAND)."""
    return bool(intent) and intent.strip().upper() in REQUEST_INTENTS


def decide(
    text: str,
    *,
    intent: str | None = None,
    lora: str | None = None,
    policy: str = POLICY_LORA_AND_CONTEXT,
) -> GateDecision:
    """Decide se a voz deve responder.

    Args:
        text: a transcrição da fala (o que o STR ouviu).
        intent: rótulo do classificador de intenção (QUESTION/COMMAND/.../None).
        lora: rótulo do classificador de turno (RESPOND/WAIT/SILENCE/BARGE).
        policy: `lora_and_addr_or_intent` (padrão) ou `explicit` (o de hoje).

    Returns:
        GateDecision — `respond`, `reason` e o contexto, sempre.
    """
    explicit = addressed_explicit(text)
    intent_norm = (intent or "").strip().upper() or None
    lora_norm = (lora or "").strip().upper() or None

    # Policy de hoje (para A/B e rollback): só o nome explícito decide.
    if policy == POLICY_EXPLICIT:
        if explicit:
            return GateDecision(True, REASON_EXPLICIT, explicit, intent_norm, lora_norm)
        return GateDecision(False, REASON_NOT_ADDRESSED, explicit, intent_norm, lora_norm)

    # BARGE é interrupção, não pedido de resposta.
    if lora_norm == LORA_BARGE:
        return GateDecision(False, REASON_BARGE, explicit, intent_norm, lora_norm)

    # Frase incompleta: segura o merge (não é silêncio, é esperar a continuação).
    if lora_norm == LORA_WAIT:
        return GateDecision(False, REASON_WAIT, explicit, intent_norm, lora_norm, hold=True)

    # Nome explícito: resposta garantida (paper: direct recall ≈ 0,99).
    if explicit:
        return GateDecision(True, REASON_EXPLICIT, explicit, intent_norm, lora_norm)

    # Sem sinal do LoRA (indisponível): não dá para exigir a âncora de
    # precisão — degrada para a evidência que existe (intent ou nada).
    if lora_norm is None:
        if intent_is_request(intent_norm):
            return GateDecision(True, REASON_CONTEXTUAL, explicit, intent_norm, lora_norm,
                                notes=["lora-missing"])
        return GateDecision(False, REASON_NOT_ADDRESSED, explicit, intent_norm, lora_norm,
                            notes=["lora-missing"])

    if lora_norm != LORA_RESPOND:
        # O LoRA disse que não é para o assistente (SILENCE).
        return GateDecision(False, REASON_NOT_ADDRESSED, explicit, intent_norm, lora_norm)

    # LoRA RESPOND: falta o contexto semântico.
    if intent_norm is None:
        # Intenção indisponível (classificador caiu): degradar, nunca voltar
        # ao gate que descarta 11 de 13 pedidos do dono.
        return GateDecision(True, REASON_DEGRADED, explicit, intent_norm, lora_norm,
                            notes=["intent-missing"])
    if intent_is_request(intent_norm):
        return GateDecision(True, REASON_CONTEXTUAL, explicit, intent_norm, lora_norm)
    return GateDecision(False, REASON_LORA_ONLY, explicit, intent_norm, lora_norm)
