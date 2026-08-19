"""`jarvis voice` — STT + TTS + loop de voz completo.

Decisão validada por pesquisa 2026 (docs/architecture/legacy-inventory-findings.md):
- **STT**: faster-whisper (CTranslate2, nixpkgs 1.2.1) — Whisper Large V3 continua o
  padrão multi-língua (99+, incl. PT-BR); o runtime faster-whisper é recomendado
  para CPU. VAD calibrado no legado (ambiente ruidoso: ventoinha + casa):
  threshold=0.5, min_silence=1000ms, speech_pad=400ms.
- **TTS**: Kokoro-82M — "eficiência king" 2026 (82M params, <1GB, CPU, RTF 0.03,
  Apache-2.0, 54 vozes/8 línguas incl. PT-BR). O legado já usava Kokoro.

Os imports das libs pesadas (faster_whisper, kokoro) são **lazy** — o módulo
carrega rápido e falhas de dependência viram mensagens claras, nunca exceções
que quebrem o agente/roteador.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from typing import Any

# ---------------------------------------------------------------------------
# Configuração (compatível com o Config do pacote, mas independente)
# ---------------------------------------------------------------------------

MODEL_DIR_DEFAULT = "~/.local/share/jarvis/voice"
STT_MODEL_DEFAULT = "small"  # faster-whisper: tiny/base/small/medium/large-v3

# Kokoro-82M no formato do nixpkgs (torch): config.json + kokoro-v1_0.pth +
# voz voices/af_heart.pt. No host, os paths vêm do store Nix via env vars
# (JARVIS_KOKORO_CONFIG/MODEL/VOICE) — declarativo, sem download em runtime.
KOKORO_CONFIG_DEFAULT = os.environ.get("JARVIS_KOKORO_CONFIG", "~/.local/share/kokoro/config.json")
KOKORO_MODEL_DEFAULT = os.environ.get("JARVIS_KOKORO_MODEL", "~/.local/share/kokoro/kokoro-v1_0.pth")
KOKORO_VOICE_DEFAULT = os.environ.get("JARVIS_KOKORO_VOICE", "~/.local/share/kokoro/af_heart.pt")
KOKORO_VOICE_ID_DEFAULT = "af_heart"  # id da voz (para o nome do arquivo)


def _model_dir() -> str:
    return os.path.expanduser(os.environ.get("JARVIS_VOICE_DIR", MODEL_DIR_DEFAULT))


# ---------------------------------------------------------------------------
# STT — faster-whisper
# ---------------------------------------------------------------------------

def transcribe(
    audio_path: str,
    model_size: str = STT_MODEL_DEFAULT,
    language: str | None = None,
) -> str:
    """Transcreve um WAV com faster-whisper + VAD calibrado do legado.

    Parâmetros VAD (calibrados para ventoinha/sons de casa — ver
    docs/architecture/legacy-audio-calibration.md):
      threshold=0.5, min_speech=250ms, min_silence=1000ms, speech_pad=400ms.
    """
    try:
        from faster_whisper import WhisperModel  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover — depende do ambiente
        return f"ERROR: faster-whisper não instalado: {exc}"

    try:
        model = WhisperModel(model_size, device="cpu", compute_type="int8", download_root=_model_dir())
        segments, _info = model.transcribe(
            audio_path,
            beam_size=3,
            language=language,
            vad_filter=True,
            vad_parameters=dict(
                threshold=0.5,
                min_speech_duration_ms=250,
                min_silence_duration_ms=1000,
                speech_pad_ms=400,
            ),
        )
        return " ".join(seg.text for seg in segments).strip()
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: falha na transcrição: {exc}"


# ---------------------------------------------------------------------------
# TTS — Kokoro-82M
# ---------------------------------------------------------------------------

def speak(text: str, voice: str | None = None, *, play: bool = True) -> str:
    """Sintetiza `text` com Kokoro-82M (formato torch do nixpkgs) e (opcionalmente) toca.

    Aplica a prosódia emocional (speed) do `jarvis.core.emotion` — porta do
    emotional_state do legado (keywords → perfil → speed do Kokoro).
    Retorna o path do WAV gerado ou mensagem ERROR:.
    """
    try:
        import numpy as np  # noqa: F401  (kokoro depende)
        from kokoro import KModel, KPipeline  # type: ignore[import-not-found]
        import soundfile as sf  # type: ignore[import-not-found]
    except ImportError as exc:  # pragma: no cover
        return f"ERROR: kokoro não instalado: {exc}"

    try:
        from jarvis.core.emotion import speed_for

        config_path = os.path.expanduser(KOKORO_CONFIG_DEFAULT)
        model_path = os.path.expanduser(KOKORO_MODEL_DEFAULT)
        missing = [p for p in (config_path, model_path) if not Path(p).exists()]
        voice_path = os.path.expanduser(KOKORO_VOICE_DEFAULT)
        if not Path(voice_path).exists():
            missing.append(voice_path)
        if missing:
            return (
                f"ERROR: arquivos Kokoro não encontrados: {', '.join(missing)}. "
                "No host, eles vêm do store Nix (modules/ai/models.nix) e o PATH "
                "via JARVIS_KOKORO_* — provisionamento declarativo."
            )
        voice_path = voice or os.path.expanduser(KOKORO_VOICE_DEFAULT)
        kmodel = KModel(config=config_path, model=model_path)
        pipeline = KPipeline(lang_code="a", model=kmodel)
        out_dir = Path(_model_dir()) / "tts"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"jarvis_tts_{abs(hash(text)) % 10**9}.wav"

        speed = speed_for(text)
        chunks = []
        for _result in pipeline(text, voice=voice_path, speed=speed):
            chunks.append(_result.audio)
        if not chunks:
            return "ERROR: kokoro não gerou áudio"
        audio = np.concatenate(chunks)
        sf.write(str(out_path), audio, 24000)

        if play:
            _play(str(out_path))
        return str(out_path)
    except Exception as exc:  # noqa: BLE001
        return f"ERROR: falha no TTS: {exc}"


def _play(wav_path: str) -> None:
    """Toca um WAV (canberra → paplay → aplay, em ordem de preferência)."""
    for cmd in (
        ["canberra-gtk-play", "--file", wav_path],
        ["paplay", wav_path],
        ["aplay", "-q", wav_path],
    ):
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
            return
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue


# ---------------------------------------------------------------------------
# Loop de voz completo (wakeword → STT → roteador → TTS)
# ---------------------------------------------------------------------------

def voice_loop(audio_path: str, *, tts: bool = True) -> int:
    """Pipeline completo para o brainCommand do wakeword.

    STT do WAV capturado → roteia o pedido (`jarvis ask`) → TTS da resposta.
    Tolerante: cada etapa degrada sem quebrar as seguintes.
    """
    from jarvis.core.router import (
        handle_agent, handle_doctor, handle_fastpath, handle_nixos, handle_rag, route_request,
    )

    text = transcribe(audio_path)
    if text.startswith("ERROR"):
        print(text, file=sys.stderr)
        return 1
    if not text:
        print("(voz vazia)", file=sys.stderr)
        return 0

    print(f"🎤 {text}", flush=True)
    route = route_request(text)
    try:
        if route.handler == "fastpath":
            out = handle_fastpath(route.query)
        elif route.handler == "doctor":
            out = handle_doctor()
        elif route.handler == "nixos":
            out = handle_nixos(route.query)
        elif route.handler == "rag":
            out = handle_rag(route.query)
        else:
            out = handle_agent(route.query)
    except Exception as exc:  # noqa: BLE001
        print(f"ERROR: rota '{route.handler}' falhou: {exc}", file=sys.stderr)
        return 1

    answer = str(out.get("response", out))
    if tts:
        wav = speak(answer)
        print(f"🔊 {answer}", flush=True)
        if wav.startswith("ERROR"):
            print(wav, file=sys.stderr)
    else:
        print(f"💬 {answer}", flush=True)
    return 0


def main_voice(argv: list[str] | None = None) -> int:
    """Entry point CLI: jarvis voice <wav> [--no-tts]."""
    import argparse

    parser = argparse.ArgumentParser(prog="jarvis voice", description="STT → roteador → TTS a partir de um WAV")
    parser.add_argument("wav", help="arquivo de áudio capturado pelo wakeword")
    parser.add_argument("--no-tts", action="store_true", help="não sintetizar resposta em voz")
    parser.add_argument("--model", default=STT_MODEL_DEFAULT, help="tamanho do modelo faster-whisper")
    args = parser.parse_args(argv)

    if not Path(args.wav).exists():
        print(f"ERROR: arquivo não existe: {args.wav}", file=sys.stderr)
        return 1
    return voice_loop(args.wav, tts=not args.no_tts)


def main_stt(argv: list[str] | None = None) -> int:
    """Entry point CLI: jarvis stt <wav> [--model small]."""
    import argparse

    parser = argparse.ArgumentParser(prog="jarvis stt", description="Transcreve um WAV (faster-whisper)")
    parser.add_argument("wav", help="arquivo de áudio")
    parser.add_argument("--model", default=STT_MODEL_DEFAULT, help="tamanho do modelo")
    args = parser.parse_args(argv)

    if not Path(args.wav).exists():
        print(f"ERROR: arquivo não existe: {args.wav}", file=sys.stderr)
        return 1
    text = transcribe(args.wav, model_size=args.model)
    print(text)
    return 0 if not text.startswith("ERROR") else 1


def main_tts(argv: list[str] | None = None) -> int:
    """Entry point CLI: jarvis speak <texto> [--voice af_heart] [--no-play]."""
    import argparse

    parser = argparse.ArgumentParser(prog="jarvis speak", description="Sintetiza texto com Kokoro (TTS)")
    parser.add_argument("text", help="texto a falar")
    parser.add_argument("--voice", default=KOKORO_VOICE_ID_DEFAULT, help="id da voz Kokoro (ex: af_heart)")
    parser.add_argument("--no-play", action="store_true", help="gera WAV sem tocar")
    args = parser.parse_args(argv)

    # id da voz → path (mesmo diretório do modelo, voices/<id>.pt)
    voice_path = os.path.expanduser(KOKORO_VOICE_DEFAULT)
    if args.voice != KOKORO_VOICE_ID_DEFAULT and not Path(args.voice).exists():
        voice_dir = Path(voice_path).parent
        candidate = voice_dir / f"{args.voice}.pt"
        if candidate.exists():
            voice_path = str(candidate)
        else:
            voice_path = args.voice  # deixa o speak validar/errar

    out = speak(args.text, voice=voice_path, play=not args.no_play)
    print(out)
    return 0 if not out.startswith("ERROR") else 1


if __name__ == "__main__":
    raise SystemExit(main_voice())
