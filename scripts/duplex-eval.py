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
  --unit-battery     turn-taking accuracy: 120 cenas gold-label
                     (data/duplex-eval-turntaking.jsonl) → classify_turn replicado
                     BYTE-A-BYTE (CLASS_SYS + toggle /lora-adapters + /completion
                     temp 0, sync duplex-voice.py:114) → matriz de confusão + acc
                     por classe. Não usar enquanto o cliente duplex estiver em
                     sessão ativa (races no toggle do LoRA).

Métricas stubs (contrato no design doc, TODO com dono/OC):
  --barge-latency    E2E acústico com voz real (precisa dono falando sobre TTS)
  --timespeak        idem

USO:   python3 scripts/duplex-eval.py --trigger-bench [--samples 20] [--seed 42]
          [--asr http://127.0.0.1:8097] [--fixtures /tmp/opencode/night-microturn/kaggle-pkg]
          [--out reports/duplex-eval]
       python3 scripts/duplex-eval.py --unit-battery [--classify http://127.0.0.1:8092]
EXEMPLO (smoke rápido): python3 scripts/duplex-eval.py --trigger-bench --samples 6
"""
import argparse, json, os, random, sys, time, urllib.request, uuid

CLASS_SYS = ("Você é o JARVIS, assistente de voz. Classifique o turno do "
             "usuário em uma palavra: RESPOND (fala completa que pede "
             "resposta), WAIT (frase incompleta, mais vem), SILENCE "
             "(backchannel/ruído), ou BARGE (o dono interrompeu sua fala).")
CLASS_LABELS = ("RESPOND", "WAIT", "SILENCE", "BARGE")


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
        observed = []
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
                observed.append(f"{cat}\t{row.get('id')}\t{text}")
        n = empty + hallo
        report["categories"][cat] = {
            "clips": n, "empty_ok": empty, "hallucinated": hallo,
            "halluc_rate": round(hallo / n, 3) if n else None,
            "lexicon_kill": killed,
            "net_rate_apos_lista": round((hallo - killed) / n, 3) if n else None,
            "errors": errs, "samples": samples[:8]}
        print(f"{cat}: {hallo}/{n} alucinou ({report['categories'][cat]['halluc_rate']})"
              f" | lista mataria {killed} | erros {errs}")
    # feed p/ o deny-list (lane OC): TODOS os textos alucinados observados
    if observed:
        obs = os.path.join(args.out, "hallucinations-observed.txt")
        os.makedirs(args.out, exist_ok=True)
        with open(obs, "a", encoding="utf-8") as f:
            f.write(f"# {report['ts']} asr={args.asr} samples/cat={args.samples}\n")
            f.write("\n".join(observed) + "\n")
        report["hallucinations_observed_file"] = obs
    return report


def http_json(url: str, payload) -> dict:
    req = urllib.request.Request(url, data=json.dumps(payload).encode(),
                                 method="POST",
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read())


def classify_once(base: str, utt: str):
    """Réplica byte-a-byte de classify_turn (duplex-voice.py:114) — sync lá."""
    try:
        http_json(base + "/lora-adapters", [{"id": 0, "scale": 1.0}])
        prompt = (f"<|im_start|>system\n{CLASS_SYS}<|im_end|>\n"
                  f"<|im_start|>user\n{utt}<|im_end|>\n"
                  f"<|im_start|>assistant\n")
        j = http_json(base + "/completion", {
            "prompt": prompt, "n_predict": 6, "temperature": 0,
            "stop": ["<|im_end|>"], "cache_prompt": True})
        out = str(j.get("content", "")).strip().upper()
        for lab in CLASS_LABELS:
            if out.startswith(lab):
                return lab
        return None
    except Exception:
        return None
    finally:
        try:
            http_json(base + "/lora-adapters", [])
        except Exception:
            pass


def unit_battery(args) -> dict:
    path = os.path.join(os.path.dirname(__file__), "..", "data",
                        "duplex-eval-turntaking.jsonl")
    items = [json.loads(l) for l in open(path, encoding="utf-8")
             if l.strip() and not l.lstrip().startswith("#")]
    conf = {g: {p: 0 for p in CLASS_LABELS + ("NONE",)} for g in CLASS_LABELS}
    lats = []
    for it in items:
        t0 = time.monotonic()
        pred = classify_once(args.classify, it["utt"])
        lats.append((time.monotonic() - t0) * 1000)
        conf[it["gold"]][pred or "NONE"] += 1
    ls = sorted(lats)
    report = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "classify": args.classify,
              "n": len(items), "classes": {},
              "latency_ms": {"p50": round(ls[len(ls)//2], 1),
                             "p99": round(ls[min(int(len(ls)*0.99), len(ls)-1)], 1),
                             "mean": round(sum(ls)/len(ls), 1)}}
    accs = []
    for g in CLASS_LABELS:
        tot = sum(conf[g].values())
        acc = conf[g][g] / tot if tot else None
        accs.append(acc)
        report["classes"][g] = {"n": tot, "acc": round(acc, 3),
                                "confusion": conf[g]}
        print(f"{g}: acc={acc:.2f} ({conf[g][g]}/{tot}) "
              f"conf={ {k: v for k, v in conf[g].items() if v and k != g} }")
    report["avg_turn_taking_acc"] = round(sum(accs) / len(accs), 3)
    print("AVERAGED TURN-TAKING ACC:", report["avg_turn_taking_acc"],
          "| classify lat ms p50/p99/mean:",
          report["latency_ms"]["p50"], report["latency_ms"]["p99"],
          report["latency_ms"]["mean"])
    return report


def e2e_playback(args) -> dict:
    """E2E acústico: toca wavs no ALTO-FALANTE e mede o duplex pela reação no log
    (/tmp/opencode/duplex-voice.log — formato calibrado na live-fire TV 09:4x).
    Autorização: dono AFK 20/10 "gerem as vozes com TTS, alto-falante ou injetado".
    SEQUÊNCIA COMBINADA COM O OC (janela de teste) — não rodar em sessão do dono.
    """
    import subprocess, threading
    LOG = "/tmp/opencode/duplex-voice.log"
    WAVS = "/tmp/opencode/night-microturn/genuine-synth-wavs"
    scenarios = []
    items = [json.loads(l) for l in open(
        os.path.join(os.path.dirname(__file__), "..", "data",
                     "duplex-eval-turntaking.jsonl"), encoding="utf-8")
             if l.strip() and not l.lstrip().startswith("#")]
    # 10 perguntas (RESPOND), 5 barge, 5 backchannel — ordem de execução
    by = {}
    for i, it in enumerate(items):
        by.setdefault(it["gold"], []).append((i, it["utt"]))
    scenarios = [(i, u, "RESPOND") for i, u in by["RESPOND"][:10]]
    scenarios += [(i, u, "BARGE") for i, u in by["BARGE"][:5]]
    scenarios += [(i, u, "SILENCE") for i, u in by["SILENCE"][:5]]

    seen = 0
    if os.path.exists(LOG):
        seen = os.path.getsize(LOG)
    lines = []
    def follow():
        # poll-by-path: reabre o arquivo a cada ciclo (imune a truncate/recreate
        # do log — o cliente relança e o inode muda; lição do run gate-off 20/10)
        pos = seen
        while not stop[0]:
            try:
                sz = os.path.getsize(LOG)
                if sz < pos:            # truncado/recriado
                    pos = 0
                if sz > pos:
                    with open(LOG, encoding="utf-8", errors="ignore") as f:
                        f.seek(pos)
                        chunk = f.read()
                        pos = f.tell()
                    for ln in chunk.splitlines(keepends=True):
                        lines.append((time.monotonic(), ln))
            except FileNotFoundError:
                pass
            time.sleep(0.2)
    stop = [False]
    threading.Thread(target=follow, daemon=True).start()

    def wait_for(pat, timeout=15.0):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            for t, ln in lines:
                if t > t0 and pat in ln:
                    return t - t0, ln
            time.sleep(0.05)
        return None, None

    report = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "route": "speaker",
              "scenarios": []}
    time.sleep(1)
    want = {x.strip().upper() for x in args.only.split(",") if x.strip()}
    for idx, utt, expect in scenarios:
        if want and expect not in want:
            continue
        wav = os.path.join(WAVS, f"utt_{idx:03d}.wav")
        if not os.path.exists(wav):
            continue
        r = {"utt": utt, "expect": expect, "wav": f"utt_{idx:03d}.wav"}
        t0 = time.monotonic()
        player = "/run/current-system/sw/bin/pw-play"  # NixOS: pipewire player
        subprocess.run([player, wav], check=False)
        t_play_end = time.monotonic() - t0
        r["play_s"] = round(t_play_end, 2)
        seg = utt[:25]
        dseg, lseg = wait_for(seg, 20)
        r["segment_captured"] = dseg is not None
        if expect == "RESPOND":
            dt, lresp = wait_for("TTS(", 25)
            r["timespeak_s"] = round(dseg + dt, 2) if dseg and dt else None
            dcls, lcls = wait_for("classify", 10)
            r["classify_line"] = lcls.strip()[:80] if lcls else None
            r["verdict"] = "ok" if lresp else "no-response"
        elif expect == "SILENCE":
            dcls, lcls = wait_for("classify", 12)
            ok_sil = lcls and ("SILENCE" in lcls or "silêncio" in lcls or "backchannel" in lcls)
            r["verdict"] = "ok-silenced" if ok_sil else ("classified" if lcls else "no-segment")
        else:  # BARGE — fase 3: barge DURANTE a resposta (senão não há TTS p/ matar).
               # sequência: pergunta longa → espera TTS( → barge por cima → kill.
            qidx, qu_ = by["RESPOND"][11]  # "Jarvis, me conta uma piada." (resposta longa)
            subprocess.run([player, os.path.join(WAVS, f"utt_{qidx:03d}.wav")],
                           check=False)
            dtts, ltts = wait_for("TTS(", 20)
            if not dtts:
                r["verdict"] = "no-response-to-barge-onto"
            else:
                time.sleep(1.2)          # TTS audível no meio
                t0 = time.monotonic()
                subprocess.run([player, wav], check=False)
                dkill, lkill = wait_for("TTS morto", 10)
                r["barge_reaction_s"] = round(time.monotonic() - t0 - 1.2, 2)
                r["kill_line"] = lkill.strip()[:80] if lkill else None
                r["verdict"] = "tts-killed" if dkill else "barge-not-kill"
            r["classify_line"] = None
        report["scenarios"].append(r)
        print(f"{expect:8s} {utt[:30]:30s} {r['verdict']}")
        time.sleep(2)
    stop[0] = True
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--trigger-bench", action="store_true")
    ap.add_argument("--unit-battery", action="store_true")
    ap.add_argument("--e2e-playback", action="store_true",
                    help="toca wavs no alto-falante e mede pela reação no log "
                         "duplex (janela combinada com OC; autorização dono 20/10)")
    ap.add_argument("--samples", type=int, default=20)
    ap.add_argument("--only", default="",
                    help="e2e: filtra cenários por classe (ex: BARGE,SILENCE)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--asr", default="http://127.0.0.1:8097")
    ap.add_argument("--classify", default="http://127.0.0.1:8092")
    ap.add_argument("--fixtures",
                    default="/tmp/opencode/night-microturn/kaggle-pkg")
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__),
                                                  "..", "reports", "duplex-eval"))
    args = ap.parse_args()
    if args.trigger_bench:
        report = trigger_bench(args)
    elif args.unit_battery:
        report = unit_battery(args)
    elif args.e2e_playback:
        report = e2e_playback(args)
    else:
        print(__doc__)
        return 1
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
