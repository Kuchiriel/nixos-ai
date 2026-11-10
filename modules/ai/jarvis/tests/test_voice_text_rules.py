"""Contract for scripts/voice_text_rules.py (text hygiene of the ASRD gate).

Why: the measured residual of the house voice chain is syllable repetition
("Ah, ah, ah.", "Tataataataata. Uh uh uh.", "E E E E E"), which the hyphenated
repetition rule in the ASRD does not catch. The cost of the new rule was
measured on 199 real transcripts before it was written: it kills 3 of the 3
survivors and 1 of 199 real utterances ("Nao, nao, nao, nao."), so it can be
switched off with JARVIS_VOICE_REPEAT_RULE=0.
"""
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
sys.path.insert(0, str(SCRIPTS))

import voice_text_rules  # noqa: E402

SURVIVORS = [
    "Ah, ah, ah.",
    "Tataataataata.\n Uh uh uh.",
    "E E E E E",
]

REAL_SPEECH = [
    "Preciso que voce grave 10 segundos de fala para eu cadastrar a voz",
    "do TSE. O TSE e o que decide a eleicao",
    "Essas algumas horas ai tem que provar que o senhor tem dentro das sessoes",
]


@pytest.mark.parametrize("text", SURVIVORS)
def test_kills_the_measured_survivors(text):
    assert voice_text_rules.looks_repeated(text) is True


@pytest.mark.parametrize("text", REAL_SPEECH)
def test_keeps_normal_speech(text):
    assert voice_text_rules.looks_repeated(text) is False


def test_hyphenated_repetition_is_always_caught():
    assert voice_text_rules.looks_repeated("A-a-a-a") is True


def test_token_rule_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("JARVIS_VOICE_REPEAT_RULE", "0")
    assert voice_text_rules.repeat_rule_enabled() is False
    assert voice_text_rules.looks_repeated("Ah, ah, ah.") is False
    # the hyphenated form is not optional
    assert voice_text_rules.looks_repeated("A-a-a-a") is True


def test_token_rule_is_on_by_default(monkeypatch):
    monkeypatch.delenv("JARVIS_VOICE_REPEAT_RULE", raising=False)
    assert voice_text_rules.repeat_rule_enabled() is True


def test_empty_text_is_not_repetition():
    assert voice_text_rules.looks_repeated("") is False
    assert voice_text_rules.looks_repeated("   ") is False
