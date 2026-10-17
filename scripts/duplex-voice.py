#!/usr/bin/env python3
"""duplex-voice.py — o MODO VOZ FULL-DUPLEX do JARVIS (17/10).

Fala E ouve ao mesmo tempo: micro-turn protocol (0.6s/tick, card do LoRA
codacus MicroTurn-Duplex, byte-for-byte) sobre o llama-server duplex-35b
(:8085, gerado de models.nix directServers — binário stock v0.7.0).

O ciclo por tick:
  mic 0.6s → faster-whisper (pt, int8, CPU, modelo PERSISTENTE) → fragmento
  → /completion (história append-only, prompt-cache retoma) → ≤3 palavras
  ou <listen> → regra speak-or-listen (P("<") ≥ 0.3 = escuta; senão BAN)
  → fragmentos viram frases (limpa em pontuação OU pausa) → jarvis speak
  (kokoro) → aplay. Barge-in grátis: o próximo tick vê o que tu falou por
  cima da resposta e o modelo decide voltar a escutar.

"acordar" (início)  = POST /lora-adapters [{"id":0,"scale":1.0}] (runtime!)
"dormir"  (Ctrl-C)  = POST [] — o LoRA sai, o 35B segue servindo TEXTO.

USO (venv do karaok: faster-whisper+ctranslate2; devShell NÃO tem):
  sudo systemctl start llama-duplex-35b          # o server (só 1x; fica de pé)
  ~/projects/karaok/.venv/bin/python3 scripts/duplex-voice.py
  (jarvis speak/aplay/arecord vêm do PATH do sistema)
FLAGS: --port 8085 --lang pt --stt-model small
PROVA do protocolo: /tmp/opencode/microturn-test/demo-stock.log +
docs/VOZ-FULL-DUPLEX.md (interrompeu "Stop! Do not mix those two..." na
hora exata, 576ms/tick mediana na 6GB).
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

TICK = 0.6
LISTEN, NOVOICE = "<listen>", "<no voice>"
LISTEN_P = 0.3
SYSTEM = ("You are a voice assistant in a live phone call; both sides can talk at the same time. Every "
          f"{TICK:g} seconds you get what the microphone heard in that moment, as a streaming transcript fragment, or "
          f"{NOVOICE}. You reply with up to three new words to say next, or {LISTEN} to add nothing.")
SR = 16000
CHUNK_BYTES = int(SR * TICK * 2)  # s16 mono

# ---------------------------------------------------------------- HTTP
def http(url, payload=None, timeout=180):
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data,
                                  headers={"Content-Type": "application/json"})
    return json.load(urllib.request.urlopen(req, timeout=timeout))

def lora_apply(base, on):
    """Runtime toggle (POST /lora-adapters) — 'acordar'/'dormir'."""
    adapters = http(base + "/lora-adapters") or []
    if on:
        return http(base + "/lora-adapters",
                    [{"id": a["id"], "scale": a.get("scale", 1.0)} for a in adapters],
                    timeout=600)  # 1ª aplicação pode demorar (buffers)
    return http(base + "/lora-adapters", [])

def tick_once(base, history, heard):
    """Um micro-turn — cópia fiel do microturn_client.py (card codacus)."""
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

# ---------------------------------------------------------------- STT
VOICE_DIR = os.environ.get("JARVIS_VOICE_DIR", os.path.expanduser("~/.local/share/jarvis/voice"))

class Asr:
    """faster-whisper PERSISTENTE (o transcribe() do core/voice recarrega
    o modelo a cada chamada — inaceitável a cada 0.6s). Roda no venv do
    karaok (faster-whisper + ctranslate2 lá; o devShell do nixos-ai NÃO
    tem — 17/10, ModuleNotFoundError na 1ª tentativa do dono)."""
    def __init__(self, model_size, lang):
        from faster_whisper import WhisperModel
        self.lang = lang
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8",
                                  download_root=VOICE_DIR)
    def chunk_text(self, pcm_f32):
        try:
            segs, _ = self.model.transcribe(pcm_f32, beam_size=3, language=self.lang,
                                             condition_on_previous_text=False,
                                             vad_filter=False)
            return " ".join(s.text for s in segs).strip()
        except Exception as exc:  # noqa: BLE001
            print(f"[asr] {exc}", file=sys.stderr)
            return ""

# ---------------------------------------------------------------- TTS
class Tts:
    """Fila de frases → jarvis speak (kokoro) → aplay. Frase (não fragmento):
    síntese por frase ~beat realtime, fila absorve o resto (lição do
    vídeo xbedfuqYQYA: fila de 2, sintetiza enquanto toca)."""
    def __init__(self):
        self.q = queue.Queue()
        threading.Thread(target=self._worker, daemon=True).start()
    def say(self, text):
        if text.strip():
            self.q.put(text.strip())
    def _worker(self):
        while True:
            text = self.q.get()
            try:
                out = subprocess.run(["jarvis", "speak", "--no-play", text],
                                     capture_output=True, text=True, timeout=120)
                wav = (out.stdout or "").strip().splitlines()[-1]
                if wav and wav.endswith(".wav"):
                    subprocess.run(["aplay", "-q", wav], timeout=120)
            except Exception as exc:  # noqa: BLE001
                print(f"[tts] {exc}", file=sys.stderr)

# ---------------------------------------------------------------- mic
def mic_stream(rate=SR):
    # pw-record na FONTE DEFAULT do sistema = o filtro rnnoise da casa
    # (17/10: arecord/ALSA pegava fonte morta RMS=0; rnnoise RMS=70 e
    # ainda DENOISA a entrada). "-" = raw s16 no stdout.
    return subprocess.Popen(["pw-record", "--rate", str(rate), "--channels", "1",
                             "--format", "s16", "-"],
                            stdout=subprocess.PIPE, bufsize=CHUNK_BYTES)

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8085)
    ap.add_argument("--lang", default="pt")
    ap.add_argument("--stt-model", default="small",
                    help="faster-whisper size (small=int8 cpu ~ok; tiny=+rápido)")
    args = ap.parse_args()
    base = f"http://{args.host}:{args.port}"

    try:
        http(base + "/health")
    except Exception:
        sys.exit(f"duplex-voice: server {base} fora — systemctl start llama-duplex-35b")

    print(f"duplex-voice | {base} | tick={TICK}s | stt={args.stt_model}@{args.lang}")
    print("aplicando LoRA (acordar)…", flush=True)
    lora_apply(base, True)
    print("LoRA aplicado — MODO DUPLEX. Ctrl-C = dormir.\n", flush=True)

    asr = Asr(args.stt_model, args.lang)
    tts = Tts()
    mic = mic_stream()
    history: list[tuple[str, str]] = []
    frase: list[str] = []
    quiet_ticks = 0
    running = True

    def _sair(*_):
        nonlocal running
        running = False
    signal.signal(signal.SIGINT, _sair)

    try:
        while running:
            t0 = time.monotonic()
            raw = mic.stdout.read(CHUNK_BYTES)
            heard = NOVOICE
            if len(raw) == CHUNK_BYTES:
                import numpy as np
                pcm = np.frombuffer(raw, dtype=np.int16).astype("float32") / 32768.0
                txt = asr.chunk_text(pcm)
                heard = txt if txt else NOVOICE
            said, p = tick_once(base, history, heard)
            history += [("user", heard), ("assistant", said)]
            if said == LISTEN:
                quiet_ticks += 1
            else:
                quiet_ticks = 0
                frase.append(said)
                print(f"  ouvi: {heard:<28} digo: {said}", flush=True)
                if said.rstrip().endswith((".", "!", "?")) or len(frase) >= 3:
                    tts.say(" ".join(frase)); frase = []
            # pausa natural: 2 ticks quietos com frase pendente = fecha
            if quiet_ticks >= 2 and frase:
                tts.say(" ".join(frase)); frase = []; quiet_ticks = 0
            dt = TICK - (time.monotonic() - t0)
            if dt > 0:
                time.sleep(dt)
    finally:
        print("\ndormindo (LoRA off)…", flush=True)
        try:
            lora_apply(base, False)
            print("dormindo: LoRA desligado — server segue servindo texto.")
        except Exception as exc:  # noqa: BLE001
            print(f"aviso: unapply falhou ({exc})")
        mic.terminate()

if __name__ == "__main__":
    main()
