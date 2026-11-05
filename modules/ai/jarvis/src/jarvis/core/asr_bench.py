"""ASR_BENCH — benchmark de STT do JARVIS (instrumentação no estilo FluidVoice).

O app FluidVoice (macOS/CoreML) mede o STT com um log `ASR_BENCH` por
segmento. A IDEIA (medir, não Supor) é o que vale; o código aqui é
implementação própria (o FluidVoice é GPL-3.0).

Serve para responder com número, não com opinião:
  - AEC3 (echo_cancel_source) vs RNNoise-only (rnnoise_source): o STT
    transcreve a própria voz? (o VAD por RMS não distingue TTS de voz)
  - VAD on vs off: o VAD calibrado corta o começo da fala?
  - streaming (janelas de 1,5 s) vs batch: quanto o STT erra no duplex?
  - custo: decode_ms, RTF (tempo real), avg_logprob, no_speech_prob.

Formato de log (1 linha por variante, compacto):

    ASR_BENCH variant=vad_off audio_s=3.20 rms=0.031 peak=0.44 decode_ms=1840
    rtf=0.58 avg_logprob=-0.31 no_speech=0.04 words=7 chars=41 text="..."

Uso:
    python3 -m jarvis.core.asr_bench <wav> [wav...] [--model small]
                                 [--variants vad_on,vad_off] [--json]
                                 [--stream-window 1.5] [--language pt]
"""

from __future__ import annotations

import argparse
import array
import json
import math
import os
import sys
import time
import wave
from pathlib import Path
from typing import Any

STT_MODEL_DEFAULT = os.environ.get("JARVIS_STT_MODEL", "small")
MODEL_DIR_DEFAULT = os.path.expanduser("~/.local/share/jarvis/models")

# Mesmos parâmetros do VAD calibrado do legado (core/voice.py).
VAD_PARAMETERS = {
    "threshold": 0.5,
    "min_speech_duration_ms": 250,
    "min_silence_duration_ms": 1000,
    "speech_pad_ms": 400,
}

VARIANTS: dict[str, dict[str, Any]] = {
    "vad_on": {"vad_filter": True, "beam_size": 3},
    "vad_off": {"vad_filter": False, "beam_size": 3},
    "vad_on_fast": {"vad_filter": True, "beam_size": 1},
}


def model_dir() -> str:
    return os.path.expanduser(os.environ.get("JARVIS_VOICE_DIR", MODEL_DIR_DEFAULT))


def wav_stats(path: str) -> dict[str, Any]:
    """Estatísticas do WAV (stdlib): duração, RMS, pico, sample rate."""
    stats: dict[str, Any] = {"file": path, "error": None}
    try:
        with wave.open(path, "rb") as wf:
            frames = wf.getnframes()
            rate = wf.getframerate() or 1
            channels = wf.getnchannels() or 1
            width = wf.getsampwidth() or 2
            raw = wf.readframes(frames)
    except Exception as exc:  # noqa: BLE001
        stats["error"] = f"{type(exc).__name__}: {exc}"
        return stats

    stats["duration_s"] = round(frames / rate, 3) if rate else 0.0
    stats["sample_rate"] = rate
    stats["channels"] = channels
    stats["sample_width"] = width

    if width == 2:
        samples = array.array("h")
        samples.frombytes(raw[: len(raw) - (len(raw) % 2)])
        peak = max((abs(s) for s in samples), default=0) / 32768.0
        if samples:
            acc = 0.0
            for s in samples:
                acc += float(s) * float(s)
            rms = math.sqrt(acc / len(samples)) / 32768.0
        else:
            rms = 0.0
    elif width == 1:
        peak = max((abs(s - 128) for s in raw), default=0) / 128.0
        rms = (sum((s - 128) ** 2 for s in raw) / len(raw)) ** 0.5 / 128.0 if raw else 0.0
    else:
        peak, rms = 0.0, 0.0

    stats["peak"] = round(peak, 4)
    stats["rms"] = round(rms, 4)
    return stats


def _load_model(size: str):
    from faster_whisper import WhisperModel  # type: ignore[import-not-found]

    return WhisperModel(size, device="cpu", compute_type="int8", download_root=model_dir())


def transcribe_variant(
    path: str,
    model: Any,
    variant: str,
    language: str | None = None,
) -> dict[str, Any]:
    """Transcreve numa variante e devolve a linha ASR_BENCH."""
    cfg = VARIANTS.get(variant, VARIANTS["vad_on"])
    if language is None:
        try:
            from jarvis.core.lang import stt_code

            language = stt_code()
        except Exception:  # noqa: BLE001
            language = None

    t0 = time.perf_counter()
    segments, info = model.transcribe(
        path,
        beam_size=cfg["beam_size"],
        language=language,
        condition_on_previous_text=False,
        initial_prompt="Hey Jarvis.",
        vad_filter=cfg["vad_filter"],
        vad_parameters=VAD_PARAMETERS if cfg["vad_filter"] else None,
    )
    texts: list[str] = []
    lp_weighted, chars = 0.0, 0
    no_speech_weighted, no_speech_weight = 0.0, 0
    for seg in segments:
        texts.append(seg.text)
        lp_weighted += float(getattr(seg, "avg_logprob", 0.0)) * max(len(seg.text), 1)
        chars += len(seg.text)
        ns = float(getattr(seg, "no_speech_prob", 0.0) or 0.0)
        no_speech_weighted += ns * max(len(seg.text), 1)
        no_speech_weight += max(len(seg.text), 1)
    decode_ms = int((time.perf_counter() - t0) * 1000)
    text = " ".join(t.strip() for t in texts if t.strip()).strip()

    stats = wav_stats(path)
    audio_s = float(stats.get("duration_s") or 0.0)
    row: dict[str, Any] = {
        "variant": variant,
        "file": path,
        "audio_s": audio_s,
        "rms": stats.get("rms"),
        "peak": stats.get("peak"),
        "sample_rate": stats.get("sample_rate"),
        "channels": stats.get("channels"),
        "decode_ms": decode_ms,
        "rtf": round(decode_ms / 1000.0 / audio_s, 3) if audio_s else None,
        "avg_logprob": round(lp_weighted / chars, 3) if chars else None,
        "no_speech": round(no_speech_weighted / no_speech_weight, 3) if no_speech_weight else None,
        "words": len(text.split()),
        "chars": len(text),
        "language": getattr(info, "language", language),
        "text": text,
    }
    return row


def format_line(row: dict[str, Any]) -> str:
    """Uma linha ASR_BENCH (parseável por grep/awk)."""
    fields = [
        f"ASR_BENCH variant={row.get('variant')}",
        f"file={row.get('file')}",
        f"audio_s={row.get('audio_s')}",
        f"rms={row.get('rms')}",
        f"peak={row.get('peak')}",
        f"decode_ms={row.get('decode_ms')}",
        f"rtf={row.get('rtf')}",
        f"avg_logprob={row.get('avg_logprob')}",
        f"no_speech={row.get('no_speech')}",
        f"words={row.get('words')}",
        f"chars={row.get('chars')}",
        f"lang={row.get('language')}",
    ]
    text = str(row.get("text") or "").replace('"', "'")
    fields.append(f'text="{text}"')
    return " ".join(fields)


def bench(
    paths: list[str],
    model_size: str = STT_MODEL_DEFAULT,
    variants: list[str] | None = None,
    language: str | None = None,
) -> list[dict[str, Any]]:
    variants = variants or ["vad_on", "vad_off"]
    rows: list[dict[str, Any]] = []
    model = None
    for path in paths:
        for variant in variants:
            if model is None:
                model = _load_model(model_size)
            try:
                row = transcribe_variant(path, model, variant, language)
            except Exception as exc:  # noqa: BLE001
                row = {
                    "variant": variant,
                    "file": path,
                    "error": f"{type(exc).__name__}: {exc}",
                    "text": "",
                }
            rows.append(row)
    return rows


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="asr_bench",
        description="Mede o STT do JARVIS (ASR_BENCH): VAD on/off, RTF, confiança.",
    )
    parser.add_argument("wavs", nargs="+", help="arquivo(s) WAV para medir")
    parser.add_argument("--model", default=STT_MODEL_DEFAULT, help="tamanho do faster-whisper")
    parser.add_argument(
        "--variants",
        default="vad_on,vad_off",
        help="variantes: " + ",".join(sorted(VARIANTS)),
    )
    parser.add_argument("--language", default=None, help="código de idioma (ex: pt, en)")
    parser.add_argument("--json", action="store_true", help="saída em JSON")
    args = parser.parse_args(argv)

    paths = [str(Path(p).expanduser()) for p in args.wavs]
    missing = [p for p in paths if not Path(p).exists()]
    if missing:
        print(f"ERROR: arquivo(s) não encontrado: {', '.join(missing)}", file=sys.stderr)
        return 2

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    rows = bench(paths, model_size=args.model, variants=variants, language=args.language)

    if args.json:
        print(json.dumps(rows, indent=2, ensure_ascii=False))
    else:
        for row in rows:
            if row.get("error"):
                print(f"ASR_BENCH variant={row['variant']} file={row['file']} ERROR={row['error']}")
            else:
                print(format_line(row))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
