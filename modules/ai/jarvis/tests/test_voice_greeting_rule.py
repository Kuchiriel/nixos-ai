"""Contract for the 'e ai' composite greeting rule (scripts/voice_text_rules.py).

Why: the sweep measured the candidate on 1817 real transcripts: it kills 1 of
them (0.06 percent, 'E ai, o que e isso?') and 10 of the 24 gate survivors. The
cost is the floor of any text gate (the same string sits in both classes), not
a defect of the rule. The real greeting 'E ai, tudo bom?' must pass.
"""
import sys
from pathlib import Path

import pytest


def _find_scripts():
    for p in Path(__file__).resolve().parents:
        if (p / "scripts").is_dir():
            return p / "scripts"
    return None


SCRIPTS = _find_scripts()
if SCRIPTS is None:
    pytest.skip("scripts/ fora do src (sandbox Nix)", allow_module_level=True)
sys.path.insert(0, str(SCRIPTS))

import voice_text_rules as vtr  # noqa: E402

LEXICON = {"obrigado por assistir", "até o próximo vídeo", "som de futebol"}
GREET_SUS = {"e aí", "e aí e aí", "a cidade no brasil", "o que é isso",
             "não não não", "oh oh oh", "hey", "bye", "hi"}


def _rule(text):
    return vtr.looks_greeting_halluc(text, LEXICON, GREET_SUS, vtr.looks_repeated)


@pytest.mark.parametrize("text", [
    "E aí E aí E aí",
    "E aí, E aí, E aí.",
    "E aí obrigado por assistir",
    "E aí a cidade no brasil",
    "E aí o que é isso",
    "E aí legenda Adriana Zanotto",
    "E aí, ah, ah, ah.",
])
def test_kills_the_composite_greetings(text):
    assert _rule(text) is True


@pytest.mark.parametrize("text", [
    "E aí, tudo bom?",
    "E aí, tudo bem?",
    "Bom dia",
    "Obrigado",
    "E aí, vamos embora",
])
def test_keeps_real_speech(text):
    assert _rule(text) is False


def test_greeting_rule_can_be_switched_off(monkeypatch):
    monkeypatch.setenv("JARVIS_VOICE_GREETING_RULE", "0")
    assert vtr.greeting_rule_enabled() is False
    assert _rule("E aí E aí E aí") is False


def test_greeting_rule_is_on_by_default(monkeypatch):
    monkeypatch.delenv("JARVIS_VOICE_GREETING_RULE", raising=False)
    assert vtr.greeting_rule_enabled() is True


def test_accents_do_not_change_the_verdict():
    assert _rule("E aí E aí E aí") is _rule("E ai E ai E ai")


def test_empty_text_is_not_a_greeting_hallucination():
    assert _rule("") is False
    assert _rule("   ") is False
