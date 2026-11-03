"""Testes do ASR_BENCH (core/asr_bench.py) — sem modelo, sem áudio externo."""

from __future__ import annotations

import array
import math
import wave
from pathlib import Path

from jarvis.core.asr_bench import format_line, main, wav_stats


def _write_wav(path: Path, seconds: float = 1.0, rate: int = 16000, channels: int = 1) -> Path:
    n = int(seconds * rate)
    tone = array.array(
        "h",
        [int(12000 * math.sin(2 * math.pi * 440 * i / rate)) for i in range(n)],
    )
    if channels == 2:
        interleaved = array.array("h")
        for s in tone:
            interleaved.append(s)
            interleaved.append(s)
        data = interleaved.tobytes()
    else:
        data = tone.tobytes()
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(channels)
        wf.setsampwidth(2)
        wf.setframerate(rate)
        wf.writeframes(data)
    return path


def test_wav_stats_reads_duration_rms_and_peak(tmp_path):
    wav = _write_wav(tmp_path / "tone.wav", seconds=1.0, rate=16000)
    stats = wav_stats(str(wav))
    assert stats["error"] is None
    assert stats["duration_s"] == 1.0
    assert stats["sample_rate"] == 16000
    assert stats["channels"] == 1
    assert stats["rms"] > 0.1
    assert stats["peak"] <= 1.0


def test_wav_stats_reports_error_for_missing_file(tmp_path):
    stats = wav_stats(str(tmp_path / "nope.wav"))
    assert stats["error"] is not None


def test_format_line_is_parseable(tmp_path):
    wav = _write_wav(tmp_path / "tone.wav", seconds=0.5)
    row = {
        "variant": "vad_off",
        "file": str(wav),
        "audio_s": 0.5,
        "rms": 0.34,
        "peak": 0.5,
        "decode_ms": 250,
        "rtf": 0.5,
        "avg_logprob": -0.3,
        "no_speech": 0.01,
        "words": 2,
        "chars": 9,
        "language": "en",
        "text": 'hello "world"',
    }
    line = format_line(row)
    assert line.startswith("ASR_BENCH variant=vad_off")
    assert "rtf=0.5" in line
    assert "text=" in line
    # aspas do texto não podem quebrar o parse
    assert "\"" in line.split("text=")[1]


def test_main_rejects_missing_file(tmp_path, capsys):
    rc = main([str(tmp_path / "missing.wav")])
    assert rc == 2
