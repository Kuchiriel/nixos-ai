#!/usr/bin/env python3
"""voice-pipeline-probe.py — mede o pipeline de voz da CASA nos gatilhos.

POR QUE (09/11, coord-naming): o trigger bench (scripts/duplex-eval.py
--trigger-bench) faz POST /inference direto no whisper-server. Ele NUNCA
passa pelo VAD, nem pela segmentacao, nem pelo gate anti_halluc do
duplex-asrd. O numero do bench (0,925) e' "o que o whisper faz com o clip
inteiro", nao "o que a casa responderia". Este probe mede a cadeia real:

    chunk do mic -> VAD (silero, threshold 0.5 fixo) -> segmento
    -> whisper-server -> anti_halluc (v6) -> texto que a casa entregaria

Ele fala o mesmo protocolo do duplex-voice (JSON lines em stdio), alimenta o
audio em TEMPO REAL (o VAD tem regra de fechamento por relogio: 0,70 s sem
voz fecha o segmento) e poe silencio digital no fim para forcar o
fechamento de um segmento que nao teve pausa.

O probe tem um CONTROLE POSITIVO: sem ele, "nenhum texto" pode ser probe
quebrado. O controle sao wavs reais de fala (logs/audio) e o resultado
esperado e texto nao vazio.

USO
  python3 scripts/voice-pipeline-probe.py --samples 10 --max-seconds 8
  python3 scripts/voice-pipeline-probe.py --categories silence --samples 30
  python3 scripts/voice-pipeline-probe.py --no-control

EXEMPLO DE SAIDA
  silence: 0/10 clipes produziram texto | controle (fala real): 3/3
"""
import argparse
import base64
import json
import os
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
import asrd_env  # noqa: E402

SR = 16000
CHUNK = int(SR * 0.25)          # o mic entrega 0,25-0,6 s por chunk
ASRD = Path(__file__).with_name("duplex-asrd.py")
DEFAULT_PYTHON = "/home/nixos/projects/karaok/.venv/bin/python3"
REPO = Path(__file__).resolve().parents[1]
CATEGORIES = ("silence", "nonspeech", "music", "reduplication")


class Asrd:
    """Cliente do duplex-asrd.py pelo mesmo protocolo do duplex-voice."""

    def __init__(self, python: str, taskset: str = ""):
        cmd = (["taskset", "-c", taskset] if taskset else []) + [python, str(ASRD)]
        self.proc = subprocess.Popen(
            cmd, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE, text=True, bufsize=1,
            env=asrd_env.asrd_env())
        self.lines = queue.Queue()
        self.stderr = []
        threading.Thread(target=self._reader, daemon=True).start()
        threading.Thread(target=self._errreader, daemon=True).start()
        # linha de readiness
        deadline = time.time() + 180
        ready = None
        while time.time() < deadline:
            try:
                obj = json.loads(self.lines.get(timeout=5))
            except queue.Empty:
                continue
            ready = obj
            break
        if not ready or not ready.get("ready"):
            err = "\n".join(self.stderr[-5:])
            raise SystemExit(
                f"ASRD nao ficou pronto: {ready} | stderr: {err}")

    def _reader(self):
        for line in self.proc.stdout:
            line = line.strip()
            if line:
                self.lines.put(line)

    def _errreader(self):
        for line in self.proc.stderr:
            self.stderr.append(line.rstrip())

    def send(self, obj: dict):
        self.proc.stdin.write(json.dumps(obj) + "\n")
        self.proc.stdin.flush()

    def feed(self, pcm) -> None:
        self.send({"audio_b64": base64.b64encode(
            np.asarray(pcm, dtype="<f4").tobytes()).decode()})

    def drain(self, wait: float = 0.0) -> list:
        """Linhas do ASRD que chegarem dentro de `wait` segundos."""
        out = []
        deadline = time.time() + wait
        while True:
            timeout = max(0.0, deadline - time.time())
            try:
                out.append(json.loads(self.lines.get(timeout=timeout)))
            except queue.Empty:
                break
        return out

    def close(self):
        try:
            self.proc.stdin.close()
        except Exception:
            pass
        try:
            self.proc.wait(timeout=10)
        except Exception:
            self.proc.kill()


def _load_clip(raw: bytes):
    """FLAC/WAV bytes -> float32 mono 16 kHz."""
    import io

    import soundfile as sf
    data, sr = sf.read(io.BytesIO(raw), dtype="float32")
    if getattr(data, "ndim", 1) > 1:
        data = data.mean(axis=1)
    if sr != SR:
        import math
        n = int(len(data) * SR / sr)
        idx = np.linspace(0, len(data) - 1, n, dtype=np.float64)
        data = np.interp(idx, np.arange(len(data)), data).astype("float32")
    return data


def _feed_clip(asrd: Asrd, pcm, speed: float, silence_s: float) -> list:
    """Alimenta o audio em tempo real e devolve as linhas do ASRD."""
    asrd.send({"reset": True})
    asrd.drain(0.3)
    lines = []
    total = len(pcm)
    for off in range(0, total, CHUNK):
        block = pcm[off:off + CHUNK]
        asrd.feed(block)
        if speed > 0:
            time.sleep(len(block) / SR / speed)
        lines += asrd.drain(0.02)
    # silencio digital no fim: fecha o segmento que nao teve pausa
    zeros = np.zeros(int(SR * silence_s), dtype="float32")
    for off in range(0, len(zeros), CHUNK):
        asrd.feed(zeros[off:off + CHUNK])
        if speed > 0:
            time.sleep(CHUNK / SR / speed)
        lines += asrd.drain(0.02)
    lines += asrd.drain(0.8)
    return lines


def _texts(lines) -> list:
    out = []
    for obj in lines:
        t = (obj.get("text") or "").strip()
        if t and any(c.isalnum() for c in t):
            out.append(t)
    return out


def _raw_whisper_file(path) -> dict:
    """POST de um WAV (o segmento que o ASRD gravou) no whisper-server.

    Serve para provar ONDE o audio morreu: se o segmento cru tem texto e a
    saida da casa veio vazia, quem matou foi o gate anti_halluc; se o
    segmento cru tambem vem vazio, o whisper nao inventou nada naquele
    segmento.
    """
    import urllib.request
    import wave

    p = Path(path)
    if not p.is_file():
        return {"error": "wav do segmento sumiu"}
    with p.open("rb") as fh:
        wav = fh.read()
    boundary = "----PROBESEG"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; "
        f"name=\"file\"; filename=\"seg.wav\"\r\n"
        f"Content-Type: audio/wav\r\n\r\n").encode() + wav + b"\r\n"
    body += (f"--{boundary}\r\nContent-Disposition: form-data; "
             f"name=\"response_format\"\r\n\r\nverbose_json\r\n").encode()
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        "http://127.0.0.1:8097/inference", data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        j = json.load(urllib.request.urlopen(req, timeout=60))
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:120]}
    segs = j.get("segments") or []
    ns = max([float(s.get("no_speech_prob", 0.0) or 0.0) for s in segs] or [0.0])
    lp = min([float(s.get("avg_logprob", 0.0) or 0.0) for s in segs] or [0.0])
    return {"text": str(j.get("text", "")).strip(), "no_speech_prob": ns,
            "avg_logprob": lp}


def _segments_closed(lines) -> int:
    """Quantos segmentos o ASRD fechou (linha com 'text').

    Distingue as tres situacoes, que o numero sozinho nao mostra:
      - nenhuma linha: o VAD nunca abriu segmento (o audio nao pareceu fala);
      - linha com texto vazio: o segmento foi cortado e o gate matou;
      - linha com texto: a alucinacao atravessou a cadeia inteira.
    """
    return sum(1 for obj in lines if "text" in obj)


def _raw_whisper(pcm, url: str = "http://127.0.0.1:8097/inference") -> dict:
    """O MESMO audio, janela por janela, direto no whisper-server.

    E' o caminho do trigger bench (POST /inference): serve de controle
    pareado — o que o whisper faz com o clip inteiro, contra o que a casa
    faz com o mesmo audio. Sem isso nao da' para dizer o que a cadeia
    (VAD + segmentacao + gate) acrescenta.
    """
    import io
    import urllib.request
    import wave

    buf = io.BytesIO()
    w = wave.open(buf, "wb")
    w.setnchannels(1)
    w.setsampwidth(2)
    w.setframerate(SR)
    w.writeframes((np.clip(pcm, -1, 1) * 32767).astype("<i2").tobytes())
    w.close()
    boundary = "----PROBE"
    body = (
        f"--{boundary}\r\nContent-Disposition: form-data; "
        f"name=\"file\"; filename=\"clip.wav\"\r\n"
        f"Content-Type: audio/wav\r\n\r\n").encode() + buf.getvalue() + b"\r\n"
    body += (f"--{boundary}\r\nContent-Disposition: form-data; "
             f"name=\"response_format\"\r\n\r\nverbose_json\r\n").encode()
    body += f"--{boundary}--\r\n".encode()
    req = urllib.request.Request(
        url, data=body,
        headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        j = json.load(urllib.request.urlopen(req, timeout=60))
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)[:120]}
    segs = j.get("segments") or []
    ns = max([float(s.get("no_speech_prob", 0.0) or 0.0) for s in segs] or [0.0])
    lp = min([float(s.get("avg_logprob", 0.0) or 0.0) for s in segs] or [0.0])
    return {"text": str(j.get("text", "")).strip(), "no_speech_prob": ns,
            "avg_logprob": lp, "duration": j.get("duration")}


def _control_wavs(limit: int) -> list:
    """Wavs de fala real (logs/audio) para provar que o probe ve texto."""
    d = REPO / "logs" / "audio"
    if not d.is_dir():
        return []
    wavs = sorted(d.rglob("*.wav"), key=lambda p: p.stat().st_size,
                   reverse=True)
    return wavs[:limit]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--fixtures", default=os.path.expanduser(
        "~/.local/share/jarvis/voice-trigger"))
    ap.add_argument("--samples", type=int, default=10,
                    help="clipes por categoria")
    ap.add_argument("--max-seconds", type=float, default=8.0,
                    help="teto de audio por clip (o ring do ASRD segura 20 s)")
    ap.add_argument("--categories", default=",".join(CATEGORIES))
    ap.add_argument("--speed", type=float, default=1.0,
                    help="1.0 = tempo real (o VAD fecha por relogio)")
    ap.add_argument("--silence-seconds", type=float, default=1.0)
    ap.add_argument("--control", type=int, default=3,
                    help="wavs de fala real como controle (0 = sem)")
    ap.add_argument("--no-control", action="store_true")
    ap.add_argument("--no-segment-check", dest="segment_check",
                    action="store_false",
                    help="nao re-postar cada segmento no whisper (mais rapido)")
    ap.add_argument("--python", default=DEFAULT_PYTHON)
    ap.add_argument("--taskset", default="0-11")
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--out", default=str(REPO / "reports" / "voice-pipeline"))
    args = ap.parse_args()

    import pandas as pd

    cats = [c.strip() for c in args.categories.split(",") if c.strip()]
    outdir = Path(args.out)
    outdir.mkdir(parents=True, exist_ok=True)
    ts = time.strftime("%Y-%m-%dT%H:%M:%S")
    report = {"ts": ts, "asrd": str(ASRD), "fixtures": args.fixtures,
              "samples_per_cat": args.samples, "max_seconds": args.max_seconds,
              "speed": args.speed, "categories": {}}

    asrd = Asrd(args.python, args.taskset)
    print(f"ASRD pronto ({ts})", flush=True)

    try:
        # ---- controle positivo: fala real tem de virar texto ----
        control = {"wavs": 0, "with_text": 0, "texts": []}
        if not args.no_control and args.control > 0:
            for wav in _control_wavs(args.control):
                import soundfile as sf
                data, sr = sf.read(str(wav), dtype="float32")
                if getattr(data, "ndim", 1) > 1:
                    data = data.mean(axis=1)
                if sr != SR:
                    n = int(len(data) * SR / sr)
                    idx = np.linspace(0, len(data) - 1, n, dtype=np.float64)
                    data = np.interp(idx, np.arange(len(data)), data).astype("float32")
                lines = _feed_clip(asrd, data, args.speed, args.silence_seconds)
                texts = _texts(lines)
                control["wavs"] += 1
                control["with_text"] += 1 if texts else 0
                control["texts"].append({"wav": wav.name, "texts": texts[:3]})
                print(f"controle {wav.name}: {texts[:1]}", flush=True)
        report["control"] = control

        # ---- gatilhos pelo pipeline real ----
        import random
        for cat in cats:
            path = Path(args.fixtures) / f"{cat}.parquet"
            if not path.is_file():
                report["categories"][cat] = {"error": f"sem fixtures: {path}"}
                continue
            df = pd.read_parquet(path)
            idx = list(range(len(df)))
            # semente POR CATEGORIA: com um rng compartilhado a fatia de uma
            # categoria dependia de quantas categorias vieram antes, e dois
            # runs com subconjuntos diferentes nao eram comparaveis
            rng = random.Random(f"{args.seed}:{cat}")
            rng.shuffle(idx)
            idx = idx[: args.samples]
            clips = 0
            with_text = 0
            seg_closed = 0
            raw_hallu = 0
            texts_seen = []
            per_clip = []
            for i in idx:
                row = df.iloc[i]
                pcm = _load_clip(row["audio"]["bytes"])
                if len(pcm) > int(args.max_seconds * SR):
                    pcm = pcm[: int(args.max_seconds * SR)]
                # caminho cru (o do trigger bench) no MESMO audio/mesma janela
                raw = _raw_whisper(pcm)
                raw_text = (raw.get("text") or "").strip()
                raw_bad = bool(raw_text) and any(c.isalnum() for c in raw_text)
                # caminho da casa
                lines = _feed_clip(asrd, pcm, args.speed, args.silence_seconds)
                texts = _texts(lines)
                closed = _segments_closed(lines)
                # onde o audio morreu: o segmento cru tinha texto e a saida
                # da casa veio vazia => quem matou foi o gate anti_halluc
                seg_detail = []
                for obj in lines:
                    if "text" not in obj:
                        continue
                    raw_seg = _raw_whisper_file(obj.get("wav", "")) if args.segment_check else {}
                    raw_text = (raw_seg.get("text") or "").strip()
                    seg_detail.append({
                        "wav": Path(obj.get("wav", "")).name,
                        "pipeline_text": (obj.get("text") or "").strip()[:60],
                        "raw_segment_text": raw_text[:60],
                        "raw_ns": round(raw_seg.get("no_speech_prob", 0.0), 4),
                        "raw_lp": round(raw_seg.get("avg_logprob", 0.0), 4),
                        "gate_killed": bool(raw_text) and not (obj.get("text") or "").strip(),
                    })
                clips += 1
                seg_closed += closed
                raw_hallu += 1 if raw_bad else 0
                if texts:
                    with_text += 1
                texts_seen += texts
                per_clip.append({"id": str(row.get("id")),
                                 "seconds": round(len(pcm) / SR, 2),
                                 "raw_whisper": raw_text[:60],
                                 "raw_ns": round(raw.get("no_speech_prob", 0.0), 4),
                                 "raw_lp": round(raw.get("avg_logprob", 0.0), 4),
                                 "segments_closed": closed,
                                 "segments": seg_detail,
                                 "texts": texts[:3]})
            counts = {}
            for t in texts_seen:
                counts[t] = counts.get(t, 0) + 1
            report["categories"][cat] = {
                "clips": clips,
                "segments_closed": seg_closed,
                "clips_with_text": with_text,
                "rate": round(with_text / clips, 3) if clips else None,
                "raw_whisper_hallucinated": raw_hallu,
                "raw_rate": round(raw_hallu / clips, 3) if clips else None,
                "top_texts": sorted(counts.items(), key=lambda kv: -kv[1])[:8],
                "per_clip": per_clip[:10],
            }
            print(f"{cat}: cru {raw_hallu}/{clips} | casa "
                  f"{with_text}/{clips} ({report['categories'][cat]['rate']}) | "
                  f"segmentos fechados: {seg_closed}", flush=True)
    finally:
        asrd.close()

    out = outdir / f"{ts.replace(':', '')}.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=1))
    print(f"relatorio: {out}")
    for cat, v in report["categories"].items():
        if "error" in v:
            print(f"  {cat}: {v['error']}")
            continue
        print(f"  {cat}: {v['clips_with_text']}/{v['clips']} "
              f"({v['rate']}) | segmentos fechados: {v.get('segments_closed')} "
              f"| {v['top_texts'][:3]}")
    c = report.get("control") or {}
    if c.get("wavs"):
        print(f"  controle (fala real): {c['with_text']}/{c['wavs']}")


if __name__ == "__main__":
    main()
