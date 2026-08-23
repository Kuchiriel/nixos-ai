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
STT_MODEL_DEFAULT = "tiny"  # faster-whisper: tiny multilingual (~75MB, PT-BR+EN, ~1s CPU)

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
        model_dir = _model_dir()
        model = WhisperModel(model_size, device="cpu", compute_type="int8", download_root=model_dir)
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

def _setup_kokoro_espeak():
    """Bypass spaCy: monkey-patch en.G2P para usar espeak-ng.

    Kokoro 0.9+ usa spaCy para English G2P (grapheme-to-phoneme), mas spaCy
    precisa de modelo baixado via pip — impossível no NixOS declarativo.
    Esta função substitui en.G2P por um wrapper que usa espeak-ng, que já
    está no PATH do nix develop. Chamada uma vez; idempotente.
    """
    if getattr(_setup_kokoro_espeak, "_done", False):
        return
    try:
        from kokoro.pipeline import en as _en, espeak as _espeak_mod
        _espeak_backend = _espeak_mod.EspeakG2P(language="en-us")

        class _EspeakG2PWrapper:
            def __init__(self, *args: Any, **kwargs: Any) -> None:
                pass

            def __call__(self, text: str, preprocess: bool = True) -> tuple[str, list]:
                ps_list = _espeak_backend.backend.phonemize([text])
                ps = ps_list[0].strip() if ps_list else ""
                words = text.split()
                tokens = []
                for i, word in enumerate(words):
                    ws = " " if i < len(words) - 1 else ""
                    t = _en.MToken(text=word, tag="NN", whitespace=ws)
                    try:
                        w_ps = _espeak_backend.backend.phonemize([word])
                        t.phonemes = w_ps[0].strip() if w_ps else ""
                    except Exception:  # noqa: BLE001 — phonemize é best-effort
                        t.phonemes = ""
                    tokens.append(t)
                return ps, tokens

        _en.G2P = _EspeakG2PWrapper  # type: ignore[misc]
        _setup_kokoro_espeak._done = True  # type: ignore[attr-defined]
    except Exception:  # noqa: BLE001 — espeak é best-effort
        pass  # se espeak não está disponível, Kokoro vai dar erro own


def speak(text: str, voice: str | None = None, *, play: bool = True) -> str:
    """Sintetiza `text` com Kokoro-82M (formato torch do nixpkgs) e (opcionalmente) toca.

    Aplica a prosódia emocional (speed) do `jarvis.core.emotion` — porta do
    emotional_state do legado (keywords → perfil → speed do Kokoro).
    Bypass automático de spaCy via espeak-ng quando o modelo spaCy não está
    disponível (comum em NixOS declarativo).
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
        _setup_kokoro_espeak()  # bypass spaCy antes de criar pipeline
        kmodel = KModel(config=config_path, model=model_path)
        pipeline = KPipeline(lang_code="a", model=kmodel, trf=False)
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
    """Toca um WAV (pw-play → canberra → mpv → aplay, em ordem de preferência)."""
    pw_play = "/run/current-system/sw/bin/pw-play"
    for cmd in (
        [pw_play, wav_path],
        ["canberra-gtk-play", "--file", wav_path],
        ["mpv", "--no-video", "--really-quiet", wav_path],
        ["paplay", wav_path],
        ["aplay", "-q", wav_path],
    ):
        try:
            subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=30)
            return
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
            continue


# ---------------------------------------------------------------------------
# Conversão de respostas para texto limpo (TTS)
# ---------------------------------------------------------------------------

def _text_for_tts(out: dict[str, Any] | str) -> str:
    """Converte a resposta do router em texto limpo para TTS.

    O router retorna dicts com chaves como 'response', 'overall', 'checks'.
    Para TTS, queremos apenas o texto principal, sem JSON cru.
    """
    if isinstance(out, str):
        return out

    # Rota doctor: {overall, checks, actions}
    if "overall" in out:
        overall = out["overall"]
        checks = out.get("checks", [])
        down = [c.get("name", "") for c in checks if c.get("status") == "down"]
        degraded = [c.get("name", "") for c in checks if c.get("status") == "degraded"]
        parts = [f"Sistema {overall}."]
        if down:
            parts.append(f"Servicos fora: {', '.join(down)}.")
        if degraded:
            parts.append(f"Degradados: {', '.join(degraded)}.")
        return " ".join(parts)

    # Rota agent: {response, commands_run, commands_denied}
    if "response" in out:
        return str(out["response"])

    # Rota rag: {hits}
    if "hits" in out:
        hits = out["hits"]
        if not hits:
            return "Nao encontrei nada no codigo."
        lines = []
        for h in hits[:3]:
            path = h.get("path", "")
            score = h.get("score", 0)
            lines.append(f"{path} (relevancia {score:.0%})")
        return f"Encontrei: {', '.join(lines)}."

    # Rota fastpath: {response}
    if "response" in out:
        return str(out["response"])

    # Fallback
    return str(out)[:500]


# ---------------------------------------------------------------------------
# Loop de voz completo (wakeword → STT → roteador → TTS)
# ---------------------------------------------------------------------------

def voice_loop(audio_path: str, *, tts: bool = True, model_size: str = STT_MODEL_DEFAULT) -> int:
    """Pipeline completo para o brainCommand do wakeword.

    STT do WAV capturado → load check → roteia o pedido → TTS da resposta.
    Tolerante: cada etapa degrada sem quebrar as seguintes.

    Load shedding: se o LLM está sobrecarregado (todos os slots ocupados ou
    contexto >80%), retorna resposta busy via TTS sem tentar o LLM — evita
    sobrecarregar ainda mais e dá feedback imediato ao usuário.
    """
    from jarvis.core.busy import check_load, handle_busy
    from jarvis.core.feedback import set_status
    from jarvis.core.logging import get_logger
    from jarvis.core.router import (
        handle_agent, handle_doctor, handle_fastpath, handle_nixos, handle_rag, route_request,
    )

    log = get_logger("voice")

    # 1. STT
    set_status("transcribing", "Transcrevendo...")
    text = transcribe(audio_path, model_size=model_size)
    if text.startswith("ERROR"):
        set_status("error", text[:80])
        print(text, file=sys.stderr)
        return 1
    if not text:
        set_status("idle", "")
        print("(voz vazia)", file=sys.stderr)
        return 0

    print(f"🎤 {text}", flush=True)

    # 2. Roteamento
    route = route_request(text)

    # 3. Load shedding — verifica carga ANTES de chamar o LLM
    #    Rotas que NÃO usam LLM (fastpath, doctor, nixos, rag) passam direto.
    needs_llm = route.handler in ("agent",)
    if needs_llm:
        from jarvis.providers.llm import LLMClient
        from jarvis.core.config import get_config
        llm = LLMClient(get_config())
        load = check_load(llm)
        if load["busy"]:
            log.warning("voice_load_shed", detail={
                "reason": load["reason"],
                "text": text[:100],
            })
            return handle_busy(load, tts=tts)

    # 4. Executa a rota
    set_status("thinking", f"{route.handler}: {text[:40]}")
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
        set_status("error", str(exc)[:80])
        print(f"ERROR: rota '{route.handler}' falhou: {exc}", file=sys.stderr)
        return 1

    # 5. TTS
    answer = _text_for_tts(out)
    set_status("speaking", answer[:60])
    if tts:
        wav = speak(answer)
        print(f"🔊 {answer}", flush=True)
        if wav.startswith("ERROR"):
            print(wav, file=sys.stderr)
    else:
        print(f"💬 {answer}", flush=True)

    set_status("done", "")
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
    return voice_loop(args.wav, tts=not args.no_tts, model_size=args.model)


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
