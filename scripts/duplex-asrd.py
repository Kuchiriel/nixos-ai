#!/usr/bin/env python3
"""duplex-asrd.py — ASR v4: silero VAD (limites) + whisper.cpp GPU (texto).

(18/10 08:50) A evolução final da manhã: o VAC do whisper_streaming
carregava um whisper CPU interno (1.5-3s por segmento) só pra FECHAR
limites. Agora: FixedVADIterator (silero sozinho, o arquivo vendored)
detecta pausa em ~300ms; o segmento cortado do ring vai pro
whisper-server (:8097, CUDA, modelo quente) — 158ms medidos por
segmento. Total fala→texto: <1s.

Protocolo stdio (igual o cliente já fala):
  req: {"audio_b64": "<float32 PCM 16k>"} (chunks de 0.6s, TODOS —
       silêncio inclusive, o VAD precisa)
  resp: {"text": "...", "ms": X} quando fecha segmento; silêncio = nada
"""
import base64
import io
import json
import sys
import time
import urllib.request
import wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

import numpy as np

SR = 16000
WCPP = "http://127.0.0.1:8097/inference"

def main():
    from silero_vad_iterator import FixedVADIterator

    # silero via torch hub (cacheado em ~/.cache/torch — o VAC baixou 1×)
    import torch
    model, utils = torch.hub.load("snakers4/silero-vad", "silero_vad")
    vad = FixedVADIterator(model, threshold=0.5, min_silence_duration_ms=350,
                           speech_pad_ms=150)
    print(json.dumps({"text": "", "ms": 0, "ready": True}), flush=True)

    ring = np.zeros(0, dtype="float32")
    started = None

    def seg_to_text(seg):
        if len(seg) < SR * 0.4:
            return ""
        buf = io.BytesIO()
        w = wave.open(buf, "wb")
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(SR)
        w.writeframes((seg * 32767).astype("int16").tobytes())
        w.close()
        req = urllib.request.Request(
            WCPP, data=buf.getvalue(),
            headers={"Content-Type": "audio/wav"})
        boundary = "----JARVIS"
        # multipart manual: whisper-server espera form-data 'file'
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; "
            f"name=\"file\"; filename=\"seg.wav\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n").encode() + buf.getvalue() + \
            f"\r\n--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            WCPP, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        j = json.load(urllib.request.urlopen(req, timeout=60))
        return str(j.get("text", "")).strip()

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
        try:
            ring = np.concatenate([ring, pcm])[-SR * 20:]   # cap 20s
            ev = vad(pcm)
            if ev and started is None and ev.get("start") is not None:
                started = max(0, int(len(ring) - SR * 1.0))   # 1s de pré-roll
            if ev and ev.get("end") is not None and started is not None:
                seg = ring[int(started):int(len(ring) - SR * 0.35)]
                txt = seg_to_text(seg)
                ms = (time.monotonic() - t0) * 1000
                print(json.dumps({"text": txt, "ms": ms}), flush=True)
                ring = np.zeros(0, dtype="float32")
                started = None
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"text": "", "ms": 0, "err": str(exc)[:120]}),
                  flush=True)

if __name__ == "__main__":
    main()
