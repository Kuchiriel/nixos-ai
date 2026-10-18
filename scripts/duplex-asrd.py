#!/usr/bin/env python3
"""duplex-asrd.py — daemon ASR STREAMING do duplex (v2, 18/10 ~06:40).

ANTES: janelas fixas 1.2s + transcribe batch = cortava palavras nas
bordas + 2-7s de latência + brigava por CPU com o LLM.
AGORA: Whisper-Streaming (ufal, LocalAgreement-2 + VAC, arXiv 2307.14743)
— chunks de 0.6s alimentam um buffer CONTÍNUO; o process_iter publica
prefixos estáveis incrementalmente; o VAC detecta fim de segmento.
Sem corte de palavras, latência ~0.6-1.5s, contexto que cresce.

Protocolo stdio (igual ao cliente duplex-voice.py já fala):
  req: {"audio_b64": "<float32 PCM 16k>"} (um chunk de 0.6s por linha)
  resp: {"text": "<texto novo estável>", "ms": X, "final": bool}
Voz karaok venv (ctranslate2 30× mais rápido que o do env jarvis).
"""
import base64
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np

SR = 16000

def main():
    from whisper_streaming import FasterWhisperASR, VACOnlineASRProcessor

    asr = FasterWhisperASR(modelsize="small", lan="pt",
                           cache_dir="/home/nixos/.local/share/jarvis/voice",
                           model_dir=None)
    online = VACOnlineASRProcessor(0.6, asr, tokenizer=None,
                                   logfile=sys.stderr,
                                   buffer_trimming=("segment", 15))
    print(json.dumps({"text": "", "ms": 0, "final": False, "ready": True}),
          flush=True)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            b64 = req.get("audio_b64")
            if not b64:
                continue
            pcm = np.frombuffer(base64.b64decode(b64), dtype="<f4")
        except Exception:
            continue
        t0 = time.monotonic()
        txt = ""
        try:
            online.insert_audio_chunk(pcm)
            out = online.process_iter()
            # (medido 18/10) VACOnlineASRProcessor.process_iter →
            # (beg_ts, end_ts, texto_novo) quando fecha um segmento,
            # (None, None, '') entre segmentos. O VAC fecha NA PAUSA do
            # usuário = o gatilho de resposta nasce pronto.
            if isinstance(out, tuple) and len(out) == 3 and out[2]:
                txt = str(out[2]).strip()
        except Exception as exc:  # noqa: BLE101
            print(json.dumps({"text": "", "ms": 0, "final": False,
                              "err": str(exc)[:120]}), flush=True)
            continue
        print(json.dumps({"text": txt, "ms": (time.monotonic() - t0) * 1000,
                          "final": False}), flush=True)

if __name__ == "__main__":
    main()
