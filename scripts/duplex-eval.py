#!/usr/bin/env python3
"""duplex-eval.py — harness de eval do modo voz full-duplex (P5, noite 20/10, HB).

Spec completa: docs/DUPLEX-EVAL-DESIGN.md. Runner NOVO (zero colisão com lanes do
AGENTE-OC): só lê endpoints públicos (:8097 ASR / :8092 chat) — nunca escreve em
duplex-voice.py/asrd.

Métricas implementadas:
  --trigger-bench    hallucination-on-trigger: clips Scicom (silence/nonspeech/
                     music/reduplication, FLAC embutido no parquet) → POST /inference
                     no ASR live → taxa de saída não-vazia (alucinação) por categoria,
                     + kill-rate simulado das listas (lexicon/hard tier-2, TSVs do repo).
                     Gate v6 completo vive no asrd (lane OC) — aqui aproximamos tier-2
                     com as listas TSV; diferença documentada no relatório.

Métricas stubs (contrato no design doc, TODO com dono/OC):
  --unit-battery     turn-taking accuracy do classify_turn (offline, sem GPU)
  --barge-latency    E2E acústico com voz real (precisa dono falando sobre TTS)
  --timespeak        idem

USO:   python3 scripts/duplex-eval.py --trigger-bench [--samples 20] [--seed 42]
          [--asr http://127.0.0.1:8097] [--fixtures /tmp/opencode/night-microturn/kaggle-pkg]
          [--out reports/duplex-eval]
EXEMPLO (smoke rápido): python3 scripts/duplex-eval.py --trigger-bench --samples 6
"""
import argparse, json, os, random, sys, time, urllib.request, uuid


def post_audio(asr: str, flac: bytes, timeout: float = 30.0) -> dict:
    """POST /inference multipart (stdlib, sem deps) — mesmo contrato do asrd."""
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\n"
            f"Content-Disposition: form-data; name=\"file\"; filename=\"clip.flac\"\r\n"
            f"Content-Type: audio/flac\r\n\r\n").encode() + flac + \
           f"\r\n--{boundary}\r\n".encode() + \
           b"Content-Disposition: form-data; name=\"temperature\"\r\n\r\n0\r\n" + \
           f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        asr.rstrip("/") + "/inference", data=body, method="POST",
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read())


def load_banlists() -> set:
    """Listas TSV do repo (col 1 = phrase) — tier-2 aproximado do gate v6."""
    phrases = set()
    base = os.path.join(os.path.dirname(__file__), "..", "data")
    for name in ("whisper-halluc-ban-pt-hard.tsv", "whisper-halluc-lexicon-pt.tsv"):
        p = os.path.join(base, name)
        if os.path.isfile(p):
            with open(p, encoding="utf-8") as f:
                for line in f:
                    if line.startswith("#") or not line.strip():
                        continue
                    phrases.add(line.split("\t")[0].strip().lower())
    return phrases


def trigger_bench(args) -> dict:
    import pandas as pd  # venv karaok se necessário; parquet exige pyarrow
    ban = load_banlists()
    rng = random.Random(args.seed)
    report = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "asr": args.asr,
              "samples_per_cat": args.samples, "seed": args.seed,
              "categories": {}, "note": "gate v6 completo vive no duplex-asrd (lane "
              "OC); kill simulado = listas TSV (tier-2 + lexicon)"}
    for cat, fname in [("silence", "silence.parquet"),
                       ("nonspeech", "nonspeech.parquet"),
                       ("music", "music.parquet"),
                       ("reduplication", "reduplication.parquet")]:
        path = os.path.join(args.fixtures, fname)
        if not os.path.isfile(path):
            report["categories"][cat] = {"error": f"sem fixtures: {path}"}
            continue
        df = pd.read_parquet(path)
        idx = list(range(len(df)))
        rng.shuffle(idx)
        idx = idx[:args.samples]
        hallo, killed, empty, errs, samples = 0, 0, 0, 0, []
        for i in idx:
            row = df.iloc[i]
            try:
                out = post_audio(args.asr, row["audio"]["bytes"])
            except Exception as e:
                errs += 1
                samples.append({"id": row.get("id"), "error": str(e)[:80]})
                continue
            text = (out.get("text") or "").strip()
            # pontuação-só ("." / "…") = semantically vazio, não é alucinação
            if not text or not any(c.isalnum() for c in text):
                empty += 1
            else:
                hallo += 1
                inlist = text.lower() in ban
                killed += inlist
                samples.append({"id": row.get("id"), "text": text[:60],
                                "lexicon_kill": inlist})
        n = empty + hallo
        report["categories"][cat] = {
            "clips": n, "empty_ok": empty, "hallucinated": hallo,
            "halluc_rate": round(hallo / n, 3) if n else None,
            "lexicon_kill": killed,
            "net_rate_apos_lista": round((hallo - killed) / n, 3) if n else None,
            "errors": errs, "samples": samples[:8]}
        print(f"{cat}: {hallo}/{n} alucinou ({report['categories'][cat]['halluc_rate']})"
              f" | lista mataria {killed} | erros {errs}")
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--trigger-bench", action="store_true")
    ap.add_argument("--samples", type=int, default=20)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--asr", default="http://127.0.0.1:8097")
    ap.add_argument("--fixtures",
                    default="/tmp/opencode/night-microturn/kaggle-pkg")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__),
                                                  "..", "reports", "duplex-eval"))
    args = ap.parse_args()
    if not args.trigger_bench:
        print(__doc__)
        return 1
    report = trigger_bench(args)
    os.makedirs(args.out, exist_ok=True)
    latest = os.path.join(args.out, "latest.json")
    with open(latest, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    with open(os.path.join(args.out, f"{report['ts'].replace(':', '')}.json"),
              "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=1)
    print("relatório:", latest)
    return 0


if __name__ == "__main__":
    sys.exit(main())
