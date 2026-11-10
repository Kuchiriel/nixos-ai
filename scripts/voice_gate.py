"""Gate de voz: a lógica anti-alucinação do duplex-asrd, extraída verbatim.

POR QUE ESTE MÓDULO EXISTE (09/11, sweep-2026-11)
O bench (scripts/duplex-eval.py --trigger-bench) media um PROXY do gate:
`text.lower() in ban`, com igualdade exata, contra dois arquivos TSV. O gate
de produção (scripts/duplex-asrd.py) é outra coisa: uma pilha de ramos, com
substring, greeted-fantasma, redup, "legenda", ALL-CAPS, stats e
tokens-vs-duração. Medir o proxy e medir o gate dá números diferentes, e quem
lê o proxy conclui que o gate fecha a alucinação de gatilho quando não fecha.

Este módulo é a MESMA lógica, extraída sem reescrever (o corpo de
`anti_halluc` é cópia literal do asrd), para que:
  1. o bench meça o gate de verdade;
  2. `scripts/check-voice-gate-parity.py` prove, por comparação de token
     stream, que o gate do asrd e o deste módulo não divergiram.

O asrd ainda tem a sua cópia aninhada (mudar arquivo de produção é da lane
de voz); este módulo é a referência de medição e o alvo do refactor quando a
lane de voz tirar a duplicação.

USO
    from voice_gate import anti_halluc
    texto = anti_halluc(texto_bruto, segmentos, duracao_s)   # "" = morto
"""
import re as _re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
# (09/11, coord-naming) as regras de repeticao do texto vivem num modulo so
# (scripts/voice_text_rules.py), com teste e com o custo em fala real medido.
import voice_text_rules  # noqa: E402

DATA = Path(__file__).resolve().parents[1] / "data"

# (06/11) tracker próprio de fala: o AdaptiveVAD recria o
# FixedVADIterator a cada chunk (update_threshold) e perde o
# estado interno (start/end) — o "end" às vezes não chega e o
# segmento engolia a fala seguinte. Aqui onset/fim vem da
# PROBABILIDADE do silero por janela de 512 (32ms).
# (20/10, papers voz-stt) 4 defesas anti-alucinação:
# 2609.04561 (gated projection): no_speech_prob+avg_logprob como
#   gate — é o sinal que o paper usa p/ decidir projetar.
# 2609.32560 (two-sided): deny-list de frases-alucinação — léxico
#   Scicom PT (data/whisper-halluc-lexicon-pt.tsv, curado AGENTE-HB)
#   em SEGUNDA CAMADA: frase do léxico só morre se os stats do
#   áudio TAMBÉM forem fracos (gated!) — 'Obrigado' dito de verdade
#   tem stats confiantes e PASSA; 'Obrigada' alucinado em ruído não.
#   Riscadas da lista: risadas/aplausos/música = SINAIS SOCIAIS
#   (direção do dono: o agente usa).
# 2610.08847 (CTC criterion): tokens >> duração do áudio = fakir.
# 2608.15940 (null token): logprobs/no_speech = abstenção que a
#   gente jogava fora.
HALLUC_PT = (
    "obrigado por assistir", "obrigado por assistirem",
    "inscreva-se no canal", "até o próximo vídeo",
    "som de futebol",
    # (05:45, curadoria HB ban-pt-hard) só os 2 inequívocos; os
    # outros 8 'safe_candidate' ('muito obrigado', 'com licença'...)
    # são fala REAL — seguem no léxico gated (tier 2, stats fracos)
    "jouvin o sr", "o que é a reunião",
)
SOCIAL_KEEP = ("risada", "aplauso", "música", "músicas", "som dos",
               "sons dos")


def load_lexicon():
    """Léxico Scicom PT: frases ≤4 palavras, sem sinais sociais."""
    out = set()
    try:
        for line in open(DATA / "whisper-halluc-lexicon-pt.tsv"):
            if line.startswith("#") or not line.strip():
                continue
            parts = [p.strip() for p in line.split("\t")]
            if len(parts) < 3 or not parts[2].isdigit():
                continue
            norm = parts[1].lower()
            if not norm or len(norm.split()) > 4:
                continue
            if any(k in norm for k in SOCIAL_KEEP):
                continue
            out.add(norm)
    except OSError:
        pass
    return out


LEXICON = load_lexicon()
# (08:55, delta HB pós-multilingue) fantasmas trocaram de idioma:
# 'Hey.'/'Bye.'/'*Eat*'/'Eee.'/'T-T-T-T'. TSV multilingual do HB:
# ban-hard (curado, multi-word, nunca fala real) + gated JA/ZH.
MULTI_HARD = set()
try:
    for line in open(DATA / "whisper-halluc-ban-multilingual.tsv"):
        if line.startswith("#") or not line.strip():
            continue
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 3 or parts[0] not in ("ban-hard", "gated"):
            continue
        phrase = parts[2].lower()
        if not phrase or len(phrase.split()) < 2:
            continue        # 1-palavra ('ed', 'me') = lixo do count
        if parts[0] == "ban-hard":
            MULTI_HARD.add(phrase)
        else:
            LEXICON.add(phrase)
except OSError:
    pass
# Greeting fantasma por idioma (o turbo emite o clássico da língua
# detectada; PT 'e aí' já morto — estendendo p/ EN. 'hey jarvis'
GREET_SUS = {"e aí", "e aí e aí", "a cidade no brasil", "o que é isso",
             "não não não", "oh oh oh", "hey", "bye", "hi"}


def anti_halluc(txt, segs, dur_s):
    # normalização p/ GATE (pontuação fora): a assinatura de
    # alucinação tem pontuação de legenda ('Não, não, não.')
    t = " ".join(txt.lower().replace("[", " ").replace("]", " ")
                 .replace(",", " ").replace(".", " ").replace("!", " ")
                 .replace("?", " ").split()).strip()
    # 1. deny-list dura: contaminação inequívoca de legenda
    if len(t.split()) <= 6 and any(h in t for h in HALLUC_PT):
        return ""
    # 1a. (06:15, fixtures HB + stats reais: turbo alucina COM
    # CONFIANÇA MÁXIMA — ns ~1e-10, lp ~-0.01; o gate por stats NÃO
    # discrimina. Padrões dominantes = kill determinístico.)
    # Greeting fantasma: 'E aí' SECO (≤2 pal). A saudação REAL
    # completa ('E aí, tudo bom?') passa. Trade-off no queue p/ dono.
    if t in ("e aí", "e ai", "e aí e aí", "e ai e ai",
             "a cidade no brasil", "a cidade no brasil a cidade no brasil"):
        return ""
    # Stutter redup: 'A-a-a-a-a' (loop de sílaba hifenizada) e
    # 'Ah, ah, ah' (token repetido). A segunda forma é o RESIDUAL
    # medido da cadeia da voz (09/11, coord-naming): 3 clipes de
    # repetição de sílabas que atravessavam este gate. O custo foi
    # medido antes: mata 3 de 3 dessas alucinações e 1 de 199 falas
    # reais; a regra de token pode ser desligada com
    # JARVIS_VOICE_REPEAT_RULE=0.
    if voice_text_rules.looks_repeated(t):
        return ""
    # Legenda-leading: 'Legenda Adriana Zanotto' — ninguém COMEÇA
    # fala com 'Legenda' ('a legenda' no meio passa)
    t_words = t.split()
    if t_words and t_words[0] == "legenda" and len(t_words) <= 4:
        return ""
    first2 = " ".join(t_words[:2])
    # 1b. suspeitos GATED (léxico Scicom + greetings fantasma do
    #     turbo [eval HB] + repetição redup): stats fracos = morte;
    #     fala REAL tem stats confiantes e passa.
    if segs and (t in LEXICON or t in GREET_SUS
                 or first2 in GREET_SUS
                 or any(w in LEXICON for w in t_words[:2])
                 or (len(t_words) >= 3 and len(set(t_words)) == 1)):
        ns = max(s.get("no_speech_prob", 0) for s in segs)
        lp = min(s.get("avg_logprob", 0) for s in segs)
        if ns > 0.35 or lp < -0.45:
            return ""
    # 1c. ALL-CAPS recap (eval HB: 'A CIDADE NO BRASIL'): legenda
    #     de programa, nunca fala de mic; gated p/ FP
    if segs and len(t_words) >= 2 and txt.strip().isupper() \
            and not t.replace(" ", "").isdigit():
        ns = max(s.get("no_speech_prob", 0) for s in segs)
        lp = min(s.get("avg_logprob", 0) for s in segs)
        if ns > 0.35 or lp < -0.45:
            return ""
    # 2. gate estatístico: TUDO no_speech alto + logprob ruim = vazio
    if segs and all(s.get("no_speech_prob", 0) > 0.6 for s in segs) \
            and all(s.get("avg_logprob", 0) < -0.8 for s in segs):
        return ""
    # 3. tokens-vs-duração: PT falado ~2-4 pal/s; >5.5 = impossível
    if dur_s > 0.3 and len(txt.split()) > dur_s * 5.5:
        return ""
    return txt


def gate_lists() -> dict:
    """As listas que o gate consulta (para relatório e para a paridade)."""
    return {"HALLUC_PT": set(HALLUC_PT), "LEXICON": set(LEXICON),
            "MULTI_HARD": set(MULTI_HARD), "GREET_SUS": set(GREET_SUS)}
