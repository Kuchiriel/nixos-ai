"""Testes do classificador de intenções (determinístico)."""

import pytest

from jarvis.core.intents import classify_intent, IntentClassifier


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        # SYSTEM
        ("uso de cpu", "SYSTEM"),
        ("quanta memória tem", "SYSTEM"),
        ("espaço em disco", "SYSTEM"),
        ("mude a voz", "SYSTEM"),
        ("gpu status", "SYSTEM"),
        # CODING
        ("escreva um script em python", "CODING"),
        ("analise o protocolo de rede", "CODING"),
        ("corrija o erro no código", "CODING"),
        ("packet structure do cliente", "CODING"),
        ("otimize este código", "CODING"),
        # VISION
        ("tire um print da tela", "VISION"),
        ("screenshot da janela", "VISION"),
        ("analise o que estou vendo na tela", "VISION"),
        ("look at the screen", "VISION"),
        # CHAT
        ("olá", "CHAT"),
        ("bom dia", "CHAT"),
        ("quem foi Alan Turing", "CHAT"),
        ("conte uma história", "CHAT"),
        ("qual a capital da França", "CHAT"),
    ],
)
def test_intent_classification(text: str, expected: str) -> None:
    assert classify_intent(text) == expected


def test_technical_markers_never_vision() -> None:
    """Regra de Ouro: termo técnico sempre CODING, nunca VISION."""
    assert classify_intent("analise o protocolo na tela") == "CODING"


def test_question_trigger_low_confidence_is_chat() -> None:
    assert classify_intent("quem") == "CHAT"


def test_deterministic() -> None:
    a = classify_intent("me ajude com o opcode xtea")
    b = classify_intent("me ajude com o opcode xtea")
    assert a == b == "CODING"


def test_scores_cover_all_intents() -> None:
    scores = IntentClassifier().scores("screenshot da tela")
    assert set(scores.keys()) == {"SYSTEM", "CODING", "VISION", "CHAT"}
    assert scores["VISION"] >= 0.0
