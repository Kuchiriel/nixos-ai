#!/usr/bin/env python3
"""measure-voice-signals.py — separa alucinação de fala real por sinais que o gate NÃO usa.

POR QUE (10/11, sweep-2026-11)
O braço de áudio do gate (scripts/duplex-asrd.py) usa dois sinais do
whisper: no_speech_prob e avg_logprob. Medido (commit b256a247, 120 clips de
gatilho), os dois NÃO discriminam: no_speech_prob mediano 0,000 e
avg_logprob mediano entre -0,22 e -0,30 contra limiar de -0,45 — a
transcrição alucinada chega confiante. Ou seja, o ramo gated do gate é
inoperante na alucinação de gatilho (mata 0 de 111).

O whisper.cpp expõe mais no verbose_json, e o gate ignora tudo isso:
  - words[].probability: confiança POR PALAVRA;
  - tokens: o id de cada token (dá a compression ratio, um dos três
    heurísticos do próprio Whisper);
  - start/end: a duração (o gate usa, no teste tokens-vs-duração).
O paper arXiv 2606.23060 ("From Text Metrics to Model Internals") estuda
exatamente isso: os três heurísticos do Whisper (AL, CR, NSP) deveriam
marcar as alucinações e, na prática, não marcam.

O QUE ESTE SCRIPT FAZ
  1. re-transcreve uma amostra da fala real da casa (logs/audio) com
     verbose_json e guarda os segmentos (cache próprio);
  2. pega as alucinações de gatilho do JSONL do bench (mesmo estado real);
  3. calcula candidatos de sinal nas DUAS classes;
  4. mede a separação: no limiar que mata 90 % das alucinações, quantas
     falas reais morreriam (o custo), e mostra a AUC aproximada.

NÃO mexe no gate de produção: é medição, para a lane de voz decidir se
existe um braço de áudio que sirva.

USO
    python3 scripts/measure-voice-signals.py --n 200
    python3 scripts/measure-voice-signals.py --samples reports/duplex-eval/trigger-samples-2026-11-09T231001.jsonl
    python3 scripts/measure-voice-signals.py --no-transcribe   # só o cache

EXEMPLO
    $ python3 scripts/measure-voice-signals.py --n 200
    sinal min_word_prob: AUC 0.51 (não separa)
"""
import argparse
import json
import sys
import uuid
import urllib.request
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
CACHE = ROOT / "logs" / "audio-segments.json"
ASR = "http://127.0.0.1:8097"


def post_wav(asr: str, wav: bytes, timeout: float = 30.0) -> dict:
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


def compression_ratio(text: str) -> float:
    """Compression ratio do texto (heurístico CR do Whisper): gzip do texto
    sobre o texto. Repetição comprime bem ⇒ CR baixo."""
    t = (text or "").strip()
    if not t:
        return 0.0
    return len(zlib.compress(t.encode(), 9)) / len(t.encode())


def signals(segs: list, text: str) -> dict:
    probs = [float(w.get("probability", 1.0) or 0.0)
             for s in (segs or []) for w in (s.get("words") or [])
             if w.get("probability") is not None]
    ns = max([float(s.get("no_speech_prob", 0.0) or 0.0) for s in (segs or [])]
             or [0.0])
    lp = min([float(s.get("avg_logprob", 0.0) or 0.0) for s in (segs or [])]
             or [0.0])
    starts = [float(s.get("start", 0.0) or 0.0) for s in (segs or [])]
    ends = [float(s.get("end", 0.0) or 0.0) for s in (segs or [])]
    dur = (max(ends) - min(starts)) if segs else 0.0
    ntok = sum(len(s.get("tokens") or []) for s in (segs or []))
    words = len((text or "").split())
    return {
        "min_word_prob": min(probs) if probs else 1.0,
        "med_word_prob": (sorted(probs)[len(probs) // 2] if probs else 1.0),
        "no_speech_prob": ns,
        "avg_logprob": lp,
        "duration": dur,
        "words_per_s": (words / dur) if dur > 0.05 else 0.0,
        "tokens": ntok,
        "words": words,
        "cr": compression_ratio(text),
        "tokens_per_word": (ntok / words) if words else 0.0,
    }


def auc(pos: list, neg: list) -> float:
    """AUC de pos (queremos alto) contra neg (queremos baixo). 0,5 = nada."""
    if not pos or not neg:
        return float("nan")
    wins = ties = 0
    for p in pos:
        for n in neg:
            if p > n:
                wins += 1
            elif p == n:
                ties += 1
    return (wins + 0.5 * ties) / (len(pos) * len(neg))


def report(name: str, pos: list, neg: list, higher_is_bad: bool) -> None:
    a = auc(pos, neg) if higher_is_bad else auc(neg, pos)
    pos_s = sorted(pos)
    neg_s = sorted(neg)
    p10 = pos_s[int(len(pos_s) * 0.10)] if pos_s else float("nan")
    # custo: no limiar que mata 10 % das alucinações, quantas falas reais morrem
    thr = p10
    if higher_is_bad:
        custo = sum(1 for n in neg if n >= thr)
    else:
        custo = sum(1 for n in neg if n <= thr)
    print(f"  {name:18s} AUC {a:.3f} | limiar(10 % das alucinacoes) "
          f"{thr:.4f} | custo em fala real: {custo}/{len(neg)}"
          f" ({custo / max(1, len(neg)) * 100:.1f} %)")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", default=str(ROOT / "logs" / "audio"))
    ap.add_argument("--n", type=int, default=200)
    ap.add_argument("--asr", default=ASR)
    ap.add_argument("--samples", default="")
    ap.add_argument("--cache", default=str(CACHE))
    ap.add_argument("--no-transcribe", action="store_true")
    args = ap.parse_args()

    # 1) fala real (com segmentos)
    cache = {}
    cp = Path(args.cache)
    if cp.is_file():
        cache = json.loads(cp.read_text())
    wavs = sorted(Path(args.corpus).glob("*.wav"))
    sample = wavs[:args.n]
    todo = [w for w in sample if w.name not in cache]
    if todo and not args.no_transcribe:
        print(f"transcrevendo {len(todo)} falas reais (com segmentos) em {args.asr} ...")
        for i, w in enumerate(todo, 1):
            try:
                out = post_wav(args.asr, w.read_bytes())
                cache[w.name] = {"text": (out.get("text") or "").strip(),
                                 "segments": out.get("segments") or []}
            except Exception:  # noqa: BLE001
                cache[w.name] = {"text": "", "segments": []}
            if i % 25 == 0:
                cp.write_text(json.dumps(cache, ensure_ascii=False))
        cp.write_text(json.dumps(cache, ensure_ascii=False))

    real = [(v["text"], v["segments"]) for v in cache.values() if v.get("text")]
    print(f"\nfala real: {len(real)} transcritas com segmentos")

    # 2) alucinações (estado real do bench)
    hall = []
    if args.samples and Path(args.samples).is_file():
        recs = [json.loads(l) for l in
                Path(args.samples).read_text().splitlines() if l.strip()]
        hall = [(r["text"], r["segs"]) for r in recs]
        print(f"alucinacoes: {len(hall)} (do JSONL do bench)")

    if not real or not hall:
        print("faltou corpus real ou amostras de alucinacao", file=sys.stderr)
        return 1

    rs = [signals(segs, t) for t, segs in real]
    hs = [signals(segs, t) for t, segs in hall]
    print("\nseparacao dos sinais (alucinacao vs fala real):")
    for key, higher_is_bad in (
            ("min_word_prob", False), ("med_word_prob", False),
            ("no_speech_prob", True), ("avg_logprob", False),
            ("duration", True), ("words_per_s", True),
            ("cr", False), ("tokens_per_word", False)):
        report(key, [h[key] for h in hs], [r[key] for r in rs], higher_is_bad)
    return 0


if __name__ == "__main__":
    sys.exit(main())
