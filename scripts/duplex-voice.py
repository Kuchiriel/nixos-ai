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
from pathlib import Path
from datetime import datetime

import numpy as np

TICK = 0.6
LISTEN, NOVOICE = "<listen>", "<no voice>"
LISTEN_P = 0.3
SYSTEM = ("You are a voice assistant in a live phone call; both sides can talk at the same time. Every "
          f"{TICK:g} seconds you get what the microphone heard in that moment, as a streaming transcript fragment, or "
          f"{NOVOICE}. You reply with up to three new words to say next, or {LISTEN} to add nothing.")
SR = 16000
# Digital mic (17/10): Stereo mic = morto (rms 0); Digital = vivo
# (sustained). Nome estável do node (id muda por boot).
MIC_SOURCE = "alsa_input.pci-0000_00_1f.3-platform-skl_hda_dsp_generic.HiFi__Mic1__source"
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
    """ASR EM THREAD PRÓPRIA (17/10 v3): whisper 2s/chunk bloqueava o tick
    (loop 3.6s/tick). Agora o loop NUNCA espera: manda o ÚLTIMO texto pronto,
    backlog cap 2 (se whisper atrasa, o tick segue; fragmentos tardios chegam
    no próximo tick — duplex tolera)."""
    def __init__(self, model_size, lang):
        from faster_whisper import WhisperModel
        voice_dir = os.environ.get("JARVIS_VOICE_DIR",
                                   os.path.expanduser("~/.local/share/jarvis/voice"))
        self.lang = lang
        t0 = time.monotonic()
        # cpu_threads=3 (17/10): sem cap o CTranslate2 rouba TODOS os
        # cores do llama-server → asr 2.5-10s sob contenção. 3 threads =
        # llama mantém seus P-cores, asr ~1.2s estável.
        self.model = WhisperModel(model_size, device="cpu", compute_type="int8",
                                  download_root=voice_dir, cpu_threads=3)
        log(f"[{ts()}] asr: {model_size} carregado em {time.monotonic()-t0:.1f}s")
        self.chunks = queue.Queue(maxsize=2)
        self.results = queue.Queue(maxsize=4)
        self.last_ms = 0.0
        threading.Thread(target=self._worker, daemon=True).start()
    def _worker(self):
        while True:
            pcm = self.chunks.get()
            t0 = time.monotonic()
            try:
                # (17/10, anime JP do dono) ANTI-ALUCINAÇÃO: whisper forced-pt
                # sobre japonês/música inventa "Legendas pela comunidade" (e o
                # 35B RESPONDEU à alucinação). Antídotos da casa (transcribe()
                # calibrado): VAD Silero + descarte por avg_logprob < -0.60
                # + no_speech_prob. VAD params ajustados à janela 1.2s.
                segs, _ = self.model.transcribe(
                    pcm, beam_size=1, language=self.lang,
                    condition_on_previous_text=False,
                    vad_filter=True,
                    vad_parameters=dict(threshold=0.45, min_speech_duration_ms=200,
                                         min_silence_duration_ms=300,
                                         speech_pad_ms=160))
                good, lp_sum, ch_sum = [], 0.0, 0
                for seg in segs:
                    lp = float(getattr(seg, "avg_logprob", -1.0))
                    ns = float(getattr(seg, "no_speech_prob", 1.0))
                    if lp < -0.60 or ns > 0.6:
                        continue
                    good.append(seg.text)
                    lp_sum += lp * len(seg.text); ch_sum += len(seg.text)
                if good and ch_sum and lp_sum / ch_sum < -0.60:
                    good = []
                txt = " ".join(good).strip()
                self.last_ms = (time.monotonic() - t0) * 1000
                try:
                    self.results.put_nowait(txt)
                except queue.Full:
                    try: self.results.get_nowait()
                    except queue.Empty: pass
                    self.results.put_nowait(txt)
            except Exception as exc:  # noqa: BLE001
                log(f"[{ts()}] asr ERRO: {exc}")
    def feed(self, pcm_f32):
        try:
            self.chunks.put_nowait(pcm_f32)
        except queue.Full:
            pass  # backlog cap: whisper lento = chunk descartado, tick segue
    def take(self):
        try:
            return self.results.get_nowait()
        except queue.Empty:
            return None

# ---------------------------------------------------------------- TTS (worker, subprocess comprovado)
class Tts:
    """Frase → jarvis speak --no-play (CLI, env jarvis-voice: edge-antonio
    default / kokoro) → aplay. In-process speak() exigiria o env jarvis,
    que não expõe faster_whisper no site-packages (A/B de envs 17/10) —
    o cliente roda no venv karaok; subprocess = comprovado (voice-selftest).
    Mede synth+play por frase (o gargalo de latência conhecido)."""
    def __init__(self):
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
                out = subprocess.run(["jarvis", "speak", "--no-play", text],
                                     capture_output=True, text=True, timeout=180)
                wav = (out.stdout or "").strip().splitlines()[-1]
                if wav.endswith(".wav"):
                    subprocess.run(["aplay", "-q", wav], timeout=180)
                self.last_ms = (time.monotonic() - t0) * 1000
            except Exception as exc:  # noqa: BLE001
                log(f"[{ts()}] tts ERRO: {exc}")

# ---------------------------------------------------------------- mic
def mic_stream():
    # pw-record EXPLÍCITO na rnnoise (17/10: a default do pw-record é
    # morta — rms=0; a rnnoise rms=70 ambiente/206 falando, e DENOISA).
    # Pelo NOME (id 38 muda a cada boot).
    return subprocess.Popen(["pw-record", "--rate", str(SR), "--channels", "1",
                             "--format", "s16", "--target", MIC_SOURCE, "-"],
                            stdout=subprocess.PIPE, bufsize=CHUNK_BYTES)

# ---------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8085)
    ap.add_argument("--lang", default="pt")
    ap.add_argument("--stt-model", default="small")
    ap.add_argument("--rms", type=int, default=700,
                    help="gate de silêncio (ambiente rnnoise~70; fala 300+)")
    args = ap.parse_args()
    base = f"http://{args.host}:{args.port}"

    try:
        http(base + "/health")
    except Exception:
        sys.exit(f"duplex-voice: server {base} fora — systemctl start llama-duplex-35b")

    # EXCLUSIVIDADE (17/10): o wakeword daemon falso-positiva em diálogo
    # alto de anime (baseline 205/gate 310 vs bursts 700-1441) e dispara
    # o fluxo de comando DELE enquanto o duplex escuta — os dois brigam
    # pelo microfone e pela voz. Duplex ON = daemon pausado; dormir = volta.
    # (Recalibração do wakeword p/ o mic novo = pendência 4 do doc.)
    Path("/tmp/jarvis-duplex-mode.flag").touch()   # heal respeita (17/10)
    subprocess.run(["systemctl", "--user", "stop", "jarvis-wakeword.service"],
                   capture_output=True)
    log(f"[{ts()}] wakeword daemon pausado (flag pro heal plantada) — volta no dormir")
    # EXCLUSIVIDADE (17/10): o wakeword daemon falso-positiva em diálogo
    # alto de anime (baseline 205/gate 310 vs bursts 700-1441) e dispara
    # o fluxo de comando DELE enquanto o duplex escuta — os dois brigam
    # pelo microfone e pela voz. Duplex ON = daemon pausado; dormir = volta.
    # (Recalibração do wakeword p/ o mic novo = pendência 4 do doc.)
    Path("/tmp/jarvis-duplex-mode.flag").touch()   # heal respeita (17/10)
    subprocess.run(["systemctl", "--user", "stop", "jarvis-wakeword.service"],
                   capture_output=True)
    log(f"[{ts()}] wakeword daemon pausado (flag pro heal plantada) — volta no dormir")
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
    prev_pcm, prev_rms = None, 0
    zeros = 0
    zeros = 0
    try:
        while running:
            t0 = time.monotonic()
            raw = mic.stdout.read(CHUNK_BYTES)
            heard, asr_ms, rms = NOVOICE, 0.0, 0
            if len(raw) == CHUNK_BYTES:
                pcm16 = np.frombuffer(raw, dtype=np.int16)
                rms = int(np.sqrt((pcm16.astype(np.float64) ** 2).mean()))
                # JANELA 1.2s (v4): pares de chunks (0.6s cortava palavras
                # no meio — bench 17/10). Transcreve o par quando QUALQUER
                # metade passa o gate; cobertura sem buracos, sem overlap.
                if prev_pcm is not None:
                    if max(prev_rms, rms) >= args.rms:
                        asr.feed(np.concatenate([prev_pcm, pcm16]).astype("float32") / 32768.0)
                    prev_pcm, prev_rms = None, 0
                else:
                    prev_pcm, prev_rms = pcm16, rms
                txt = asr.take()
                asr_ms = asr.last_ms
                if txt is not None and txt:
                    heard = txt
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

            # WATCHDOG (17/10): rms=0 por ~5s = stream morto (restart do
            # wakeword derrubou a captura uma vez) → reabre o pw-record.
            if rms == 0:
                zeros += 1
                if zeros >= 8:
                    log(f"[{ts()}] mic morto ({zeros} ticks rms=0) — reabrindo captura")
                    mic.terminate()
                    mic = mic_stream()
                    zeros = 0
            else:
                zeros = 0
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
        subprocess.run(["systemctl", "--user", "start", "jarvis-wakeword.service"],
                       capture_output=True)
        Path("/tmp/jarvis-duplex-mode.flag").unlink(missing_ok=True)
        log(f"[{ts()}] wakeword daemon de volta (flag removida)")

def selfless(f):
    return " ".join(f)

if __name__ == "__main__":
    main()
