"""Gate do duplex: endereço OU intenção (03/11).

O gate antigo exigia a palavra "Jarvis" → 2/13 pedidos do dono passavam
(recall 15%). O classificador de intenção (4B+GBNF) reconhece pergunta/
comando sem a palavra-mágica → recall 92%, F1 0,889 medidos em
`benchmarks/voice/bench_gate.py` (contra o 4B real).

Este teste é OFFLINE: valida a MATRIZ de decisão do gate (sem modelo),
a compatibilidade dos modos e o worker de intenção em thread.
"""

from __future__ import annotations

import importlib.util
import threading
from pathlib import Path

import pytest

DUPLEX = Path(__file__).resolve().parents[4] / "scripts" / "duplex-voice.py"


def _load_duplex():
    spec = importlib.util.spec_from_file_location("duplex_voice_gate_test", DUPLEX)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


@pytest.fixture(scope="module")
def dv():
    return _load_duplex()


# (fala, endereçada?, intenção, deve_responder) — rotulado no bench real
MATRIX = [
    ("que horas são", False, "QUESTION", True),
    ("acende a luz do escritório", False, "COMMAND", True),
    ("toca uma música", False, "COMMAND", True),
    ("me lembra de comprar pão amanhã", False, "COMMAND", True),
    ("qual o status do sistema", False, "QUESTION", True),
    ("Jarvis, que dia é hoje", True, "QUESTION", True),
    ("Jarvis, desliga a luz", True, "COMMAND", True),
    ("obrigado", False, "BACKCHANNEL", False),
    ("hum", False, "BACKCHANNEL", False),
    ("[música]", False, "SOCIAL", False),
    ("isso é muito bom", False, "BACKCHANNEL", False),
    ("cheguei tarde hoje", False, "NONE", False),
    ("ele disse que vem amanhã", False, "NONE", False),
]


@pytest.mark.parametrize("utter,addressed,intent,expected", MATRIX)
def test_gate_intent_mode(dv, utter, addressed, intent, expected):
    dv.GATE_MODE = "intent"
    assert dv._gate_accepts(addressed, intent) is expected


def test_gate_jarvis_mode_is_strict(dv):
    dv.GATE_MODE = "jarvis"
    # sem a palavra-mágica, a intenção NÃO salva o turno (modo antigo)
    assert dv._gate_accepts(False, "QUESTION") is False
    assert dv._gate_accepts(True, "QUESTION") is True


def test_gate_off_accepts_everything(dv):
    dv.GATE_MODE = "off"
    assert dv._gate_accepts(False, None) is True
    assert dv._gate_accepts(False, "NONE") is True


def test_gate_intent_mode_needs_question_or_command(dv):
    dv.GATE_MODE = "intent"
    assert dv._gate_accepts(False, "MUTE") is False
    assert dv._gate_accepts(False, "STOP") is False
    assert dv._gate_accepts(False, "NONE") is False
    assert dv._gate_accepts(False, None) is False  # falha técnica → não responde


def test_intent_worker_fills_box(dv, monkeypatch):
    monkeypatch.setattr(dv, "classify_intent", lambda base, utt: "QUESTION")
    box: dict = {}
    dv._intent_worker("http://x", "que horas são", box)
    assert box["intent"] == "QUESTION"


def test_intent_worker_swallows_error(dv, monkeypatch):
    def boom(base, utt):
        raise RuntimeError("model down")
    monkeypatch.setattr(dv, "classify_intent", boom)
    box: dict = {}
    dv._intent_worker("http://x", "oi", box)
    assert box["intent"] is None


def test_intent_of_joins_thread(dv, monkeypatch):
    monkeypatch.setattr(dv, "classify_intent", lambda base, utt: "COMMAND")
    box: dict = {}
    th = threading.Thread(target=dv._intent_worker, args=("http://x", "liga", box))
    th.start()
    assert dv._intent_of(th, box) == "COMMAND"
    assert not th.is_alive()


def test_intent_of_without_thread(dv):
    assert dv._intent_of(None, {}) is None


def test_addressed_detects_jarvis(dv):
    assert dv._addressed("Jarvis, que horas são") is True
    assert dv._addressed("jarvis toca uma música") is True
    assert dv._addressed("que horas são") is False
