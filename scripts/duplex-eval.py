#!/usr/bin/env python3
"""duplex-eval.py — harness de eval do modo voz full-duplex (P5, noite 20/10, HB).

Spec completa: docs/DUPLEX-EVAL-DESIGN.md. Runner NOVO (zero colisão com lanes do
AGENTE-OC): só lê endpoints públicos (:8097 ASR / :8092 chat) — nunca escreve em
duplex-voice.py/asrd.

Métricas implementadas:
  --trigger-bench    hallucination-on-trigger: clips Scicom (silence/nonspeech/
                     music/reduplication, FLAC embutido no parquet) → POST /inference
                     no ASR live → taxa de saída não-vazia (alucinação) por categoria,
                     + kill-rate do GATE REAL (a mesma pilha de ramos do
                       duplex-asrd, via voice_gate.py, com paridade provada por
                       scripts/check-voice-gate-parity.py) e o proxy antigo
                       (igualdade exata nas listas TSV) para comparação.
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
          [--asr http://127.0.0.1:8097] [--fixtures ~/.local/share/jarvis/voice-trigger]
          [--out reports/duplex-eval]
       python3 scripts/duplex-eval.py --unit-battery [--classify http://127.0.0.1:8092]
EXEMPLO (smoke rápido): python3 scripts/duplex-eval.py --trigger-bench --samples 6
"""
import argparse, json, os, random, sys, time, urllib.request, uuid
from pathlib import Path

CLASS_SYS = ("Você é o JARVIS, assistente de voz. Classifique o turno do "
             "usuário em uma palavra: RESPOND (fala completa que pede "
             "resposta), WAIT (frase incompleta, mais vem), SILENCE "
             "(backchannel/ruído), ou BARGE (o dono interrompeu sua fala).")
CLASS_LABELS = ("RESPOND", "WAIT", "SILENCE", "BARGE")


def post_audio(asr: str, flac: bytes, timeout: float = 30.0) -> dict:
    """POST /inference multipart (stdlib, sem deps) — mesmo contrato do asrd."""
    boundary = uuid.uuid4().hex
    # (09/11, sweep-2026-11) response_format=verbose_json: e o que expoe
    # no_speech_prob/avg_logprob por segmento. Sem isso o /inference devolve so
    # {"text": ...} e o gate de audio do asrd (ns>0.35 ou lp<-0.45) nunca tem
    # com o que trabalhar.
    body = (f"--{boundary}\r\n"
           f"Content-Disposition: form-data; name=\"file\"; filename=\"clip.flac\"\r\n"
           f"Content-Type: audio/flac\r\n\r\n").encode() + flac + \
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
    # (09/11, sweep-2026-11) GATE REAL: o bench media um PROXY (igualdade
    # exata do texto em 2 TSV) e o gate de produção é uma pilha de ramos
    # (substring, greeting-fantasma, redup, "legenda", léxico gated,
    # ALL-CAPS, stats, tokens-vs-duração). Medir o proxy dá um número que
    # NÃO é o do gate. voice_gate.py é a lógica do asrd extraída verbatim,
    # com paridade provada por scripts/check-voice-gate-parity.py.
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from voice_gate import anti_halluc
    rng = random.Random(args.seed)
    report = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "asr": args.asr,
              "samples_per_cat": args.samples, "seed": args.seed,
              "categories": {}, "note": "gate medido = gate REAL do duplex-asrd "
              "(voice_gate.py, paridade provada por check-voice-gate-parity.py); "
              "lexicon_kill = proxy antigo (igualdade exata em 2 TSV)"}
    # (09/11, sweep-2026-11) `observed` e a lista ACUMULADA de todos os textos
    # alucinados (o comentario do deny-list diz "TODOS"). Antes ela nascia
    # DENTRO do loop de categoria e era lida FORA dele => UnboundLocalError
    # (o bench nem rodava: era parte do 0/10).
    observed = []
    observed_gate = []
    samples_all = []
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
        gate_killed, gate_det = 0, 0
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
                # (09/11, sweep-2026-11) STATS DE AUDIO: o gate v6 do asrd
                # so mata a frase do lexico se o audio TAMBEM for fraco
                # (no_speech_prob alto / avg_logprob baixo). Sem os stats no
                # report, a simulacao de kill do bench era a lista CRUA e
                # media pessimista. O whisper-server devolve os stats em
                # "transcription", com uma lista por segmento.
                _segs = out.get("segments") or []   # verbose_json expoe os stats em segments
                _ns = max([float(s.get("no_speech_prob", 0.0) or 0.0)
                           for s in _segs] or [0.0])
                _lp = min([float(s.get("avg_logprob", 0.0) or 0.0)
                           for s in _segs] or [0.0])
                # (09/11, sweep-2026-11) GATE REAL: aplica a MESMA pilha de
                # ramos do asrd. A duração vem dos timestamps dos segmentos
                # (a visão do ASR), que é o que o gate usa no teste
                # tokens-vs-duração.
                _starts = [float(s.get("start", 0.0) or 0.0) for s in _segs]
                _ends = [float(s.get("end", 0.0) or 0.0) for s in _segs]
                _dur = (max(_ends) - min(_starts)) if _segs else 0.0
                _gate_out = anti_halluc(text, _segs, _dur)
                _gate_kill = (_gate_out == "")
                gate_killed += _gate_kill
                # kill SEM stats fracos = ramo determinístico (substring,
                # greeting-fantasma, redup, "legenda", tokens-vs-duração)
                if _gate_kill and not (_ns > 0.35 or _lp < -0.45):
                    gate_det += 1
                samples.append({"id": row.get("id"), "text": text[:60],
                                "lexicon_kill": inlist,
                                "gate_kill": _gate_kill,
                                "no_speech_prob": _ns,
                                "avg_logprob": _lp,
                                "stats_weak": (_ns > 0.35 or _lp < -0.45)})
                # (09/11) estado completo por amostra, para que a análise
                # offline chame o gate REAL (voice_gate.anti_halluc) sem
                # precisar do ASR: segmentos crus + duração + veredito.
                samples_all.append({"cat": cat, "id": str(row.get("id")),
                                    "text": text, "ns": _ns, "lp": _lp,
                                    "dur": _dur, "segs": _segs,
                                    "gate_kill": bool(_gate_kill),
                                    "lexicon_kill": bool(inlist)})
                # (09/11) TAB dentro do texto alucinado quebrava o TSV do
                # feed (63 de 150 linhas saíam com nº de campos errado e a
                # curation lia menos amostras do que existiam). O texto vai
                # pro feed com TAB e newline trocados por espaço.
                _txt_feed = " ".join(text.replace("\t", " ").replace("\n", " ").split())
                observed.append(f"{cat}\t{row.get('id')}\t{_txt_feed}\t{_ns:.4f}\t{_lp:.4f}")
                # o veredito do gate vai num feed SEPARADO: o arquivo de
                # curation (5 colunas) não muda de formato, e quem curar
                # sabe na hora o que o gate REAL já mata (77 de 111 no
                # último bench: curar isso é trabalho jogado fora).
                observed_gate.append(f"{cat}\t{row.get('id')}\t{_txt_feed}\t{_ns:.4f}\t{_lp:.4f}\t{int(_gate_kill)}")
        n = empty + hallo
        report["categories"][cat] = {
            "clips": n, "empty_ok": empty, "hallucinated": hallo,
            "halluc_rate": round(hallo / n, 3) if n else None,
            "lexicon_kill": killed,
            "net_rate_apos_lista": round((hallo - killed) / n, 3) if n else None,
            "gate_kill": gate_killed,
            "gate_kill_deterministico": gate_det,
            "net_rate_apos_gate": round((hallo - gate_killed) / n, 3) if n else None,
            "errors": errs, "samples": samples[:8]}
        print(f"{cat}: {hallo}/{n} alucinou ({report['categories'][cat]['halluc_rate']})"
              f" | gate REAL mata {gate_killed} (det {gate_det})"
              f" | proxy lista mataria {killed} | erros {errs}")
    # feed p/ o deny-list (lane OC): TODOS os textos alucinados observados
    if observed:
        obs = os.path.join(args.out, "hallucinations-observed.txt")
        os.makedirs(args.out, exist_ok=True)
        with open(obs, "a", encoding="utf-8") as f:
            f.write(f"# {report['ts']} asr={args.asr} samples/cat={args.samples}\n")
            f.write("\n".join(observed) + "\n")
        report["hallucinations_observed_file"] = obs
    # (09/11) feed com o veredito do gate (6 colunas), para a curation saber
    # o que o gate REAL já mata: 77 das 111 alucinações do último bench já
    # morrem no gate, e curar essas frases é trabalho jogado fora.
    if observed_gate:
        obsg = os.path.join(args.out, "hallucinations-observed-gate.tsv")
        os.makedirs(args.out, exist_ok=True)
        with open(obsg, "a", encoding="utf-8") as f:
            f.write(f"# {report['ts']} asr={args.asr} samples/cat={args.samples}"
                    f"  cols: cat id text ns avg_logprob gate_kill\n")
            f.write("\n".join(observed_gate) + "\n")
        report["hallucinations_observed_gate_file"] = obsg
    # (09/11, sweep-2026-11) estado por amostra em JSONL: segmentos crus +
    # duração + veredito do gate. É o que permite chamar o gate REAL
    # offline (voice_gate.anti_halluc) e medir cenários sem re-rodar o ASR.
    if samples_all:
        os.makedirs(args.out, exist_ok=True)
        jsl = os.path.join(args.out, f"trigger-samples-{report['ts'].replace(':', '')}.jsonl")
        with open(jsl, "w", encoding="utf-8") as f:
            for s in samples_all:
                f.write(json.dumps(s, ensure_ascii=False) + "\n")
        report["samples_jsonl"] = jsl
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

    def wait_response(timeout=15.0):
        """Marcador de resposta: streaming novo loga 'tts.say' por sentença;
        legado logava 'TTS('. Um OU outro (deploy 13:02 matou o legado)."""
        dt, ln = wait_for("tts.say", timeout)
        if not dt:
            dt, ln = wait_for("TTS(", 0.1)
        return dt, ln

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
            dt, lresp = wait_response(25)
            r["timespeak_s"] = round(dseg + dt, 2) if dseg and dt else None
            dcls, lcls = wait_for("classify", 10)
            r["classify_line"] = lcls.strip()[:80] if lcls else None
            r["verdict"] = "ok" if lresp else "no-response"
        elif expect == "SILENCE":
            dcls, lcls = wait_for("classify", 12)
            ok_sil = lcls and ("SILENCE" in lcls or "silêncio" in lcls or "backchannel" in lcls)
            r["verdict"] = "ok-silenced" if ok_sil else ("classified" if lcls else "no-segment")
        else:  # BARGE fase-3 v2: pergunta LONGA → resposta longa → barge DENTRO
               # da fala (a) OC: TTS curto morria antes do classify chegar.
            qwav = os.path.join(WAVS, "utt_124_long.wav")
            subprocess.run([player, qwav], check=False)
            dtts, ltts = wait_response(30)
            if not dtts:
                r["verdict"] = "no-response-to-barge-onto"
            else:
                time.sleep(2.5)          # solidemente DENTRO da fala longa
                t0 = time.monotonic()
                subprocess.run([player, wav], check=False)
                dkill, lkill = wait_for("TTS morto", 15)
                r["barge_reaction_s"] = round(time.monotonic() - t0 - 2.5, 2)
                r["kill_line"] = lkill.strip()[:90] if lkill else None
                r["verdict"] = "tts-killed" if dkill else "barge-not-kill"
            r["classify_line"] = None
        report["scenarios"].append(r)
        print(f"{expect:8s} {utt[:30]:30s} {r['verdict']}")
        time.sleep(2)
    stop[0] = True
    return report


# ── (06/11) E2E VIA GANCHO DE ASR (o AEC cancela a caixa de som, então
# tocar WAV no alto-falante NÃO chega ao mic — o dono ouve, o JARVIS não).
# O WAV entra no asrd pelo mesmo caminho do microfone: exercita
# ASR+VAD+merge+gate+classificador+LLM+tools+TTS reais.
ACTION_TOOLS = ("tool", "jarvis", "shell", "execute_shell", "notify")


def wav_inject(args) -> dict:
    import shutil, subprocess, threading
    LOG = args.log or os.path.join(
        os.path.dirname(__file__), "..", "logs", "duplex",
        time.strftime("%Y-%m-%d") + ".log")
    LOG = os.path.abspath(LOG)
    WAVS = args.wavs
    items = [json.loads(l) for l in open(
        os.path.join(os.path.dirname(__file__), "..", "data",
                     "duplex-eval-turntaking.jsonl"), encoding="utf-8")
        if l.strip() and not l.lstrip().startswith("#")]
    by = {}
    for i, it in enumerate(items):
        by.setdefault(it["gold"], []).append((i, it["utt"]))
    scen = [(i, u, "RESPOND") for i, u in by["RESPOND"][:10]]
    scen += [(i, u, "BARGE") for i, u in by["BARGE"][:5]]
    scen += [(i, u, "SILENCE") for i, u in by["SILENCE"][:5]]
    want = {x.strip().upper() for x in args.only.split(",") if x.strip()}

    seen = os.path.getsize(LOG) if os.path.exists(LOG) else 0
    lines = []
    stop = [False]

    def follow():
        pos = seen
        while not stop[0]:
            try:
                sz = os.path.getsize(LOG)
                if sz < pos:
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
            time.sleep(0.1)
    threading.Thread(target=follow, daemon=True).start()

    def wait_for(pat, timeout=15.0, since=None):
        t0 = time.monotonic()
        while time.monotonic() - t0 < timeout:
            for t, ln in lines:
                if (since is None or t > since) and pat in ln:
                    return t - t0, ln
            time.sleep(0.05)
        return None, None

    report = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "route": "asr-inject",
              "log": LOG, "scenarios": []}
    time.sleep(0.5)
    for idx, utt, expect in scen:
        if want and expect not in want:
            continue
        wav = os.path.join(WAVS, f"utt_{idx:03d}.wav")
        if not os.path.exists(wav):
            report["scenarios"].append({"utt": utt, "expect": expect,
                                        "verdict": "sem-wav"})
            continue
        mark = time.monotonic()
        # (06/11) UM cenário por vez: a fila acumulava quando o loop
        # estava ocupado (a resposta anterior ainda falando) e o ASR
        # ficava UM turno atrás (a transcrição batia com o cenário
        # anterior). Drena a fila antes de cada injeção.
        os.makedirs("/tmp/duplex-inject-queue", exist_ok=True)
        # (06/11) NÃO apaga o que está pendente: o loop do cliente pode
        # estar ocupado (LLM lento) e o WAV seria destruído antes de
        # ser consumido → "sem-segmento" em cascata.
        shutil.copyfile(wav, "/tmp/duplex-inject-queue/"
                        + time.strftime("%H%M%S") + f"-{idx:03d}.wav")
        wait_for("WAV INJETADO", 8, since=mark)
        # (06/11) casa o segmento pelo CONTEÚDO, não pela ordem: o loop
        # do cliente bloqueia no LLM (10-20s) e o segmento do turno N
        # aparecia na janela do turno N+1 (a bateria mediava a fila, não
        # a qualidade). Tokens em comum >= 50% = o segmento é o do
        # cenário.
        _qt = set(w.lower().strip(".,!?") for w in utt.split()
                  if len(w) > 2)
        dseg, lseg = None, None
        _t_end = time.monotonic() + 40
        while time.monotonic() < _t_end:
            for _t, _ln in lines:
                if _t <= mark or "SEGMENTO:" not in _ln:
                    continue
                _txt = _ln.split("SEGMENTO:", 1)[-1].strip().lower()
                _st = set(w.strip(".,!?") for w in _txt.split()
                          if len(w) > 2)
                if _qt and (len(_qt & _st) / len(_qt)) >= 0.5:
                    dseg, lseg = _t - mark, _ln
                    break
            if dseg is not None:
                break
            time.sleep(0.1)
        r = {"utt": utt, "expect": expect, "wav": os.path.basename(wav)}
        if not dseg:
            r["verdict"] = "sem-segmento"
            report["scenarios"].append(r)
            print(f"{expect:8s} {utt[:28]:28s} -> sem-segmento")
            continue
        # texto transcrito (o ouvido)
        r["asr_text"] = lseg.split("SEGMENTO:", 1)[-1].strip()[:80]
        dcls, lcls = wait_for("classify", 8, since=mark)
        r["classify_line"] = lcls.strip()[:100] if lcls else None
        # resposta falada + tools
        dresp, lresp = wait_for("tts.say", 18, since=mark)
        r["timespeak_s"] = round(dseg + dresp, 2) if (dseg and dresp) else None
        said = []
        for t, ln in lines:
            if t > mark and "tts.say:" in ln:
                said.append(ln.split("tts.say:", 1)[-1].strip()[:120])
        r["said"] = " ".join(said)[:220]
        tools = [ln.split("TOOL:", 1)[-1].strip()[:60] for t, ln in lines
                 if t > mark and "TOOL:" in ln]
        r["tools"] = tools
        r["action_tool"] = any(any(a in t.lower() for a in ACTION_TOOLS)
                               for t in tools)
        # (06/11) SATISFICING: a fala anuncia uma ação ("está ajustando",
        # "vou mudar", "feito") sem nenhuma tool de ação → mentiu.
        low = r["said"].lower()
        claim = any(k in low for k in ("está ajustando", "esta ajustando",
                                       "vou mudar", "vou ajustar", "vou fazer",
                                       "já fiz", "foi feito", "ajustei",
                                       "mudei", "configurei", "confirmado",
                                       "está feito"))
        r["claim_without_action"] = bool(claim and not r["action_tool"])
        if expect == "RESPOND":
            r["verdict"] = ("ok" if dresp else "no-response")
            if r["claim_without_action"]:
                r["verdict"] = "claim-sem-acao"
        elif expect == "SILENCE":
            sil = lcls and ("SILENCE" in lcls or "backchannel" in lcls
                            or "silêncio" in lcls)
            r["verdict"] = "ok-silenced" if (sil and not dresp) else (
                "respondeu" if dresp else "no-classify")
        else:
            # BARGE: o certo é o classificador dizer BARGE (a versionsão
            # que mata o TTS) — não basta existir uma linha de classify.
            _is_barge = bool(lcls and "BARGE" in lcls)
            r["verdict"] = ("ok-barge" if _is_barge else
                            ("classificado-outra" if lcls else "no-classify"))
        report["scenarios"].append(r)
        print(f"{expect:8s} {utt[:28]:28s} -> {r['verdict']:16s} "
              f"asr={r.get('asr_text','')[:22]:22s} ts={r.get('timespeak_s')}")
        # deixa o turno anterior terminar (TTS + reaction) antes do próximo
        time.sleep(3.0)
    stop[0] = True
    n = len(report["scenarios"])
    ok = sum(1 for s in report["scenarios"] if s.get("verdict", "").startswith("ok"))
    claim = sum(1 for s in report["scenarios"] if s.get("claim_without_action"))
    report["summary"] = {"n": n, "ok": ok, "claim_without_action": claim,
                          "ok_rate": round(ok / n, 3) if n else None}
    print("RESUMO:", report["summary"])
    return report


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--trigger-bench", action="store_true")
    ap.add_argument("--unit-battery", action="store_true")
    ap.add_argument("--wav-inject", action="store_true",
                    help="E2E via gancho de ASR (WAV entra no asrd; o AEC "
                         "cancelaria a caixa de som)")
    ap.add_argument("--log", default="",
                    help="log do cliente (padrão: o log diário real do "
                         "próprio duplex — o jarvis heal reinicia a voz "
                         "sozinho e esse processo NÃO escreve no /tmp)")
    ap.add_argument("--wavs", default="/tmp/opencode/night-microturn/"
                                        "genuine-synth-wavs")
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
                    # (09/11, coord-naming) fixture de eval NAO vive em /tmp:
                    # a limpeza levou os parquets e o bench virou 'sem fixtures' nas
                    # 4 categorias. Destino duravel, o mesmo do gerador
                    # scripts/voice-trigger-fixtures.py.
                    default=str(Path.home() / ".local/share/jarvis/voice-trigger"))
    ap.add_argument("--out", default=os.path.join(os.path.dirname(__file__),
                                                  "..", "reports", "duplex-eval"))
    args = ap.parse_args()
    if args.wav_inject:
        report = wav_inject(args)
    elif args.trigger_bench:
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
