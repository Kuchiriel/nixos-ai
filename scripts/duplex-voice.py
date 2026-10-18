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
def _asr_child(model_size, lang, voice_dir, in_q, out_q):
    """PROCESSO próprio (18/10 ~02h, GIL): o transcribe() do faster-whisper
    é GENERATOR — a inferência roda DENTRO do `for seg`, e no mesmo
    processo o GIL do tick-loop (urllib/json) a esmagava: 71ms standalone
    vs 7-11s in-client. Processo separado = zero disputa. Warmup com
    SINAL TIPO FALA (senoide AM): o warmup de silêncio era rejeitado pelo
    VAD em 0.1s e NUNCA exercitava o encoder (por isso a 1ª fala = 7s+)."""
    import numpy as np
    from faster_whisper import WhisperModel
    model = WhisperModel(model_size, device="cpu", compute_type="int8",
                         download_root=voice_dir, cpu_threads=3)
    # (02:05) warmup com FALA REAL: senoide AM era rejeitada pelo VAD e o
    # encoder nunca rodava → a 1ª fala real custava 11.5s (depois 39ms!).
    # duplex-warmup.wav = 1.2s de fala PT (asset do repo).
    import wave as _wave
    _wp = Path(__file__).with_name("duplex-warmup.wav")
    if _wp.exists():
        _w = _wave.open(str(_wp))
        _pcm = np.frombuffer(_w.readframes(_w.getnframes()), dtype="int16").astype("float32") / 32768.0
        # (02:10) CONSUMIR o generator: transcribe() é lazy — sem o for,
        # o warmup preprocessa e volta; a inferência real (encoder+decoder,
        # ~11s na 1ª vez) estourava na primeira fala do dono.
        for _seg in model.transcribe(_pcm, beam_size=1, language=lang,
                                     vad_filter=True, vad_parameters=VAD_PARAMS):
            pass
        print("[asr-child] pronto (warmup com FALA REAL paga)", flush=True)
    else:
        t = np.arange(SR, dtype="float32") / SR
        am = (0.6 * (1 + np.sin(2 * np.pi * 4.0 * t))).astype("float32")
        carrier = np.sin(2 * np.pi * 220.0 * t).astype("float32")
        for _seg in model.transcribe((am * carrier).astype("float32"), beam_size=1,
                                      language=lang, vad_filter=True,
                                      vad_parameters=VAD_PARAMS):
            pass
        print("[asr-child] pronto (AVISO: warmup.wav ausente, senoide)", flush=True)
    while True:
        pcm = in_q.get()
        if pcm is None:
            return
        t0 = time.monotonic()
        try:
            segs, _ = model.transcribe(pcm, beam_size=1, language=lang,
                                        condition_on_previous_text=False,
                                        vad_filter=True, vad_parameters=VAD_PARAMS)
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
            ms = (time.monotonic() - t0) * 1000
            # (03:10) DEBUG: para de adivinhar — o par que o child RECEBE
            # vai pro disco quando vaza vazio. Comparar byte-a-byte com o
            # offline comprovado encerra o mistério.
            if not txt and float(np.sqrt((np.asarray(pcm) ** 2).mean())) > 0.02:
                np.save("/tmp/asr-debug-pair.npy", np.asarray(pcm, dtype="float32"))
            out_q.put((txt, ms))
        except Exception as exc:  # noqa: BLE001
            out_q.put(("", (time.monotonic() - t0) * 1000))
            print(f"[asr-child] ERRO: {exc}", flush=True)

class Asr:
    """Whisper em PROCESSO filho (GIL isolado) + anti-alucinação."""
    def __init__(self, model_size, lang):
        import multiprocessing as mp
        voice_dir = os.environ.get("JARVIS_VOICE_DIR",
                                   os.path.expanduser("~/.local/share/jarvis/voice"))
        # (02:25) SPAWN, não fork: o ctranslate2 herdado por fork de um
        # processo multithread fica patológico (43s vs 71ms standalone —
        # threadpool/OpenMP não sobrevive ao fork). Spawn = interpretador
        # limpo; boot +lento, conversa rápida.
        ctx = mp.get_context("spawn")
        self.in_q = ctx.Queue(maxsize=2)
        self.out_q = ctx.Queue(maxsize=4)
        self.last_ms = 0.0
        t0 = time.monotonic()
        self.proc = ctx.Process(target=_asr_child,
                                args=(model_size, lang, voice_dir,
                                      self.in_q, self.out_q), daemon=True)
        self.proc.start()
        log(f"[{ts()}] asr-child pid={self.proc.pid} subindo (model+warmup)…")
    def feed(self, pcm_f32):
        try:
            self.in_q.put_nowait(pcm_f32)
        except Exception:
            pass
    def take(self):
        try:
            txt, ms = self.out_q.get_nowait()
            self.last_ms = ms
            return txt
        except queue.Empty:
            return None
    def close(self):
        try:
            self.in_q.put_nowait(None)
            self.proc.join(timeout=2)
            self.proc.terminate()
        except Exception:
            pass

# ---------------------------------------------------------------- TTS
class Tts:
    """Cliente do daemon duplex-ttsd (18/10, 02:45): o kokoro só existe
    no env jarvis, mas o ctranslate2 DELE é 30× mais lento — então o ASR
    roda neste processo (karaok venv) e o TTS num daemon separado no env
    jarvis, kokoro carregado UMA vez. FIFO JSON; o daemon morre com o
    cliente (__exit)."""
    FIFO = "/tmp/jarvis-duplex-tts.fifo"
    def __init__(self):
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

    asr = Asr(args.stt_model, args.lang)
    tts = Tts()
    mic_q = queue.Queue(maxsize=3)
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
            # (03:00) CONSOME UM CHUNK POR TICK, bloqueante — o reader
            # thread é quem faz o flow-control (fila 3, drop-oldest no
            # overflow). O drain-último que eu inventei DESCARTAVA chunks
            # de fala: janela de 2.4s virava 1.2s furada (metade da
            # palavra) → VAD rejeitava → resultados vazios a noite toda.
            raw = mic_q.get()
            if raw is None:   # stream morreu → reabre
                log(f"[{ts()}] mic stream morta — reabrindo")
                mic.terminate()
                mic = mic_stream()
                threading.Thread(target=mic_reader, args=(mic, mic_q),
                                  daemon=True).start()
                raw = mic_q.get()

            heard, rms = NOVOICE, 0
            if raw is not None:
                pcm16 = np.frombuffer(raw, dtype=np.int16)
                rms = int(np.sqrt((pcm16.astype(np.float64) ** 2).mean()))
                zeros = zeros + 1 if rms == 0 else 0
                # JANELA 1.2s: pares de chunks (0.6s cortava palavras).
                if prev_pcm is not None:
                    if max(prev_rms, rms) >= args.rms:
                        asr.feed(np.concatenate([prev_pcm, pcm16]).astype("float32") / 32768.0)
                    prev_pcm, prev_rms = None, 0
                else:
                    prev_pcm, prev_rms = pcm16, rms
                txt = asr.take()
                if txt:
                    heard = txt

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
