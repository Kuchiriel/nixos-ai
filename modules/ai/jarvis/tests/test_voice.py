"""Testes da voz (core/voice.py) — imports lazy e falhas tolerantes."""
import pytest
pytestmark = pytest.mark.integration

from pathlib import Path
from types import SimpleNamespace

import pytest

from jarvis.core import voice


def _fake_module(**attrs) -> SimpleNamespace:
    """Cria um objeto que se comporta como módulo (para sys.modules)."""
    return SimpleNamespace(**attrs)


# ---------------------------------------------------------------------------
# transcribe
# ---------------------------------------------------------------------------

def test_transcribe_returns_error_without_faster_whisper(monkeypatch) -> None:
    """Sem faster-whisper instalado → mensagem ERROR (não exceção)."""
    # sys.modules[name] = None força ImportError no `from faster_whisper import ...`
    monkeypatch.setitem(voice.sys.modules, "faster_whisper", None)
    out = voice.transcribe("/tmp/x.wav")
    assert out.startswith("ERROR:")
    assert "faster-whisper" in out


def test_transcribe_uses_calibrated_vad(monkeypatch, tmp_path) -> None:
    """VAD calibrado do legado (threshold 0.5, min_silence 1000, pad 400)."""
    captured = {}

    class FakeWhisperModel:
        def __init__(self, *a, **k):
            captured["model_kwargs"] = k

        def transcribe(self, path, **kwargs):
            captured["vad"] = kwargs["vad_parameters"]
            captured["path"] = path

            class Seg:
                text = "olá jarvis"

            class _Info:
                pass

            return iter([Seg()]), _Info()

    monkeypatch.setitem(
        voice.sys.modules,
        "faster_whisper",
        _fake_module(WhisperModel=FakeWhisperModel),
    )
    out = voice.transcribe(str(tmp_path / "cmd.wav"))
    assert out == "olá jarvis"
    assert captured["path"] == str(tmp_path / "cmd.wav")
    vad = captured["vad"]
    assert vad["threshold"] == 0.5
    assert vad["min_silence_duration_ms"] == 1000
    assert vad["speech_pad_ms"] == 400
    # CPU + int8 (ambiente sem GPU garantida)
    assert captured["model_kwargs"]["device"] == "cpu"
    assert captured["model_kwargs"]["compute_type"] == "int8"


def test_transcribe_handles_exception(monkeypatch, tmp_path) -> None:
    class BoomModel:
        def __init__(self, *a, **k):
            raise RuntimeError("modelo não baixou")

    monkeypatch.setitem(
        voice.sys.modules,
        "faster_whisper",
        _fake_module(WhisperModel=BoomModel),
    )
    out = voice.transcribe(str(tmp_path / "x.wav"))
    assert out.startswith("ERROR:")
    assert "modelo não baixou" in out


# ---------------------------------------------------------------------------
# speak (TTS)
# ---------------------------------------------------------------------------

def test_speak_returns_error_without_kokoro(monkeypatch) -> None:
    monkeypatch.setitem(voice.sys.modules, "kokoro", None)
    out = voice.speak("oi", play=False)
    assert out.startswith("ERROR:")
    assert "kokoro" in out


def test_speak_returns_error_when_model_missing(monkeypatch, tmp_path) -> None:
    """Modelo não baixado → erro claro (provisionamento declarativo do host)."""
    monkeypatch.setitem(voice.sys.modules, "kokoro", _fake_module(KModel=object, KPipeline=object))
    monkeypatch.setitem(voice.sys.modules, "soundfile", _fake_module())
    monkeypatch.setitem(voice.sys.modules, "numpy", _fake_module())

    missing = tmp_path / "nao-existe.pth"
    monkeypatch.setattr(voice, "KOKORO_CONFIG_DEFAULT", str(missing))
    monkeypatch.setattr(voice, "KOKORO_MODEL_DEFAULT", str(missing))
    monkeypatch.setattr(voice, "KOKORO_VOICE_DEFAULT", str(missing))
    out = voice.speak("oi", play=False)
    assert out.startswith("ERROR:")
    assert "Kokoro" in out


def test_speak_generates_wav(monkeypatch, tmp_path) -> None:
    """Happy path: kokoro gera áudio e salva WAV (sem tocar)."""
    captured = {}

    class FakeKModel:
        def __init__(self, **k):
            captured["kmodel_kwargs"] = k

    class FakePipeline:
        def __init__(self, **k):
            captured["kwargs"] = k

        def __call__(self, text, voice=None, speed=1.0):
            captured["text"] = text
            captured["voice"] = voice
            captured["speed"] = speed
            return iter([SimpleNamespace(audio=__import__("numpy").array([0.1, 0.2]))])

    def _fake_write(path, audio, rate):
        Path(path).write_bytes(b"WAV")

    fake_np = __import__("numpy")
    monkeypatch.setitem(voice.sys.modules, "kokoro", _fake_module(KModel=FakeKModel, KPipeline=FakePipeline))
    monkeypatch.setitem(voice.sys.modules, "soundfile", _fake_module(write=_fake_write))
    monkeypatch.setitem(voice.sys.modules, "numpy", fake_np)
    (tmp_path / "config.json").write_bytes(b"{}")
    (tmp_path / "kokoro.pth").write_bytes(b"model")
    (tmp_path / "af_heart.pt").write_bytes(b"voice")
    monkeypatch.setenv("JARVIS_VOICE_DIR", str(tmp_path))
    monkeypatch.setattr(voice, "KOKORO_CONFIG_DEFAULT", str(tmp_path / "config.json"))
    monkeypatch.setattr(voice, "KOKORO_MODEL_DEFAULT", str(tmp_path / "kokoro.pth"))
    monkeypatch.setattr(voice, "KOKORO_VOICE_DEFAULT", str(tmp_path / "af_heart.pt"))
    # Force _voice_for_lang to use our tmp_path voice (system may have real kokoro installed)
    monkeypatch.setattr(voice, "_voice_for_lang", lambda lang, override=None: str(tmp_path / "af_heart.pt"))

    out = voice.speak("olá mundo", play=False)
    assert not out.startswith("ERROR")
    assert out.endswith(".wav")
    assert Path(out).exists()
    assert captured["voice"] == str(tmp_path / "af_heart.pt")
    # prosódia emocional: texto neutro → speed 1.0
    assert captured["speed"] == 1.0


# ---------------------------------------------------------------------------
# voice_loop (STT → roteador → TTS)
# ---------------------------------------------------------------------------

def test_voice_loop_routes_and_responds(monkeypatch, tmp_path) -> None:
    wav = tmp_path / "cmd.wav"
    wav.write_bytes(b"RIFF")

    monkeypatch.setattr(voice, "transcribe", lambda p, model_size="small": "como está o sistema?")

    class FakeRoute:
        handler = "doctor"
        query = "como está o sistema?"

    # voice_loop importa os handlers de jarvis.core.router no momento da chamada
    import jarvis.core.router as router_mod

    monkeypatch.setattr(router_mod, "route_request", lambda text: FakeRoute())
    monkeypatch.setattr(router_mod, "handle_doctor", lambda: {"response": "tudo ok"})
    monkeypatch.setattr(router_mod, "handle_agent", lambda q: {"response": "agent"})
    monkeypatch.setattr(router_mod, "handle_fastpath", lambda q: {"response": "fp"})
    monkeypatch.setattr(router_mod, "handle_nixos", lambda q, cfg=None, mcp_bin=None: {"response": "nix"})
    monkeypatch.setattr(router_mod, "handle_rag", lambda q, cfg=None, top_k=5: {"response": "rag"})
    monkeypatch.setattr(voice, "speak", lambda text, play=True: str(tmp_path / "out.wav"))

    rc = voice.voice_loop(str(wav), tts=True)
    assert rc == 0


def test_voice_loop_handles_stt_error(monkeypatch, tmp_path) -> None:
    wav = tmp_path / "cmd.wav"
    wav.write_bytes(b"RIFF")
    monkeypatch.setattr(voice, "transcribe", lambda p, model_size="small": "ERROR: falha na transcrição: x")
    assert voice.voice_loop(str(wav), tts=False) == 1


def test_voice_loop_handles_empty(monkeypatch, tmp_path) -> None:
    wav = tmp_path / "cmd.wav"
    wav.write_bytes(b"RIFF")
    monkeypatch.setattr(voice, "transcribe", lambda p, model_size="small": "")
    assert voice.voice_loop(str(wav), tts=False) == 0


def test_main_stt_missing_file() -> None:
    assert voice.main_stt(["/tmp/nao-existe-xyz.wav"]) == 1


def test_main_voice_missing_file() -> None:
    assert voice.main_voice(["/tmp/nao-existe-xyz.wav"]) == 1


def test_main_voice_passes_model_to_pipeline(monkeypatch, tmp_path) -> None:
    wav = tmp_path / "cmd.wav"
    wav.write_bytes(b"RIFF")
    seen = {}

    def fake_voice_loop(audio_path, *, tts=True, model_size=voice.STT_MODEL_DEFAULT):
        seen["audio_path"] = audio_path
        seen["tts"] = tts
        seen["model_size"] = model_size
        return 0

    monkeypatch.setattr(voice, "voice_loop", fake_voice_loop)
    assert voice.main_voice([str(wav), "--model", "small", "--no-tts"]) == 0
    assert seen["audio_path"] == str(wav)
    assert seen["tts"] is False
    assert seen["model_size"] == "small"
