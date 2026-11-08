"""Testes do gate de endereçamento da voz (`jarvis/voice_gate.py`).

O dataset é REUSADO de `benchmarks/voice/bench_gate.py` (fonte única: os
mesmos 27 casos PT-BR rotulados que o bench mede contra o código real).

O que estos testes travam:
- a **regressão medida**: com a política `explicit` (o gate de hoje), o
  recall no dataset é 0,154 (2 de 13) — se alguém "consertar" a heurística,
  este número muda e o teste avisa;
- a **estrutura** do gate novo: o LoRA é a âncora de precisão e o intent
  traz o contexto; degrade em vez de descartar;
- os **limites honestos**: os 2 FP que sobram (fala de TV, auto-fala) NÃO
  são resolvidos pelo gate semântico — só pelo gate de áudio (pend. 4).

Nenhuma chamada de modelo: os rótulos (LoRA/intent) são injetados.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

from jarvis import voice_gate as G

def _find_bench() -> Path:
    """Acha o bench subindo a árvore (o path do repo pode variar)."""
    for parent in Path(__file__).resolve().parents:
        cand = parent / "benchmarks" / "voice" / "bench_gate.py"
        if cand.exists():
            return cand
    raise FileNotFoundError("benchmarks/voice/bench_gate.py not found")


def _load_dataset():
    """Reusa o dataset do bench (fonte única, sem cópia aqui)."""
    spec = importlib.util.spec_from_file_location("bench_gate_ref", _find_bench())
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.DATASET


DATASET = _load_dataset()
RESPOND_CASES = [u for u, exp in DATASET if exp == "RESPOND"]
IGNORE_CASES = [u for u, exp in DATASET if exp == "IGNORE"]
WAIT_CASES = [u for u, exp in DATASET if exp == "WAIT"]


def test_dataset_is_reused_from_the_bench():
    assert len(DATASET) == 27
    assert len(RESPOND_CASES) == 13
    assert len(IGNORE_CASES) == 11
    assert len(WAIT_CASES) == 3


def test_explicit_policy_reproduces_the_measured_recall():
    """Regressão medida: o gate de hoje acerta 2 de 13 (recall 0,154).

    É o número que documenta o bug do dono ("ignora quase tudo"). Se este
    teste falhar, a heurística mudou — e o audit tem que ser atualizado
    com o novo número medido.
    """
    hits = sum(
        1 for u in RESPOND_CASES
        if G.decide(u, policy=G.POLICY_EXPLICIT).respond
    )
    assert hits == 2
    assert round(hits / len(RESPOND_CASES), 3) == 0.154


def test_contextual_path_responds_without_the_name():
    """Pedido implícito (LoRA RESPOND + intent QUESTION) → responde."""
    d = G.decide("que horas são", intent="QUESTION", lora="RESPOND")
    assert d.respond is True
    assert d.action == "RESPOND"
    assert d.reason == G.REASON_CONTEXTUAL


def test_lora_silence_is_the_precision_anchor():
    """LoRA SILENCE bloqueia a resposta, mesmo com intent de pedido.

    O paper 2609.27037 mediu que um LLM puro sobre-ativa (recall 0,993 com
    F1 0,179): ancorar no LoRA é o que segura a precisão.
    """
    d = G.decide("passa o sal", intent="QUESTION", lora="SILENCE")
    assert d.respond is False
    assert d.action == "IGNORE"
    assert d.reason == G.REASON_NOT_ADDRESSED


def test_explicit_name_always_answers():
    """Quem diz "Jarvis" sempre é atendido (direct class: recall ≈ 0,99)."""
    for text in ("Jarvis, acende a luz", "jarvis?", "ok jarvis"):
        d = G.decide(text, intent="NONE", lora="SILENCE")
        assert d.respond is True
        assert d.reason == G.REASON_EXPLICIT


def test_wait_holds_the_merge():
    """Frase incompleta (WAIT) segura — não é silêncio, é espera."""
    d = G.decide("acende a luz do", intent="NONE", lora="WAIT")
    assert d.respond is False
    assert d.hold is True
    assert d.action == "WAIT"


def test_barge_is_not_a_request():
    """Barge (interrupção) não vira resposta."""
    d = G.decide("para", intent="COMMAND", lora="BARGE")
    assert d.respond is False
    assert d.reason == G.REASON_BARGE


def test_missing_intent_degrades_instead_of_dropping():
    """Intenção indisponível: degrada (responde), não volta ao gate que
    descarta 11 de 13 pedidos. Motivo explícito para o log."""
    d = G.decide("que horas são", intent=None, lora="RESPOND")
    assert d.respond is True
    assert d.reason == G.REASON_DEGRADED
    assert "intent-missing" in d.notes


def test_missing_lora_falls_back_to_the_intent_only():
    """LoRA indisponível: só a evidência que existe (intent)."""
    d = G.decide("que horas são", intent="QUESTION", lora=None)
    assert d.respond is True
    assert "lora-missing" in d.notes

    d2 = G.decide("passa o sal", intent="NONE", lora=None)
    assert d2.respond is False


def test_known_false_positives_pass_through():
    """Limite honesto: TV e auto-fala NÃO são resolvidas pelo gate semântico.

    São os 2 FP que sobram na melhor variante medida (F1 0,889). Aqui o
    intent é de pedido e o LoRA é RESPOND ⇒ a decisão é responder. Só o
    gate de áudio (pend. 4) separa a TV do dono.
    """
    for text in ("where's the one?", "vamos embora"):
        d = G.decide(text, intent="QUESTION", lora="RESPOND")
        assert d.respond is True
        assert d.reason == G.REASON_CONTEXTUAL


def test_decision_is_loggable():
    """A decisão vem com uma linha de log (o dono quer ver o porquê)."""
    line = G.decide("que horas são", intent="QUESTION", lora="RESPOND").as_line()
    assert "[gate] RESPOND" in line
    assert f"reason={G.REASON_CONTEXTUAL}" in line
    assert "intent=QUESTION" in line


def _load_duplex():
    """Importa o duplex-voice real (como o bench_gate faz) sem efeitos colaterais."""
    import importlib.util

    path = None
    for parent in Path(__file__).resolve().parents:
        cand = parent / "scripts" / "duplex-voice.py"
        if cand.exists():
            path = cand
            break
    if path is None:
        pytest.skip("scripts/duplex-voice.py nao encontrado neste checkout")
    spec = importlib.util.spec_from_file_location("duplex_voice_live", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_live_gate_delegates_to_the_tested_module():
    """O caminho VIVO usa o modulo testado e o LoRA como ancora.

    Sem o LoRA: a decisao e a do par (endereco OU intent) — o pedido do
    dono passa mesmo sem a palavra "Jarvis".
    Com o LoRA em SILENCE: o turno NAO vira resposta (a ancora de precisao
    que o paper 2609.27037 mostra ser necessaria: um LLM puro sobre-ativa).
    """
    dv = _load_duplex()
    dv.GATE_MODE = "intent"
    # sem rotulo do LoRA: intent de pedido responde
    assert dv._gate_accepts(False, "QUESTION", None) is True
    # LoRA RESPOND + intent de pedido: responde (contexto)
    assert dv._gate_accepts(False, "QUESTION", "RESPOND") is True
    # LoRA RESPOND + intent neutro: nao (o gate so quer pergunta/comando)
    assert dv._gate_accepts(False, "NONE", "RESPOND") is False
    # LoRA SILENCE: a ancora segura, mesmo com intent de pedido
    assert dv._gate_accepts(False, "QUESTION", "SILENCE") is False
    # endereco explicito: sempre passa
    assert dv._gate_accepts(True, "NONE", "SILENCE") is True


def test_live_gate_keeps_the_operator_switches():
    """GATE_MODE off/jarvis continuam com o significado de sempre."""
    dv = _load_duplex()
    dv.GATE_MODE = "off"
    assert dv._gate_accepts(False, None, "SILENCE") is True
    dv.GATE_MODE = "jarvis"
    assert dv._gate_accepts(False, "QUESTION", "RESPOND") is False
    assert dv._gate_accepts(True, "NONE", "SILENCE") is True
