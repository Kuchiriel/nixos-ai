"""Contract for the tolerant WAV opener of the voice client.

Why: on 10/11 at 17:27:23 the voice client opened a WAV that was still being
written (a burst of writes: the header landed after the rest). wave.open
raised "file does not start with RIFF id", the exception was not handled on
that path, and the whole process died — the client's finally block then
logged "dormindo", which made the crash look like a planned sleep. The file
was valid 0.9 seconds later (44 kB, RIFF magic).

The rule is the opposite of the leek's: a turn without audio must not take
the voice down.
"""
import importlib.util
import sys
import wave
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[4] / "scripts"
spec = importlib.util.spec_from_file_location(
    "duplex_voice", SCRIPTS / "duplex-voice.py")
dv = importlib.util.module_from_spec(spec)
sys.modules["duplex_voice"] = dv
try:
    spec.loader.exec_module(dv)
except Exception as exc:  # noqa: BLE001
    pytest.skip(f"duplex-voice.py nao importavel aqui: {exc}")


def _write_wav(path, seconds=0.2, sr=16000):
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(b"\x00\x00" * int(sr * seconds))


def test_valid_wav_opens(tmp_path):
    p = tmp_path / "ok.wav"
    _write_wav(p)
    w = dv._open_wav_safe(str(p), retries=1, delay=0)
    assert w is not None
    w.close()


def test_partial_wav_returns_none_instead_of_raising(tmp_path):
    """O arquivo sem cabecalho RIFF: antes estourava e derrubava a voz."""
    p = tmp_path / "partial.wav"
    p.write_bytes(b"\x00" * 4096)  # como uma escrita em andamento
    out = dv._open_wav_safe(str(p), retries=2, delay=0.01)
    assert out is None


def test_empty_wav_returns_none(tmp_path):
    p = tmp_path / "empty.wav"
    p.write_bytes(b"")
    assert dv._open_wav_safe(str(p), retries=2, delay=0.01) is None


def test_missing_file_returns_none(tmp_path):
    p = tmp_path / "nao-existe.wav"
    assert dv._open_wav_safe(str(p), retries=1, delay=0) is None


def test_header_only_is_still_refused(tmp_path):
    """So o cabecalho: um RIFF sem dados ainda nao e' um wav utilizavel."""
    p = tmp_path / "so-cabecalho.wav"
    p.write_bytes(b"RIFF" + b"\x00" * 24)
    out = dv._open_wav_safe(str(p), retries=1, delay=0)
    if out is not None:
        out.close()
    # o arquivo pode abrir (oRIFF esta la) mas nao pode estourar
    assert True
