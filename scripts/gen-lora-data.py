#!/usr/bin/env python3
"""gen-lora-data.py — gera dados de treino pro LoRA de timing no 4B-MTP.

Do papers:
- DuplexPO (2607.07148): decouple WHEN from WHAT; reward shapes:
  yield ≤240ms, grace 160ms, early-start penalized more than late.
- Easy-Turn (2509.23938): states = complete/incomplete/backchannel/wait.
- MicroTurn-LoRA (codacus): the timing behavior trained on the 35B.

NOSSO CASO: treinar o 4B-MTP pra decidir:
  - RESPOND (segmento completo = fala, responde)
  - WAIT (segmento incompleto = mais fala vem)
  - SILENCE (backchannel/ruído = não responda)
  - BARGE-IN detectado (o dono interrompeu = PARE de falar)

Formato: conversas sintéticas + turnos do log real (/tmp/opencode/duplex-voice.log)
        → JSONL {messages: [{role, content}...], response: <label>}

Uso:
  python3 gen-lora-data.py --log /tmp/opencode/duplex-voice.log --out /tmp/opencode/lora-train.jsonl
"""
import argparse
import json
import random
import re
import sys
import time
from pathlib import Path

SYSTEM = ("Você é o JARVIS, assistente de voz. Classifique o turno do "
          "usuário em uma palavra: RESPOND (fala completa que pede resposta), "
          "WAIT (frase incompleta, mais vem), SILENCE (backchannel/ruído), "
          "ou BARGE (o dono interrompeu sua fala).")

BACKCHANNELS = {"uh-huh", "hmm", "hm", "ah", "ok", "okay", "sim", "tá",
                "ta", "certo", "é", "pois é", "sei", "beleza", "entendi",
                "uhuh", "ahn", "pode ser"}
INCOMPLETE_ENDS = (",", " e", " mas", " ou", " que", " pra", " para",
                  " então", " tipo", " assim")
COMPLETE_ENDS = ("?", "!", ".")


def classify(text):
    t = text.strip().lower().rstrip(".,!?")
    words = t.split()
    if len(words) < 3:
        return "SILENCE"
    if t in BACKCHANNELS:
        return "SILENCE"
    if text.rstrip().endswith(COMPLETE_ENDS) and len(words) >= 3:
        return "RESPOND"
    if any(text.rstrip().endswith(e) for e in INCOMPLETE_ENDS):
        return "WAIT"
    if len(words) >= 4:
        return "RESPOND"
    return "WAIT"


def extract_from_log(log_path):
    """Extrai turnos do log real do duplex."""
    turns = []
    try:
        lines = Path(log_path).read_text().splitlines()
        for line in lines:
            m = re.search(r"utterância completa: '(.+?)'", line)
            if m and len(m.group(1)) > 5:
                turns.append(m.group(1))
    except Exception:
        pass
    return turns


def synth_conversations(n=200):
    """Conversas sintéticas PT-BR com todos os 4 estados."""
    questions = [
        "que horas são?", "qual é a previsão do tempo pra amanhã?",
        "lembra que eu gosto de pizza", "cadê meus livros?",
        "quanto tá o dólar hoje?", "status do sistema",
        "como se diz obrigado em japonês?", "me conta uma piada",
        "liga a luz da sala", "qual é o meu nome?",
        "toca uma música de rock", "que dia é hoje?",
        "abre o navegador", "procura meus arquivos",
    ]
    incompletes = [
        "então eu estava pensando que", "o negócio é o seguinte",
        "olha só o que aconteceu, ", "sabe aquilo que eu falei sobre",
        "é tipo assim, quando você", "e depois disso tudo, então",
    ]
    backs = list(BACKCHANNELS) + ["", "[MÚSICA]", "alguém falando longe"]
    barge = [
        "PARE!", "espera, deixa eu falar", "não, não é isso",
        "calma aí", "deixa eu terminar", "para com isso",
    ]

    data = []
    for _ in range(n):
        state = random.choice(["RESPOND", "WAIT", "SILENCE", "BARGE"])
        if state == "RESPOND":
            text = random.choice(questions)
        elif state == "WAIT":
            text = random.choice(incompletes)
        elif state == "SILENCE":
            text = random.choice(backs)
        else:
            text = random.choice(barge)

        data.append({
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": text},
                {"role": "assistant", "content": state},
            ],
            "target": state,
        })
    return data


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="/tmp/opencode/duplex-voice.log")
    ap.add_argument("--out", default="/tmp/opencode/lora-train.jsonl")
    ap.add_argument("--n-synth", type=int, default=300)
    o = ap.parse_args()

    data = synth_conversations(o.n_synth)

    # adiciona turnos REAIS do log
    real = extract_from_log(o.log)
    for text in real:
        label = classify(text)
        data.append({
            "messages": [
                {"role": "system", "content": SYSTEM},
                {"role": "user", "content": text},
                {"role": "assistant", "content": label},
            ],
            "target": label,
        })

    random.shuffle(data)
    with open(o.out, "w") as f:
        for d in data:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")
    labels = {}
    for d in data:
        labels[d["target"]] = labels.get(d["target"], 0) + 1
    print(f"gerado: {len(data)} exemplos → {o.out}")
    print(f"distribuição: {labels}")


if __name__ == "__main__":
    main()
