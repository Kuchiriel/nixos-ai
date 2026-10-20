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
CTX = {"v": ""}   # vocabulário da conversa → prompt do whisper-server
WCPP = "http://127.0.0.1:8097/inference"

def main():
    from silero_vad_iterator import FixedVADIterator

    # silero via torch hub (cacheado em ~/.cache/torch — o VAC baixou 1×)
    import torch
    model, utils = torch.hub.load("snakers4/silero-vad", "silero_vad")
    vad = FixedVADIterator(model, threshold=0.5, min_silence_duration_ms=400,
                           speech_pad_ms=150)
    print(json.dumps({"text": "", "ms": 0, "ready": True}), flush=True)

    ring = np.zeros(0, dtype="float32")
    started = None

    # (20/10, papers voz-stt) 4 defesas anti-alucinação:
    # 2609.04561 (gated projection): no_speech_prob+avg_logprob como
    #   gate — é o sinal que o paper usa p/ decidir projetar.
    # 2609.32560 (two-sided): deny-list de frases-alucinação (léxico
    #   Scicom HF) — SÓ contaminação inequívoca de legenda; risadas/
    #   aplausos/música são SINAIS SOCIAIS e passam (direção do dono:
    #   o agente usa) — o anti-fantasma deles é o gate estatístico.
    # 2610.08847 (CTC criterion): tokens >> duração do áudio = fakir.
    # 2608.15940 (null token): o modelo SABE quando não tem fala — os
    #   logprobs-no_speech são o sinal de abstenção que a gente jogava fora.
    HALLUC_PT = (
        "obrigado por assistir", "obrigado por assistirem",
        "inscreva-se no canal", "até o próximo vídeo",
        "som de futebol", "música de fundo",
    )

    def anti_halluc(txt, segs, dur_s):
        t = " ".join(txt.lower().replace("[", " ").replace("]", " ")
                     .split()).strip()
        # 1. deny-list: frase curta com assinatura de legenda = lixo
        if len(t.split()) <= 6 and any(h in t for h in HALLUC_PT):
            return ""
        # 2. gate estatístico: TUDO no_speech alto + logprob ruim = vazio
        if segs and all(s.get("no_speech_prob", 0) > 0.6 for s in segs) \
                and all(s.get("avg_logprob", 0) < -0.8 for s in segs):
            return ""
        # 3. tokens-vs-duração: PT falado ~2-4 pal/s; >5.5 = impossível
        if dur_s > 0.3 and len(txt.split()) > dur_s * 5.5:
            return ""
        return txt

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
        # (+ 'prompt' com o vocabulário da conversa — paper 2307.14743:
        # last confirmed words as prompt fixa o 'Já viz'→'Jarvis')
        # (+ 'response_format' verbose_json: expõe no_speech_prob/
        # avg_logprob por segmento — as defesas anti-halluc)
        body = (
            f"--{boundary}\r\nContent-Disposition: form-data; "
            f"name=\"file\"; filename=\"seg.wav\"\r\n"
            f"Content-Type: audio/wav\r\n\r\n").encode() + buf.getvalue() + b"\r\n"
        if CTX["v"]:
            body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                     f"name=\"prompt\"\r\n\r\n{CTX['v'][:200]}\r\n").encode()
        body += (f"--{boundary}\r\nContent-Disposition: form-data; "
                 f"name=\"response_format\"\r\n\r\nverbose_json\r\n").encode()
        body += f"--{boundary}--\r\n".encode()
        req = urllib.request.Request(
            WCPP, data=body,
            headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
        j = json.load(urllib.request.urlopen(req, timeout=60))
        txt = str(j.get("text", "")).strip()
        segs = j.get("segments") or []
        dur_s = float(j.get("duration") or (len(seg) / SR))
        return anti_halluc(txt, segs, dur_s)

    def reset():
        # (10:20) anti-eco (pesquisa: playback suppression + reset do
        # estado de VAD no início E no fim do TTS — o tail do eco senão
        # fecha um segmento fantasma e o modelo responde a si).
        nonlocal ring, started, vad
        ring = np.zeros(0, dtype="float32")
        started = None
        vad = FixedVADIterator(model, threshold=0.5,
                               min_silence_duration_ms=400,
                               speech_pad_ms=150)

    # (19:30) SPEAKER ENGINE v2: multi-voz (papers: VAD→embed→cluster)
    # profiles = {nome: embedding}; a cada segmento identifica a voz;
    # clusters de embeddings recentes = contagem de pessoas falando.
    SPK_PROFILES = {}
    try:
        _cfg = json.loads(Path("/tmp/jarvis-spk-profiles.json").read_text())
        SPK_PROFILES = {k: np.array(v) for k, v in _cfg.items()}
    except Exception:
        pass
    SPK_RECENT = []  # [(embedding, ts)] últimos 60s — clustering
    SPK_COUNTER = {"voices": 0, "last_id": "?"}
    print(f"[asrd] speaker: {len(SPK_PROFILES)} perfis "
          f"({'ATIVO' if SPK_PROFILES else 'desligado (todos)'})",
          file=sys.stderr, flush=True)

    def _embed(pcm_f32):
        try:
            import librosa
            m = librosa.feature.mfcc(y=pcm_f32, sr=SR, n_mfcc=13,
                                      n_fft=512, hop_length=160)
            return np.concatenate([m.mean(axis=1), m.std(axis=1)])
        except Exception:
            return None

    def _cos(a, b):
        return float(np.dot(a, b) /
                     (np.linalg.norm(a) * np.linalg.norm(b) + 1e-9))

    def _identify(pcm_f32):
        """Retorna (nome, confiança) da melhor voz conhecida ou
        ('unknown', cos_max). Também alimenta o contador de vozes."""
        nonlocal SPK_RECENT
        e = _embed(pcm_f32)
        if e is None:
            return ("?", 0.0)
        # identifica contra perfis conhecidos
        best, best_cos = "?", 0.0
        for nome, prof in SPK_PROFILES.items():
            c = _cos(e, prof)
            if c > best_cos:
                best, best_cos = nome, c
        if best_cos < 0.75:
            best = "unknown"
        # clustering: conta vozes únicas nos últimos 60s
        now = time.time()
        SPK_RECENT = [(r_e, ts) for r_e, ts in SPK_RECENT if now - ts < 60]
        SPK_RECENT.append((e, now))
        n_voices = 1
        centroids = [SPK_RECENT[0][0].copy()]
        for r_e, _ in SPK_RECENT[1:]:
            if max(_cos(r_e, c) for c in centroids) < 0.82:
                centroids.append(r_e.copy())
                n_voices += 1
        SPK_COUNTER["voices"] = n_voices
        SPK_COUNTER["last_id"] = best
        return (best, best_cos)

    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
            if req.get("reset"):
                reset()
                print(json.dumps({"text": "", "ms": 0, "reset": True}),
                      flush=True)
                continue
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
                # (19:30) identificar a voz e anexar ao resultado
                spk_id, spk_cos = _identify(seg)
                txt = ''
                txt = seg_to_text(seg)
                ms = (time.monotonic() - t0) * 1000
                print(json.dumps({"text": txt, "ms": ms, "spk": spk_id,
                       "spk_cos": round(spk_cos, 2),
                       "voices": SPK_COUNTER["voices"]}), flush=True)
                ring = np.zeros(0, dtype="float32")
                started = None
        except Exception as exc:  # noqa: BLE001
            print(json.dumps({"text": "", "ms": 0, "err": str(exc)[:120]}),
                  flush=True)

if __name__ == "__main__":
    main()
