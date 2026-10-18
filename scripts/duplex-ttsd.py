#!/usr/bin/env python3
"""duplex-ttsd.py — daemon TTS do modo duplex (18/10, 02:45).

RODA NO ENV JARVIS (o kokoro vive lá; o ctranslate2 DELE é 30× mais lento
que o do karaok — por isso o ASR NÃO roda mais neste env). Carrega o
pipeline kokoro UMA vez e atende por FIFO: uma linha JSON
  {"text": "..."}
por request; responde "ok <ms>" no mesmo FIFO quando termina de tocar.
O cliente duplex (duplex-voice.py) é quem sobe e mata este daemon.

USO (o cliente faz sozinho; manual p/ debug):
  duplex-voice-run.sh --ttsd          # só o daemon
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path

FIFO_REQ = "/tmp/jarvis-duplex-tts.fifo"

def main():
    from jarvis.core.voice import speak

    for p in (FIFO_REQ,):
        if not Path(p).exists():
            os.mkfifo(p)
    print("[ttsd] kokoro subindo (1ª carga paga aqui, não por frase)…",
          flush=True)
    # warmup de verdade: speak() com play=False carrega pipeline + caches.
    t0 = time.monotonic()
    out = speak("quente", play=False, base="kokoro")
    print(f"[ttsd] kokoro quente em {time.monotonic()-t0:.1f}s ({str(out)[:40]})",
          flush=True)

    while True:
        with open(FIFO_REQ) as f:      # bloqueia até 1ª writer abrir
            for line in f:             # lê até o writer fechar
                line = line.strip()
                if not line:
                    continue
                try:
                    req = json.loads(line)
                    text = req.get("text", "")
                except Exception:
                    continue
                if text == "__exit__":
                    print("[ttsd] exit", flush=True)
                    return
                t0 = time.monotonic()
                Path("/tmp/jarvis-tts-playing.lock").touch()
                try:
                    out = speak(text, play=True, base="kokoro")
                    print(f"[ttsd] {time.monotonic()-t0:.1f}s: {text[:44]!r}",
                          flush=True)
                except Exception as exc:  # noqa: BLE001
                    print(f"[ttsd] ERRO: {exc}", flush=True)
                finally:
                    Path("/tmp/jarvis-tts-playing.lock").unlink(missing_ok=True)

if __name__ == "__main__":
    main()
