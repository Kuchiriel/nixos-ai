#!/usr/bin/env python3
"""voice_text_rules.py — regras de higiene de texto do asrd, num lugar só.

POR QUE (09/11, coord-naming): o residual medido da cadeia da voz são 3
clipes de REPETIÇÃO DE SÍLABAS que atravessam o gate `anti_halluc` do
`duplex-asrd` ("Ah, ah, ah.", "Tataataataata. Uh uh uh.", "E E E E E"). A
regra de repetição que já existia no asrd só pegava a forma hifenizada
("A-a-a-a"), que não aparece nessas alucinações.

O CUSTO foi medido antes de implementar (199 transcrições reais de
`logs/audio`, transcritas pelo whisper-server da casa):

  - regra hifenizada (a de hoje): mata 0/199 falas reais e 0/3 das alucinações
  - regra de token repetido: mata **1/199** falas reais ("Não, não, não,
    não.") e **3/3** das alucinações ⇒ **0,5 % de custo em fala real para
    fechar o residual medido**

A regra de token repetido é **não condicionada** ao áudio (o áudio da alucinação
é confiante: `avg_logprob` −0,24 a −0,43), e é por isso que ela custa 0,5 %
de fala real: alguém que diga "Não, não, não, não" de verdade tem o turno
descartado.

PARA DESLIGAR: `JARVIS_VOICE_REPEAT_RULE=0` no ambiente do asrd (o default é
ligado). A desliga e a liga sem mexer em código.

USO
    import voice_text_rules
    if voice_text_rules.looks_repeated(text):
        return ""      # no asrd: o segmento vira vazio
"""
import os
import re

# repeticao hifenizada: "A-a-a-a" (a regra que o asrd ja tinha)
REPEAT_HYPHEN = re.compile(r"\b(\w{1,3})(-\1){2,}")

# repeticao de token: "ah, ah, ah", "e e e e e", "não, não, não, não"
REPEAT_TOKEN = re.compile(r"\b(\w{1,4})\b(?:[\s,.;:'\"-]+\1\b){2,}", re.I)

# "e ai" repetido 3+ vezes: "e ai e ai e ai"
EAI_BIGRAM = re.compile(r"^(e ai\s*){3,}$")


def repeat_rule_enabled() -> bool:
    """A regra de repeticao de token pode ser desligada pelo ambiente."""
    return os.environ.get("JARVIS_VOICE_REPEAT_RULE", "1").strip() not in (
        "0", "false", "no", "off")


def looks_repeated(text: str) -> bool:
    """O texto parece repeticao (hifenizada sempre; token so se a regra esta ligada)."""
    if not text:
        return False
    t = " ".join(text.lower().split())
    if REPEAT_HYPHEN.search(t):
        return True
    if repeat_rule_enabled() and REPEAT_TOKEN.search(t):
        return True
    return False


def _deaccent(text: str) -> str:
    """Sem acento: o ASR alterna 'e aí' e 'e ai'."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(text or ""))
                   if not unicodedata.combining(c))


def _norm(text: str) -> str:
    return " ".join(str(text or "").lower()
                    .replace(".", " ").replace(",", " ").replace("!", " ")
                    .replace("?", " ").replace(";", " ").split()).strip()


def greeting_rule_enabled() -> bool:
    """A regra de 'e ai' composto pode ser desligada pelo ambiente."""
    return os.environ.get("JARVIS_VOICE_GREETING_RULE", "1").strip() not in (
        "0", "false", "no", "off")


def looks_greeting_halluc(text: str, lexicon, greet_sus, looks_repeated=None) -> bool:
    """'E ai ...' COMPOSTO: mata quando o resto tambem parece alucinacao.

    MEDIDO ANTES (10/11, sweep-2026-11, `scripts/measure-voice-rule-cost.py`):
    nas 1817 transcricoes reais de `logs/audio`, a regra mata **1** fala real
    (0,06 %) — 'E ai, o que e isso?' — e mata **10 dos 24** sobreviventes do
    gate. O custo e' o PISO de qualquer gate de texto (a mesma string esta na
    fala real e na alucinacao), nao defeito da regra.

    Conservative de proposito: 'E ai, tudo bem?' e fala real e passa. So morre
    quando o que vem depois e' de novo suspeito: lexico/greeting de alucinacao,
    repeticao, 'legenda' de programa, ou o proprio 'e ai' repetido.

    PARA DESLIGAR: `JARVIS_VOICE_GREETING_RULE=0`.
    """
    if not greeting_rule_enabled():
        return False
    t = _deaccent(_norm(text))
    if not (t.startswith("e ai ") or t == "e ai"):
        return False
    rest = t[len("e ai"):].strip()
    if not rest:
        return False                      # "e ai" seco: o gate ja mata
    lex_plain = {_deaccent(x) for x in lexicon}
    gre_plain = {_deaccent(x) for x in greet_sus}
    if rest in lexicon or rest in greet_sus:
        return True
    if rest in lex_plain or rest in gre_plain:
        return True
    if rest.startswith("legenda"):
        return True
    if any(w in lex_plain for w in rest.split()[:2]):
        return True
    if looks_repeated and looks_repeated(t):
        return True
    if EAI_BIGRAM.match(t):
        return True
    return False
