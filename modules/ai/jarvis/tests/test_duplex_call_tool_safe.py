"""Contract for the tool-call guard of the voice client.

Why: on 10/11 at 17:27:23 a tool opened a wav that was still being written;
wave.open raised, the exception climbed through call_tool into the main loop,
and the whole process died. A tool that fails must become an error string for
the model, never the death of the voice.
"""
import importlib.util
import sys
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


def test_failing_tool_returns_an_error_string(monkeypatch):
    def _boom(name, args):
        raise RuntimeError("file does not start with RIFF id")

    monkeypatch.setattr(dv, "call_tool", _boom)
    out = dv.call_tool_safe("play_audio", {"path": "x.wav"})
    assert isinstance(out, str)
    assert "play_audio" in out
    assert "RIFF" in out


def test_working_tool_passes_through(monkeypatch):
    monkeypatch.setattr(dv, "call_tool", lambda name, args: f"ok:{name}")
    assert dv.call_tool_safe("get_time", {}) == "ok:get_time"


def test_guard_is_used_at_the_call_site():
    """O laco principal tem de chamar o wrapper, nao a tool crua."""
    src = (SCRIPTS / "duplex-voice.py").read_text(encoding="utf-8")
    assert "result = call_tool_safe(name, args)" in src
    assert "result = call_tool(name, args)" not in src
