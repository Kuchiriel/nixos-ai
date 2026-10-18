#!/usr/bin/env python3
"""duplex-asrd.py — daemon ASR do modo duplex (18/10, 03:15).

Roda no VENV DO KARAAK (ctranslate2 30× mais rápido que o do env jarvis)
como SUBPROCESSO stdio (Popen — o mesmo contexto standalone onde tudo
funciona; o multiprocessing.spawn envenenava o VAD do faster-whisper:
0 timestamps → sem fala → alucinação → filtros derrubavam → surdez).

Protocolo (JSON lines no stdin, resposta JSON line no stdout):
  request : {"audio_b64": "<float32 PCM little-endian base64>"}
  resposta: {"text": "...", "ms": 123.4, "lp": -0.42, "ns": 0.12}
  "audio_b64": "" == null (sem áudio) ou o JSON vazio = ignore a linha
Filtros anti-alucinação AQUI (avg_logprob/no_speech), VAD ON (neste
contexto ele funciona — comprovado offline dezenas de vezes).
"""
import base64
import json
import sys
import time

import numpy as np
from faster_whisper import WhisperModel

SR = 16000
VAD_PARAMS = dict(threshold=0.45, min_speech_duration_ms=200,
                  min_silence_duration_ms=300, speech_pad_ms=160)

def main():
    model = WhisperModel("small", device="cpu", compute_type="int8",
                         download_root="/home/nixos/.local/share/jarvis/voice",
                         cpu_threads=3)
    # warmup real (fala sintética VAD-passável + generator consumido)
    t = np.arange(SR, dtype="float32") / SR
    am = 0.6 * (1 + np.sin(2 * np.pi * 4.0 * t))
    carrier = np.sin(2 * np.pi * 220.0 * t)
    for _ in model.transcribe(am * carrier, beam_size=1, language="pt",
                              vad_filter=True, vad_parameters=VAD_PARAMS):
        pass
    print(json.dumps({"text": "", "ms": 0, "lp": 0, "ns": 0, "ready": True}),
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
        txt, lp, ns = "", 0.0, 1.0
        try:
            segs, _ = model.transcribe(pcm, beam_size=1, language="pt",
                                       condition_on_previous_text=False,
                                       vad_filter=True,
                                       vad_parameters=VAD_PARAMS)
            good, lp_sum, ch_sum = [], 0.0, 0
            raw_txt, raw_lp, raw_ns = "", 0.0, 1.0
            for seg in segs:
                slp = float(getattr(seg, "avg_logprob", -1.0))
                sns = float(getattr(seg, "no_speech_prob", 1.0))
                stx = (seg.text or "").strip()
                if stx and not raw_txt:
                    raw_txt, raw_lp, raw_ns = stx, slp, sns
                # (05:15) NS é O guardião (dados da noite: fala real ns
                # 0.37-0.45; alucinação 'Legendas' ns 0.878). LP em beam1
                # int8 com áudio de alto-falante anda -1.0 a -1.5 SEM ser
                # alucinação ('como uma piada...' lp=-1.375 ns=0.37) —
                # threshold -0.60 matava fala real. LP vira só sanity.
                if slp < -2.5 or sns > 0.7:
                    continue
                good.append(seg.text)
                lp_sum += slp * len(seg.text); ch_sum += len(seg.text)
            if good and ch_sum and lp_sum / ch_sum < -2.5:
                good = []
            txt = " ".join(good).strip()
            if not txt and raw_txt:
                # telemetria: o filtro derrubou algo — o log do cliente
                # mostra o quê (raw/lp/ns) sem acordar ninguém.
                print(json.dumps({"text": "", "ms": (time.monotonic()-t0)*1000,
                                  "raw": raw_txt, "lp": round(raw_lp, 3),
                                  "ns": round(raw_ns, 3), "filtered": True}),
                      flush=True)
                continue
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"text": "", "ms": 0, "lp": 0, "ns": 1,
                              "err": str(exc)[:120]}), flush=True)
            continue
        print(json.dumps({"text": txt, "ms": (time.monotonic() - t0) * 1000,
                          "lp": lp, "ns": ns}), flush=True)

if __name__ == "__main__":
    main()
