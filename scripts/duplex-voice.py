#!/usr/bin/env python3
"""duplex-voice.py — MODO VOZ FULL-DUPLEX v2 (17/10, instrumentado).

Arquitetura honesta (resposta à pergunta do dono):cascade + micro-turns —
o 35B é texto; ASR/TTS ficam FORA (speech-native puro não cabe em 6GB com
PT+tools). O que NÃO é igual ao loop antigo: sem VAD/endpointing, timing
é decisão DO MODELO (LoRA micro-turn, 0.6s/tick), barge-in real. Este
script MEDE cada estágio p/ achar onde a fluidez morre:

  [19:41:02] rms=  43 | <no voice>            → <listen>          llm=431ms
  [19:41:03] rms= 812 | "oi jarvis, tudo be"  → <listen>          asr=210ms llm=438ms
  [19:41:04] rms= 790 | "m com você"         → Tudo bem! Como     asr=205ms llm=445ms  TTS("Tudo bem! Como")

Rodar no env jarvis-voice (faster_whisper + kokoro + jarvis in-process):
  /nix/store/*-python3.13-jarvis-voice-0.1.0/bin/python3 scripts/duplex-voice.py
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

import numpy as np

TICK = 0.6
LISTEN, NOVOICE = "<listen>", "<no voice>"
LISTEN_P = 0.3
SYSTEM = ("You are a voice assistant in a live phone call; both sides can talk at the same time. Every "
          f"{TICK:g} seconds you get what the microphone heard in that moment, as a streaming transcript fragment, or "
          f"{NOVOICE}. You reply with up to three new words to say next, or {LISTEN} to add nothing.")
SR = 16000
CHUNK_BYTES = int(SR * TICK * 2)

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

# ---------------------------------------------------------------- ASR (persistente)
class Asr:
    def __init__(self, model_size, lang):
        from faster_whisper import WhisperModel
        voice_dir = os.environ.get("JARVIS_VOICE_DIR",
                                   os.path.expanduser("~/.local/share/jarvis/voice"))
        self.lang = lang
        t0 = time.monotonic()
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8",
                                  download_root=voice_dir)
        log(f"[{ts()}] asr: {model_size} carregado em {time.monotonic()-t0:.1f}s")
    def chunk_text(self, pcm_f32):
        t0 = time.monotonic()
        try:
            segs, _ = self.model.transcribe(pcm_f32, beam_size=3, language=self.lang,
                                             condition_on_previous_text=False,
                                             vad_filter=False)
            txt = " ".join(s.text for s in segs).strip()
            return txt, (time.monotonic() - t0) * 1000
        except Exception as exc:  # noqa: BLE001
            log(f"[{ts()}] asr ERRO: {exc}")
            return "", 0.0

# ---------------------------------------------------------------- TTS (in-process, worker)
class Tts:
    """Frase → jarvis.core.voice.speak (edge antonio/net ou kokoro local),
    in-process (sem spawn de CLI). Mede synth+play por frase."""
    def __init__(self):
        from jarvis.core.voice import speak
        self.speak = speak
        self.q = queue.Queue()
        self.last_ms = 0.0
        threading.Thread(target=self._worker, daemon=True).start()
    def say(self, text):
        if text.strip():
            self.q.put(text.strip())
    def _worker(self):
        while True:
            text = self.q.get()
            t0 = time.monotonic()
            try:
                out = self.speak(text, play=True)
                self.last_ms = (time.monotonic() - t0) * 1000
                if str(out).startswith("ERROR"):
                    log(f"[{ts()}] tts ERRO: {out}")
            except Exception as exc:  # noqa: BLE001
                log(f"[{ts()}] tts ERRO: {exc}")

# ---------------------------------------------------------------- mic
def mic_stream():
    # pw-record na fonte default (rnnoise da casa) — raw s16 no stdout.
    return subprocess.Popen(["pw-record", "--rate", str(SR), "--channels", "1",
                             "--format", "s16", "-"],
                            stdout=subprocess.PIPE, bufsize=CHUNK_BYTES)

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8085)
    ap.add_argument("--lang", default="pt")
    ap.add_argument("--stt-model", default="small")
    ap.add_argument("--rms", type=int, default=150,
                    help="gate de silêncio (ambiente rnnoise~70; fala 300+)")
    args = ap.parse_args()
    base = f"http://{args.host}:{args.port}"

    try:
        http(base + "/health")
    except Exception:
        sys.exit(f"duplex-voice: server {base} fora — systemctl start llama-duplex-35b")

    log(f"[{ts()}] acordando (LoRA apply)…")
    http(base + "/lora-adapters", [{"id": 0, "scale": 1.0}], timeout=600)
    log(f"[{ts()}] MODO DUPLEX. Fala com ele. Ctrl-C = dormir.\n")

    asr = Asr(args.stt_model, args.lang)
    tts = Tts()
    mic = mic_stream()
    history: list[tuple[str, str]] = []
    frase: list[str] = []
    quiet = 0
    running = True

    def _sair(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, _sair)

    tick_n = 0
    try:
        while running:
            t0 = time.monotonic()
            raw = mic.stdout.read(CHUNK_BYTES)
            heard, asr_ms, rms = NOVOICE, 0.0, 0
            if len(raw) == CHUNK_BYTES:
                pcm16 = np.frombuffer(raw, dtype=np.int16)
                rms = int(np.sqrt((pcm16.astype(np.float64) ** 2).mean()))
                if rms >= args.rms:
                    pcm = pcm16.astype("float32") / 32768.0
                    heard, asr_ms = asr.chunk_text(pcm)
                    if not heard:
                        heard = NOVOICE
            said, _p = tick_once(base, history, heard)
            history += [("user", heard), ("assistant", said)]
            llm_ms = (time.monotonic() - t0) * 1000 - asr_ms
            tick_n += 1

            if said == LISTEN:
                quiet += 1
            else:
                quiet = 0
                frase.append(said)
                if said.rstrip().endswith((".", "!", "?")) or len(frase) >= 3:
                    log(f"[{ts()}] rms={rms:>5} | TTS({selfless(frase)}) tts_anterior={tts.last_ms:.0f}ms")
                    tts.say(" ".join(frase)); frase = []
            if quiet >= 2 and frase:
                tts.say(" ".join(frase)); frase = []; quiet = 0

            # LINHA DE DEBUG por tick: rms | ouvido | dito | latências
            if heard != NOVOICE or said != LISTEN or tick_n % 20 == 0:
                log(f"[{ts()}] rms={rms:>5} | {heard[:24]:<24} → {said[:28]:<28} "
                    f"asr={asr_ms:4.0f}ms llm={llm_ms:4.0f}ms")

            dt = TICK - (time.monotonic() - t0)
            if dt > 0:
                time.sleep(dt)
    finally:
        log(f"\n[{ts()}] dormindo (LoRA off)…")
        try:
            http(base + "/lora-adapters", [])
        except Exception:
            pass
        mic.terminate()

def selfless(f):
    return " ".join(f)

if __name__ == "__main__":
    main()
