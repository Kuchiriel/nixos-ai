#!/usr/bin/env python3
"""duplex-voice.py — MODO VOZ FULL-DUPLEX v6 (madrugada 18/10, reescrita).

A cadeia: mic (pw-record PIPE --container raw) → [reader thread] → tick
wall-clock 0.6s → janelas 1.2s (pares) → gate RMS → [ASR worker: whisper
small int8 + VAD + anti-alucinação] → micro-turn /completion (LoRA
runtime no llama-duplex-35b) → fala ≤3 palavras ou <listen> → frases →
[TTS worker: kokoro in-process] → alto-falante. Barge-in grátis: o tick
vê o que tu falou por cima e o modelo decide voltar a escutar.

Lies da madrugada (todas pagas em teste, ver docs/VOZ-FULL-DUPLEX.md):
- pw-record com "-" emite CONTAINER AU (magic ".snd") sem --container raw
  → stream inteira desalinhada (pedestal rms 380-426, VAD surdo).
- Abrir o mic logo após matar o wakeword = link em node moribundo → mic
  primeiro, daemon morre depois (streams paralelas são suportadas).
- Loop lendo 0.6s bloqueante + tick 350ms = cadência ~0.95s → backlog
  cresce SEMPRE → cliente vira escuta do passado + queue-cap derruba os
  pares altos. Fix: READER thread + tick pelo relógio + drain-último.
- 1ª inferência do ctranslate2 = ~2-10s → warmup no boot.
- whisper sem cap de threads rouba os P-cores do llama (taskset E-cores +
  cpu_threads=3; llama pinned P-cores 0-11 pelo launcher).
- "Legendas pela comunidade" = alucinação clássica do whisper (forced-pt
  sobre fundo) → VAD Silero + avg_logprob>=-0.60 + no_speech<=0.6.

USO: scripts/duplex-voice-run.sh (env composto + E-cores + taskset)
"""
from __future__ import annotations

import argparse
import json
import math
import os
import queue
import signal
import subprocess
import sys
import threading
import time
import urllib.request
from datetime import datetime
from pathlib import Path

import numpy as np

TICK = 0.6
LISTEN, NOVOICE = "<listen>", "<no voice>"
LISTEN_P = 0.3
SYSTEM = ("You are a voice assistant in a live phone call; both sides can talk at the same time. Every "
          f"{TICK:g} seconds you get what the microphone heard in that moment, as a streaming transcript fragment, or "
          f"{NOVOICE}. You reply with up to three new words to say next, or {LISTEN} to add nothing.")
SR = 16000
CHUNK_BYTES = int(SR * TICK * 2)
# Digital mic (17/10): o Stereo Mic é MORTO (rms 0); o Digital é vivo.
MIC_SOURCE = "alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source"
VAD_PARAMS = dict(threshold=0.45, min_speech_duration_ms=200,
                  min_silence_duration_ms=300, speech_pad_ms=160)

def log(msg):
    print(msg, file=sys.stderr, flush=True)

def ts():
    return datetime.now().strftime("%H:%M:%S")

# ---------------------------------------------------------------- HTTP
def http(url, payload=None, timeout=180):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))

def tick_once(base, history, heard):
    prompt = f"<|im_start|>system\n{SYSTEM}<|im_end|>\n"
    for role, content in history + [("user", heard)]:
        prompt += f"<|im_start|>{role}\n{content}<|im_end|>\n"
    body = {"prompt": prompt + "<|im_start|>assistant\n", "n_predict": 64,
            "temperature": 0, "stop": ["<|im_end|>"], "cache_prompt": True,
            "n_probs": 8}
    j = http(base + "/completion", body)
    out = j["content"].strip()
    top = j["completion_probabilities"][0]["top_logprobs"]
    listen_ids = [p["id"] for p in top if p["token"].startswith("<")]
    p_listen = sum(math.exp(p["logprob"]) for p in top if p["token"].startswith("<"))
    if out.startswith("<") and p_listen < LISTEN_P and listen_ids:
        body.update({"logit_bias": [[i, False] for i in listen_ids], "n_probs": 0})
        out = http(base + "/completion", body)["content"].strip()
    return (LISTEN if out.startswith("<") else out), p_listen

# ---------------------------------------------------------------- mic
def mic_stream():
    return subprocess.Popen(["pw-record", "--rate", str(SR), "--channels", "1",
                             "--format", "s16", "--container", "raw",
                             "--target", MIC_SOURCE, "-"],
                            stdout=subprocess.PIPE, bufsize=CHUNK_BYTES)

def mic_reader(mic, out_q):
    """Thread leitora: bloca no read e empurra chunk; fila curta derruba o
    MAIS VELHO (tempo real = o atraso nunca cresce; stall = descarta)."""
    while True:
        raw = mic.stdout.read(CHUNK_BYTES)
        if not raw or len(raw) != CHUNK_BYTES:
            out_q.put(None)  # stream morreu → main decide reabrir
            return
        try:
            out_q.put_nowait(raw)
        except queue.Full:
            try:
                out_q.get_nowait()
            except queue.Empty:
                pass
            try:
                out_q.put_nowait(raw)
            except queue.Full:
                pass

# ---------------------------------------------------------------- ASR
class Asr:
    """Cliente do duplex-asrd.py (subprocess stdio, venv karaok — 18/10
    03:15): o multiprocessing.spawn envenenava o VAD do faster-whisper
    (0 timestamps). Subprocess = o contexto standalone comprovado.
    Protocolo: JSON lines com audio base64."""
    def __init__(self, model_size, lang):
        # (05:20) asrd nos P-CORES (0-11): o llama usa 6 de 12 threads —
        # sobra 6 P-threads; o whisper nos E-cores (2.1GHz×4) engargalava
        # a 20s sob contenção. Pinned junto do llama = justo e rápido.
        self.proc = subprocess.Popen(
            ["taskset", "-c", "0-11",
             "/home/nixos/projects/karaok/.venv/bin/python3",
             str(Path(__file__).with_name("duplex-asrd.py"))],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            text=True, bufsize=1)
        linha = self.proc.stdout.readline()   # espera {"ready": true}
        log(f"[{ts()}] asrd pronto: {linha.strip()[:60]}")
        self.last_ms = 0.0
    def feed(self, pcm_f32):
        import base64
        try:
            self.proc.stdin.write(json.dumps(
                {"audio_b64": base64.b64encode(
                    np.asarray(pcm_f32, dtype="<f4").tobytes()).decode()}) + "\n")
            self.proc.stdin.flush()
        except Exception:
            pass
    def take(self):
        # não-bloqueante: readline só se há linha pronta (select 0s)
        import select
        try:
            r, _, _ = select.select([self.proc.stdout], [], [], 0)
            if not r:
                return None
            linha = self.proc.stdout.readline()
            if not linha:
                return None
            j = json.loads(linha)
            self.last_ms = float(j.get("ms", 0))
            if j.get("text"):
                return j
            return j if j.get("filtered") else None
        except Exception:
            return None
    def close(self):
        try:
            self.proc.stdin.close()
            self.proc.wait(timeout=2)
        except Exception:
            self.proc.kill()

# ---------------------------------------------------------------- TTS
class Tts:
    """Cliente do daemon duplex-ttsd (18/10, 02:45): o kokoro só existe
    no env jarvis, mas o ctranslate2 DELE é 30× mais lento — então o ASR
    roda neste processo (karaok venv) e o TTS num daemon separado no env
    jarvis, kokoro carregado UMA vez. FIFO JSON; o daemon morre com o
    cliente (__exit)."""
    FIFO = "/tmp/jarvis-duplex-tts.fifo"
    def __init__(self, speaking):
        self.speaking = speaking
        self.q = queue.Queue()
        self.last_ms = 0.0
        self.daemon = None
        threading.Thread(target=self._worker, daemon=True).start()
    def _ensure_daemon(self):
        import subprocess as sp
        # já vivo? (fifo aberto por outro processo + processo existe)
        if self.daemon and self.daemon.poll() is None:
            return
        w = "/run/current-system/sw/bin/jarvis"
        boot = Path(__file__).resolve()
        envbin = Path(sp.run(["readlink", "-f", w], capture_output=True,
                             text=True).stdout.strip()).parent.parent / "bin"
        # python do env jarvis = shebang do bootstrap
        bootf = envbin / "..jarvis-wrapped-wrapped"
        pybin = bootf.read_text().splitlines()[0][2:]
        sitedirs = sp.run(["bash", "-c",
                           f"grep -oE \"'/nix/store/[^']*site-packages[^']*'\" {bootf}"],
                          capture_output=True, text=True).stdout
        import shlex
        spath = ":".join(sorted(set(x.strip("'") for x in sitedirs.split())))
        self.daemon = sp.Popen(
            ["env", f"PYTHONPATH={spath}", pybin,
             str(Path(__file__).with_name("duplex-ttsd.py"))],
            stdout=sp.DEVNULL, stderr=sp.DEVNULL)
        time.sleep(0.2)
    def say(self, text):
        if text.strip():
            # eco: o mic ouve o PRÓPRIO TTS e o modelo responde a si
            # ("Okay" em loop, 18/10). Janela = synth+play estimado
            # (chars×90ms) + 500ms de cauda — o loop suprime feed nela.
            import re as _re
            n = len(_re.sub(r"\W", "", text))
            self.speaking["until"] = max(self.speaking["until"],
                                         time.monotonic() + n * 0.09 + 0.5)
            self.q.put(text.strip())
    def _worker(self):
        while True:
            text = self.q.get()
            t0 = time.monotonic()
            try:
                self._ensure_daemon()
                with open(self.FIFO, "w") as f:
                    f.write(json.dumps({"text": text}) + "\n")
                self.last_ms = (time.monotonic() - t0) * 1000
            except Exception as exc:  # noqa: BLE001
                log(f"[{ts()}] tts ERRO: {exc}")
    def close(self):
        try:
            with open(self.FIFO, "w") as f:
                f.write(json.dumps({"text": "__exit__"}) + "\n")
            if self.daemon:
                self.daemon.wait(timeout=5)
        except Exception:
            if self.daemon:
                self.daemon.kill()

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8085)
    ap.add_argument("--lang", default="pt")
    ap.add_argument("--stt-model", default="small")
    ap.add_argument("--rms", type=int, default=700,
                    help="gate fala-vs-fundo (vozes reais 886-1372; anime 380-600)")
    args = ap.parse_args()
    base = f"http://{args.host}:{args.port}"

    try:
        http(base + "/health")
    except Exception:
        sys.exit(f"duplex-voice: server {base} fora — systemctl start llama-duplex-35b")

    # MIC PRIMEIRO (node vivo), depois exclusividade + acordar.
    mic = mic_stream()
    time.sleep(1.5)
    Path("/tmp/jarvis-duplex-mode.flag").touch()   # heal respeita (17/10)
    subprocess.run(["systemctl", "--user", "stop", "jarvis-wakeword.service"],
                   capture_output=True)
    log(f"[{ts()}] wakeword pausado (flag pro heal) — mic aberto antes, node vivo")
    log(f"[{ts()}] acordando (LoRA apply)…")
    http(base + "/lora-adapters", [{"id": 0, "scale": 1.0}], timeout=600)
    log(f"[{ts()}] MODO DUPLEX. Fala com ele. Ctrl-C = dormir.\n")

    speaking = {"until": 0.0}   # self-mute anti-eco (18/10 ~06h)
    asr = Asr(args.stt_model, args.lang)
    tts = Tts(speaking)
    mic_q = queue.Queue(maxsize=6)
    threading.Thread(target=mic_reader, args=(mic, mic_q), daemon=True).start()

    history: list[tuple[str, str]] = []
    frase: list[str] = []
    quiet = 0
    tick_n = 0
    prev_pcm, prev_rms = None, 0
    zeros = 0
    running = True

    def _sair(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, _sair)

    next_t = time.monotonic()
    try:
        while running:
            next_t += TICK
            t0 = time.monotonic()
            heard = NOVOICE
            # (05:00, v6.4) CONSOME TUDO, pareia CONSECUTIVO: o tick LLM
            # (~400ms) + 1-chunk-por-iteração = deficit 40% → reader dropava
            # → pares com BURACO no meio (fragmento+salto+fragmento) → VAD
            # recusava (e bem!). Agora: drena tudo, pares de chunks
            # consecutivos (janela 1.2s contínua), sobra ímpar vira pendente
            # p/ próxima iteração. Fila 6 = 3.6s de folga sem drop.
            chunks: list = []
            try:
                while True:
                    c = mic_q.get_nowait()
                    if c is None:   # stream morreu → reabre
                        log(f"[{ts()}] mic stream morta — reabrindo")
                        mic.terminate()
                        mic = mic_stream()
                        threading.Thread(target=mic_reader, args=(mic, mic_q),
                                          daemon=True).start()
                        continue
                    chunks.append(c)
            except queue.Empty:
                pass
            if not chunks:
                chunks = [mic_q.get()]   # nada novo: espera o próximo (pace natural)
            if prev_pcm is not None:
                chunks.insert(0, prev_pcm)
            # rms do tick = o do último chunk consumido (visibilidade)
            last16 = np.frombuffer(chunks[-1], dtype=np.int16) if isinstance(chunks[-1], (bytes, bytearray)) else chunks[-1]
            rms = int(np.sqrt((np.asarray(last16, dtype=np.int16).astype(np.float64) ** 2).mean()))
            zeros = zeros + 1 if rms == 0 else 0
            # pares CONSECUTIVOS:
            i = 0
            while i + 1 < len(chunks):
                a16 = chunks[i] if isinstance(chunks[i], np.ndarray) else np.frombuffer(chunks[i], dtype=np.int16)
                b16 = chunks[i+1] if isinstance(chunks[i+1], np.ndarray) else np.frombuffer(chunks[i+1], dtype=np.int16)
                pair = np.concatenate([a16, b16]).astype("float32") / 32768.0
                prms = int(np.sqrt((pair ** 2).mean()) * 32768)
                if prms >= args.rms and time.monotonic() < speaking["until"]:
                    pass  # própria voz tocando: eco suprimido
                elif prms >= args.rms:
                    asr.feed(pair)
                i += 2
            prev_pcm = chunks[-1] if (len(chunks) - i == 1) else None
            r = asr.take()
            if isinstance(r, dict):
                if r.get("text"):
                    heard = r["text"]
                elif r.get("filtered"):
                    log(f"[{ts()}] asrd FILTRO: raw={r.get('raw','')!r} "
                        f"lp={r.get('lp')} ns={r.get('ns')}")

            said, _p = tick_once(base, history, heard)
            history += [("user", heard), ("assistant", said)]
            llm_ms = (time.monotonic() - t0) * 1000
            tick_n += 1

            if said == LISTEN:
                quiet += 1
            else:
                quiet = 0
                frase.append(said)
                print(f"  ouvi: {heard:<28} digo: {said}  (asr {asr.last_ms:.0f}ms)",
                      flush=True)
                if said.rstrip().endswith((".", "!", "?")) or len(frase) >= 3:
                    log(f"[{ts()}] TTS({' '.join(frase)})")
                    tts.say(" ".join(frase)); frase = []
            if quiet >= 2 and frase:
                tts.say(" ".join(frase)); frase = []; quiet = 0

            if (heard != NOVOICE or said != LISTEN or rms >= args.rms
                    or tick_n % 20 == 0):
                log(f"[{ts()}] rms={rms:>5} | {heard[:24]:<24} → {said[:28]:<28} "
                    f"asr={asr.last_ms:4.0f}ms llm={llm_ms:4.0f}ms"
                    f"{' ZERO×' + str(zeros) if zeros else ''}")

            dt = next_t - time.monotonic()
            if dt > 0:
                time.sleep(dt)
    finally:
        log(f"\n[{ts()}] dormindo (LoRA off)…")
        try:
            http(base + "/lora-adapters", [])
        except Exception:
            pass
        mic.terminate()
        asr.close()
        tts.close()
        subprocess.run(["systemctl", "--user", "start", "jarvis-wakeword.service"],
                       capture_output=True)
        Path("/tmp/jarvis-duplex-mode.flag").unlink(missing_ok=True)
        log(f"[{ts()}] dormindo: LoRA off, wakeword de volta, flag removida")

if __name__ == "__main__":
    main()
