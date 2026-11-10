#!/usr/bin/env python3
"""measure-voice-rule-cost.py — custo em FALA REAL de uma regra candidata de gate.

POR QUE (10/11, sweep-2026-11)
O gate de voz (duplex-asrd.py, anti_halluc) tem ramos determinísticos que
não dependem de stats de áudio. A última medição do gate real (120 clips de
gatilho, commit b256a247) deixou 24 sobreviventes, e 10 deles são a família
"E aí ..." — o gate mata "e aí" SECO, mas não "E aí E aí E aí" nem "E aí
Obrigado.".

Regra nova no gate de texto tem custo: alguém que diga "E aí, obrigado!" de
verdade tem o turno descartado. A lane de voz mediu o custo antes de
implementar a regra de repetição (1 de 199 falas reais), e é o mesmo protocolo
que este script faz: transcreve uma amostra da fala real da casa
(logs/audio) com o whisper-server e conta o que a regra candidata mata.

O QUE ESTE SCRIPT FAZ
  1. transcreve uma amostra determinística de logs/audio (cache em JSON);
  2. conta quantas falas reais a regra candidata mata (CUSTO);
  3. conta quantas alucinações de gatilho ela mata (BENEFÍCIO), usando o
     JSONL por amostra do bench (state real: segmentos + stats);
  4. imprime a tabela custo x benefício.

NÃO mexe no gate de produção: isto é medição para a lane de voz decidir.

USO
    python3 scripts/measure-voice-rule-cost.py --corpus logs/audio --n 200
    python3 scripts/measure-voice-rule-cost.py --samples reports/duplex-eval/trigger-samples-2026-11-09T231001.jsonl
    python3 scripts/measure-voice-rule-cost.py --no-transcribe   # só o cache

EXEMPLO
    $ python3 scripts/measure-voice-rule-cost.py --n 200
    fala real: 200 transcritas | custo da regra: 1 (0,5 %)
    alucinações: 24 | benefício da regra: 10
"""
import argparse
import json
import os
import re
import sys
import uuid
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

CACHE = ROOT / "logs" / "audio-transcripts.json"
ASR = "http://127.0.0.1:8097"


def post_wav(asr: str, wav: bytes, timeout: float = 30.0) -> dict:
    """POST /inference multipart (o mesmo contrato do asrd, com verbose_json)."""
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\n"
            "Content-Disposition: form-data; name=\"file\"; filename=\"clip.wav\"\r\n"
            "Content-Type: audio/wav\r\n\r\n").encode() + wav + \
        f"\r\n--{boundary}\r\n".encode() + \
        b"Content-Disposition: form-data; name=\"temperature\"\r\n\r\n0\r\n" + \
        f"\r\n--{boundary}\r\n".encode() + \
        b"Content-Disposition: form-data; name=\"response_format\"\r\n\r\nverbose_json\r\n" + \
        f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        asr.rstrip("/") + "/inference", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def norm(text: str) -> str:
    return " ".join(str(text or "").lower()
                    .replace(".", " ").replace(",", " ").replace("!", " ")
                    .replace("?", " ").replace(";", " ").split()).strip()


def deaccent(text: str) -> str:
    """Sem acento: o ASR alterna 'e aí' e 'e ai' e o gate tem as duas formas."""
    import unicodedata
    return "".join(c for c in unicodedata.normalize("NFD", str(text or ""))
                   if not unicodedata.combining(c))


# ---------------------------------------------------------------------------
# a regra candidata: "e aí" no início E o resto parecendo alucinação
# ---------------------------------------------------------------------------
EAI_BIGRAM = re.compile(r"^(e ai\s*){3,}$")


def rule_eai_prefix(text: str, lexicon: set, greet_sus: set,
                    looks_repeated=None) -> bool:
    """Mata 'E aí ...' quando o resto não parece fala real.

    Conservadora de propósito: "E aí, tudo bom?" é fala real e passa. Só morre
    quando o que vem depois é de novo suspicious: léxico/greeting de
    alucinação, repetição, ou "legenda" (legenda de programa).
    """
    t = deaccent(norm(text))
    if not (t.startswith("e ai ") or t == "e ai"):
        return False
    rest = t[len("e ai"):].strip()
    if not rest:
        return False                      # "e ai" seco: o gate já mata
    if rest in lexicon or rest in greet_sus:
        return True
    if rest.startswith("legenda"):
        return True
    if any(w in lexicon for w in rest.split()[:2]):
        return True
    if looks_repeated and looks_repeated(t):
        return True
    if EAI_BIGRAM.match(t):
        return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(ROOT / "logs" / "audio"))
    ap.add_argument("--n", type=int, default=200, help="quantas falas reais")
    ap.add_argument("--asr", default=ASR)
    ap.add_argument("--samples", default="", help="JSONL do bench (benefício)")
    ap.add_argument("--cache", default=str(CACHE))
    ap.add_argument("--no-transcribe", action="store_true")
    args = ap.parse_args()

    from voice_gate import GREET_SUS, LEXICON
    try:
        import voice_text_rules
        looks_repeated = voice_text_rules.looks_repeated
    except Exception:  # noqa: BLE001
        looks_repeated = None
    # as listas do gate são comparadas sem acento (o ASR alterna "e aí"/"e ai")
    lex_plain = {deaccent(x) for x in LEXICON}
    greet_plain = {deaccent(x) for x in GREET_SUS}

    # 1) fala real
    cache = {}
    cp = Path(args.cache)
    if cp.is_file():
        cache = json.loads(cp.read_text())
    wavs = sorted(Path(args.corpus).glob("*.wav"))
    if not wavs:
        print(f"sem WAVs em {args.corpus}", file=sys.stderr)
        return 1
    sample = wavs[:args.n]
    todo = [w for w in sample if w.name not in cache]
    if todo and not args.no_transcribe:
        print(f"transcrevendo {len(todo)} falas reais em {args.asr} ...")
        for i, w in enumerate(todo, 1):
            try:
                out = post_wav(args.asr, w.read_bytes())
                cache[w.name] = (out.get("text") or "").strip()
            except Exception as exc:  # noqa: BLE001
                cache[w.name] = ""
                if i % 25 == 0:
                    print(f"  {i}/{len(todo)} ({exc})", file=sys.stderr)
            if i % 25 == 0:
                cp.write_text(json.dumps(cache, ensure_ascii=False, indent=1))
        cp.write_text(json.dumps(cache, ensure_ascii=False, indent=1))

    real = [(n, t) for n, t in cache.items() if t]
    killed_real = [(n, t) for n, t in real
                   if rule_eai_prefix(t, lex_plain, greet_plain, looks_repeated)]
    starts_eai = [(n, t) for n, t in real
                  if deaccent(norm(t)).startswith("e ai")]
    print(f"\nfala real: {len(real)} transcritas de {len(sample)} "
          f"| começam com 'e aí': {len(starts_eai)} "
          f"| a regra MATA: {len(killed_real)} "
          f"({len(killed_real) / max(1, len(real)) * 100:.1f} %)")
    for n, t in killed_real[:10]:
        print(f"    [custo] {n}: {t[:80]}")

    # 2) alucinações (benefício)
    if args.samples and Path(args.samples).is_file():
        recs = [json.loads(l) for l in
                Path(args.samples).read_text().splitlines() if l.strip()]
        surv = [r for r in recs if not r["gate_kill"]]
        hit = [r for r in surv
               if rule_eai_prefix(r["text"], lex_plain, greet_plain, looks_repeated)]
        print(f"\nalucinações: {len(recs)} | sobreviventes ao gate: {len(surv)} "
              f"| a regra mata: {len(hit)}")
        for r in hit[:12]:
            print(f"    [benefício] {r['cat']}: {' '.join(r['text'].split())[:70]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
