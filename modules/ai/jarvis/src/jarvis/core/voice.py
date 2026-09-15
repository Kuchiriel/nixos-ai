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
# Confiança mínima (avg_logprob ponderado por chars): calibrado 2026-09 —
# fala limpa -0.23/-0.38, alucinações em ruído -0.69..-1.14. Abaixo disso,
# descarta (vira "voz vazia", rc=2) em vez de agir sobre delírio.
STT_MIN_CONFIDENCE = -0.60
# Fonte de verdade do modelo: modules/ai/models.nix (whisper-small).
# O módulo Nix espelha via JARVIS_STT_MODEL; trocar lá + aqui (env) juntos.
STT_MODEL_DEFAULT = os.environ.get("JARVIS_STT_MODEL", "small")

# Kokoro-82M no formato do nixpkgs (torch): config.json + kokoro-v1_0.pth +
# voz voices/af_heart.pt. No host, os paths vêm do store Nix via env vars
# (JARVIS_KOKORO_CONFIG/MODEL/VOICE) — declarativo, sem download em runtime.
KOKORO_CONFIG_DEFAULT = os.environ.get("JARVIS_KOKORO_CONFIG", "~/.local/share/kokoro/config.json")
KOKORO_MODEL_DEFAULT = os.environ.get("JARVIS_KOKORO_MODEL", "~/.local/share/kokoro/kokoro-v1_0.pth")
KOKORO_VOICE_DEFAULT = os.environ.get("JARVIS_KOKORO_VOICE", "~/.local/share/kokoro/af_heart.pt")
KOKORO_VOICE_ID_DEFAULT = "af_heart"  # id da voz (para o nome do arquivo)

# Aliases RVC p/ teste A/B (--rvc): nome curto → (.pth, .index) em ~/models.
RVC_ALIASES: dict[str, tuple[str, str]] = {
    "jarvis": ("Jarvis_300e_infer.pth", "added_Jarvis_v3.index"),
    "klein": ("Klein_400e_infer.pth", "added_Klein_v1.index"),
    "silver": ("Silverhand_500e_14500s_best_epoch.pth", "added_Silverhand_v2.index"),
}

# Base alternativa ao Kokoro: Edge TTS (Microsoft, requer internet).
EDGE_BIN_CANDIDATES = (
    "/tmp/opencode/kvenv/bin/edge-tts",
    os.path.expanduser("~/.local/bin/edge-tts"),
    "edge-tts",
)
EDGE_VOICE_DEFAULT = "pt-BR-AntonioNeural"

# Higiene pré-TTS: markdown que o TTS leria literalmente ("asterisco"...).
TTS_STRIP_RE = r"[*_#`>]"
# Dicionário de pronúncia (regex, case-insensitive) — aplicado antes do TTS.
TTS_PRONUNC = [
    (r"\bBeyonders\b", "Biónders"),
    (r"\bbeyonders\b", "biónders"),
    (r"\bBeyonder\b", "Biónder"),
    (r"\bbeyonder\b", "biónder"),
    (r"\bMoretti\b", "Moréti"),
    (r"\bKhoy\b", "Cói"),
    (r"\bTingen\b", "Tínguem"),
    (r"\bweb novels\b", "web nóvels"),
    (r"\bnovels\b", "nóvels"),
    (r"\bnovel\b", "nóvel"),
    (r"\bUh\b", "Ãh"),
    (r"\buh\b", "ãh"),
    (r"\bmiolos\b", "miólos"),
    (r"\bHehe\b", "Rêrê"),
    (r"\bhehe\b", "rêrê"),
    (r"\.{4,}", "…"),
]
# Notas de rodapé [1] [23]: o Edge lê como "hmm" — remover antes do TTS.
TTS_FOOTNOTE_RE = r"\[\d+\]"


def _clean_tts_text(text: str) -> str:
    """Remove markdown literal e aplica dicionário de pronúncia."""
    import re
    text = re.sub(TTS_STRIP_RE, "", text)
    text = re.sub(TTS_FOOTNOTE_RE, "", text)
    for pat, rep in TTS_PRONUNC:
        text = re.sub(pat, rep, text)
    text = re.sub(r"[ \t]{2,}", " ", text)
    return text.strip()


TTS_CHUNK_MAX = 800  # chars por fatia (Edge/Kokoro truncam texto longo)


def _split_chunks(text: str, limit: int = TTS_CHUNK_MAX) -> list[str]:
    """Fatia texto em frases, sem estourar `limit` chars por fatia."""
    import re
    parts = re.split(r"(?<=[.!?…])\s+", text.strip())
    chunks, cur = [], ""
    for p in parts:
        if len(cur) + len(p) + 1 <= limit:
            cur = (cur + " " + p).strip()
        else:
            if cur:
                chunks.append(cur)
            while len(p) > limit:  # frase gigante: corta duro
                chunks.append(p[:limit])
                p = p[limit:]
            cur = p
    if cur:
        chunks.append(cur)
    return chunks or [text]


def _resolve_rvc(rvc: str | None) -> tuple[str | None, str | None]:
    """Alias|path → (model_path, index_path). (None, None) = env atual."""
    if not rvc:
        return None, None
    home = Path(os.path.expanduser("~/models"))
    if rvc in RVC_ALIASES:
        pth, idx = RVC_ALIASES[rvc]
        return str(home / pth), str(home / idx)
    p = Path(os.path.expanduser(rvc))
    if not p.exists():
        return f"ERROR: modelo RVC não encontrado: {rvc}", None
    stem = p.with_suffix(".index")
    idx = str(stem) if stem.exists() else None
    return str(p), idx


# Style Edge (dono 15/09): mstts:express-as é rejeitado pelo serviço via
# edge-tts (NoAudioReceived) — style aqui = preset de prosódia, que funciona.
STYLE_PROSODY = {
    "angry": {"pitch": "+15Hz", "rate": "-5%"},
    "cheerful": {"pitch": "+20Hz", "rate": "+5%"},
    "sad": {"pitch": "-10Hz", "rate": "-15%"},
    "unfriendly": {"pitch": "-5Hz", "rate": "-8%"},
    "calm": {"pitch": "-5Hz", "rate": "-12%"},
}


def _edge_base_wav(text: str, out_path: Path, voice: str = EDGE_VOICE_DEFAULT,
                   rate: str | None = None, style: str | None = None) -> str:
    """Sintetiza base via Edge TTS. Com style= usa preset de prosódia
    (angry/cheerful/sad/unfriendly/calm); sem style usa texto puro."""
    import subprocess

    mp3 = out_path.with_suffix(".edge.mp3")
    # 1. biblioteca edge_tts (se instalada): falha rápido
    try:
        import asyncio
        import edge_tts

        async def _gen():
            if style and style in STYLE_PROSODY:
                pr = STYLE_PROSODY[style]
                await asyncio.wait_for(
                    edge_tts.Communicate(
                        text, voice, pitch=pr["pitch"],
                        rate=pr["rate"] if rate is None else rate).save(str(mp3)),
                    timeout=60)
            else:
                await asyncio.wait_for(
                    edge_tts.Communicate(text, voice).save(str(mp3)), timeout=60)

        asyncio.run(_gen())
        if mp3.exists():
            pass  # ok, converte abaixo
        else:
            return "ERROR: edge-tts lib nao gerou audio%s" % (" (style=%s)" % style if style else "")
    except Exception as e:
        if style:
            return ("ERROR: edge-tts style falhou: %s" % e)[:150]
        # sem style: cai p/ CLI abaixo
        try:
            mp3.unlink(missing_ok=True)
        except Exception:
            pass
        lib_err = str(e)[:80]
    else:
        lib_err = ""
    if not style and not mp3.exists():
        import shutil
        binary = next((b for b in EDGE_BIN_CANDIDATES
                       if "/" not in b or Path(b).exists()), None)
        if binary is None or ("/" not in binary and shutil.which(binary) is None):
            return "ERROR: edge-tts falhou (%s)" % (lib_err or "sem CLI")
        rstr = "" if rate is None else str(rate)
        if rstr and not rstr.endswith("%"):
            rstr += "%"
        cmd = [binary, "--voice", voice, "--text", text, "--write-media", str(mp3)]
        if rstr:
            cmd += ["--rate", rstr]
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90)
        if r.returncode != 0 or not mp3.exists():
            return f"ERROR: edge-tts falhou: {(r.stderr or '')[:150]}"
    wav = out_path.with_name(out_path.stem + "-edge.wav")
    r2 = subprocess.run(
        ["ffmpeg", "-y", "-v", "error", "-i", str(mp3),
         "-ar", "44100", "-ac", "1", str(wav)],
        capture_output=True, text=True, timeout=120)
    if r2.returncode != 0 or not wav.exists():
        return "ERROR: ffmpeg não converteu base edge"
    return str(wav)

# Voice mapping by language code (Kokoro lang_code → voice file prefix)
# First letter: a=Australian/US English, b=British, j=Japanese, z=Chinese,
#              e=Spanish, f=French, h=Hindi, i=Italian, p=Brazilian Portuguese
VOICE_BY_LANG: dict[str, str] = {
    "a": "af_heart",
    "b": "bf_emma",
    "p": "pm_alex",  # Jarvis é masculino; pf_dora segue via --voice
    "j": "jf_alpha",
    "e": "ef_dora",
    "f": "ff_siwis",
    "h": "hf_alpha",
    "i": "if_sara",
    "z": "zf_xiaoxiao",
}


def _default_lang() -> str:
    """Kokoro lang_code padrão (dinâmico via jarvis.core.lang)."""
    from jarvis.core.lang import tts_code
    return tts_code()


def _detect_lang_code(text: str) -> str:
    """Detect Kokoro lang_code from text content.

    Uses character frequency heuristics:
    - PT-BR: high count of ã, ç, é, ê, ó, õ, á, à, â, ù, ~
    - Japanese: high count of hiragana/katakana
    - Chinese: high count of CJK
    - Default: system LANG (PT-BR → 'p', else English 'a')

    Override: JARVIS_TTS_LANG (pt|en|auto) — o daemon exporta o ackLang,
    que é a verdade declarada do usuário. Sem isso, sistema en_US + resposta
    sem acentos caía em af_heart enquanto o ack era pm_alex (forense 2026-09).
    """
    forced = (os.environ.get("JARVIS_TTS_LANG", "auto") or "auto").lower()
    if forced != "auto":
        mapped = {"pt": "p", "en": "a"}.get(forced, forced)
        if mapped in VOICE_BY_LANG:
            return mapped
    if len(text) < 10:
        return _default_lang()
    sample = text[:5000]  # Check first 5000 chars
    pt_chars = sum(1 for c in sample if c in 'ãçéêóõáàâúÃÇÉÊÓÕÁÀÂÚ')
    ja_chars = sum(1 for c in sample if '\u3040' <= c <= '\u309f' or '\u30a0' <= c <= '\u30ff')
    zh_chars = sum(1 for c in sample if '\u4e00' <= c <= '\u9fff')
    total = len(sample)
    if pt_chars / max(total, 1) > 0.005:
        return "p"
    if ja_chars / max(total, 1) > 0.01:
        return "j"
    if zh_chars / max(total, 1) > 0.01:
        return "z"
    return _default_lang()


def _voice_for_lang(lang_code: str, voice_override: str | None = None) -> str:
    """Resolve voice file path for a given language code."""
    if voice_override:
        return os.path.expanduser(voice_override)
    voice_id = VOICE_BY_LANG.get(lang_code, "af_heart")
    voice_path = os.path.expanduser(f"~/.local/share/kokoro/voices/{voice_id}.pt")
    if not Path(voice_path).exists():
        # Fallback to default voice
        return os.path.expanduser(KOKORO_VOICE_DEFAULT)
    return voice_path


def _model_dir() -> str:
    return os.path.expanduser(os.environ.get("JARVIS_VOICE_DIR", MODEL_DIR_DEFAULT))


def _trim_silence(audio, sr: int, thresh_ratio: float = 0.05, pad_s: float = 0.05):
    """Corta silêncio das bordas (Kokoro adiciona ~0.2s em cada ponta).

    Em clips curtos (acks de 1.6s) 25% de silêncio soa arrastado/drogado.
    """
    import numpy as np
    if len(audio) == 0:
        return audio
    mono = audio.mean(axis=1) if getattr(audio, "ndim", 1) > 1 else audio
    win = max(1, int(sr * 0.02))
    rms = [float((mono[i:i + win] ** 2).mean() ** 0.5)
           for i in range(0, len(mono) - win + 1, win)]
    if not rms:
        return audio
    peak = max(rms)
    if peak <= 0:
        return audio
    thr = peak * thresh_ratio
    start = next((i for i, r in enumerate(rms) if r > thr), 0)
    end = next((i for i, r in enumerate(reversed(rms)) if r > thr), 0)
    pad = int(pad_s * sr / (win or 1))
    s0 = max(0, (start - pad) * win)
    s1 = min(len(audio), len(audio) - (end - pad) * win)
    return audio[s0:s1] if s1 > s0 else audio


# Cache de pipelines Kokoro por (config, model, lang): carregar o modelo
# custa ~3.4s — em batch (audiobook) o reuso economiza horas.
_PIPELINES: dict[tuple[str, str, str], tuple[object, object]] = {}


def _get_pipeline(config_path: str, model_path: str, lang_code: str):
    """Retorna (kmodel, pipeline) cacheados por chave."""
    from kokoro import KModel, KPipeline  # type: ignore[import-not-found]
    key = (config_path, model_path, lang_code)
    hit = _PIPELINES.get(key)
    if hit is None:
        kmodel = KModel(config=config_path, model=model_path)
        hit = (kmodel, KPipeline(lang_code=lang_code, model=kmodel, trf=False))
        _PIPELINES[key] = hit
    return hit


def _split_chunks(text: str, max_chars: int = 600) -> list[str]:
    """Divide texto em chunks por fronteira de sentença (pura, testável)."""
    import re
    sentences = re.split(r"(?<=[.!?…:;])\s+", text.strip())
    chunks: list[str] = []
    current = ""
    for sentence in sentences:
        if not sentence.strip():
            continue
        probe = f"{current} {sentence}".strip()
        if current and len(probe) > max_chars:
            chunks.append(current.strip())
            current = sentence
        else:
            current = probe
    if current.strip():
        chunks.append(current.strip())
    # Sentença gigante isolada: corta duro
    hard: list[str] = []
    for chunk in chunks:
        while len(chunk) > max_chars:
            hard.append(chunk[:max_chars])
            chunk = chunk[max_chars:]
        if chunk:
            hard.append(chunk)
    return hard or ([text.strip()] if text.strip() else [])


# ---------------------------------------------------------------------------
# Instrumentação / observabilidade (forense 2026-09)
# ---------------------------------------------------------------------------

def _strip_wakewords(text: str) -> str:
    """Remove o wakeword do texto transcrito ("hey jarvis, ..." → "...").

    O VAD captura o wake junto do comando; sem strip, o router tenta lidar
    com "hey jarvis" como parte do pedido e a resposta não tem nada a ver
    (forense 2026-09, ao vivo).
    """
    import re
    t = text.strip()
    t = re.sub(r"^(hey[,\s]+jarvis|ei[,\s]+jarvis|jarvis)[,\s.!?;:]+", "", t, flags=re.I)
    t = re.sub(r"[,\s.!?;:]+(hey[,\s]+jarvis|ei[,\s]+jarvis)[.!?]*$", "", t, flags=re.I)
    return t.strip() or text.strip()


def _tts_short(text: str, max_chars: int = 500) -> str:
    """Corta resposta p/ TTS na fronteira de sentença (primeira frase responde).

    Voz é unidirecional (não dá p/ "skim"): resposta longa falada = espera
    longa percebida (Siri pattern, CHI 2022). O texto completo vai no notify.
    """
    import re
    t = text.strip()
    if len(t) <= max_chars:
        return t
    sentences = re.split(r"(?<=[.!?…])\s+", t)
    out = ""
    for s in sentences:
        probe = f"{out} {s}".strip()
        if out and len(probe) > max_chars:
            break
        out = probe
    return (out or t[:max_chars]).strip() + "…"


def _audio_stats(path: str) -> dict[str, Any]:
    """Métricas do WAV (sem conteúdo sensível): formato + níveis."""
    import array
    import math
    import wave
    try:
        w = wave.open(path, "rb")
        n = w.getnframes()
        ch = w.getnchannels()
        rate = w.getframerate()
        sw = w.getsampwidth()
        raw = w.readframes(n)
        w.close()
        duration = n / rate if rate else 0.0
        stats: dict[str, Any] = {
            "channels": ch,
            "sample_rate": rate,
            "frames": n,
            "duration_s": round(duration, 3),
            "bytes": len(raw),
        }
        if sw == 2 and raw:
            a = array.array("h")
            a.frombytes(raw)
            if ch > 1:
                mono = [sum(a[i * ch:(i + 1) * ch]) / ch for i in range(n)]
            else:
                mono = list(a)
            if mono:
                peak = max(abs(int(v)) for v in mono)
                rms = math.sqrt(sum(float(v) ** 2 for v in mono) / len(mono))
                stats["peak"] = int(peak)
                stats["rms_mean"] = round(rms, 1)
        return stats
    except Exception as exc:  # noqa: BLE001 — diagnóstico nunca quebra o fluxo
        return {"error": str(exc)[:100]}


def _write_debug_wav(src_wav: str, debug_dir: str, meta: dict[str, Any]) -> str:
    """Copia o WAV p/ DIR de debug + session.json (modo explícito, fora do fluxo)."""
    import json
    import shutil
    import time
    dest = Path(debug_dir)
    dest.mkdir(parents=True, exist_ok=True)
    tag = time.strftime("%Y%m%d-%H%M%S")
    wav_dest = dest / f"voice-debug-{tag}.wav"
    try:
        shutil.copyfile(src_wav, wav_dest)
    except OSError as exc:
        return f"ERROR: debug copy falhou: {exc}"
    meta = {"ts": time.time(), "src": src_wav, "wav": str(wav_dest), **meta}
    try:
        (dest / f"voice-debug-{tag}.json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2)
        )
    except OSError as exc:
        return f"ERROR: debug json falhou: {exc}"
    return str(wav_dest)


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

    if language is None:
        from jarvis.core.lang import stt_code
        language = stt_code()

    try:
        model_dir = _model_dir()
        model = WhisperModel(model_size, device="cpu", compute_type="int8", download_root=model_dir)
        segments, _info = model.transcribe(
            audio_path,
            beam_size=3,
            language=language,
            # condition_on_previous_text=False: evita loops de alucinação
            # ("AJRs AJRs") entre segmentos (doc faster-whisper; forense 2026-09).
            condition_on_previous_text=False,
            # Seed curta com o wake: melhora nomes próprios do domínio.
            initial_prompt="Hey Jarvis.",
            vad_filter=True,
            vad_parameters=dict(
                threshold=0.5,
                min_speech_duration_ms=250,
                min_silence_duration_ms=1000,
                speech_pad_ms=400,
            ),
        )
        texts: list[str] = []
        lp_sum, ch_sum = 0.0, 0
        for seg in segments:
            texts.append(seg.text)
            lp_sum += getattr(seg, "avg_logprob", 0.0) * len(seg.text)
            ch_sum += len(seg.text)
        text = " ".join(texts).strip()
        if text and ch_sum and lp_sum / ch_sum < STT_MIN_CONFIDENCE:
            print(f"STT baixa confiança ({lp_sum / ch_sum:.2f}), descartando",
                  file=sys.stderr)
            return ""
        return text
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


CLONE_SPEED_FACTOR = 1.0  # neutro: RVC preserva o ritmo; receita validada (rvc-jarvis-10s.wav) sem slowdown

def speak(
    text: str,
    voice: str | None = None,
    *,
    play: bool = True,
    clone: bool = False,
    speed: float | None = None,
    pitch: int | None = None,
    base: str | None = None,
    rvc: str | None = None,
    rvc_index: str | None = None,
    keep_wav: bool = False,
    rate: str | None = None,
    index_rate: float = 0.75,
    f0_method: str = "rmvpe",
    style: str | None = None,
) -> str:
    """Sintetiza `text` (Kokoro local ou Edge Antonio) e (opcionalmente) toca.

    Texto longo é fatiado em frases (limite ~800 chars/fatia) e concatenado —
    nem Kokoro nem Edge entregam texto longo num request só.
    Com clone=True, pós-processa o WAV via RVC (jarvis.core.voice_clone).
    Sem keep_wav, os WAVs são apagados após tocar (só --no-play mantém).
    Retorna o path do WAV gerado ou mensagem ERROR:.
    """
    text = _clean_tts_text(text)
    if base is None:
        base = os.environ.get("JARVIS_TTS_BASE", "antonio")
    use_edge_early = base == "antonio"
    if not use_edge_early:
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
        use_edge = base == "antonio"
        kmodel, pipeline = (None, None)
        if not use_edge:
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
            # Auto-detect language from text content
            lang_code = _detect_lang_code(text)
            voice_path = _voice_for_lang(lang_code, voice)
            kmodel, pipeline = _get_pipeline(config_path, model_path, lang_code)
        else:
            voice_path, lang_code = voice, "p"
        out_dir = Path(_model_dir()) / "tts"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_path = out_dir / f"jarvis_tts_{abs(hash((text, voice, speed, base, rate, style))) % 10**9}.wav"

        # Texto longo: fatia em frases e concatena (nenhuma base entrega tudo).
        slices = _split_chunks(text)
        base_sr = 44100 if use_edge else 24000
        base_parts: list[Path] = []
        try:
            for i, part in enumerate(slices):
                part_path = out_dir / f"{out_path.stem}-p{i}.wav"
                if use_edge:
                    edge_wav = _edge_base_wav(part, part_path, rate=rate, style=style)
                    if edge_wav.startswith("ERROR"):
                        if use_edge_early:
                            return edge_wav  # sem kokoro aqui; falha limpa p/ retry
                        print(f"[speak] edge falhou ({edge_wav[:80]}), fallback kokoro", flush=True)
                        use_edge = False
                        _, pipeline = _get_pipeline(config_path, model_path, lang_code)
                    else:
                        base_parts.append(Path(edge_wav))
                        continue
                if not use_edge:
                    if speed is None:
                        # Auto-emoção clampada (forense 2026-09). --speed passa direto.
                        speed = min(1.05, max(0.95, speed_for(text)))
                        if clone:
                            speed *= CLONE_SPEED_FACTOR
                    chunks = []
                    for _result in pipeline(part, voice=voice_path, speed=speed):
                        chunks.append(_result.audio)
                    if not chunks:
                        return "ERROR: kokoro não gerou áudio"
                    audio = np.concatenate(chunks)
                    sf.write(str(part_path), audio, 24000)
                    base_parts.append(part_path)
            if not base_parts:
                return "ERROR: nenhuma base gerada"
            if len(base_parts) == 1:
                base_parts[0].replace(out_path)
            else:
                import numpy as _np
                import soundfile as _sf
                arrays = []
                for bp in base_parts:
                    data, _ = _sf.read(str(bp))
                    arrays.append(data)
                _sf.write(str(out_path), _np.concatenate(arrays), base_sr)
        finally:
            for bp in base_parts:
                if bp != out_path and bp.exists():
                    bp.unlink(missing_ok=True)

        if clone:
            from jarvis.core.voice_clone import clone_wav
            model_path, index_path = _resolve_rvc(rvc)
            if model_path and model_path.startswith("ERROR"):
                return model_path
            base_for_clone = str(out_path)
            cloned = clone_wav(base_for_clone, pitch=pitch,
                               model_path=model_path,
                               index_path=rvc_index or index_path)
            if cloned.startswith("ERROR"):
                print(f"[speak] RVC/GPU falhou ({cloned[:100]}), tentando CPU", flush=True)
                cloned = clone_wav(base_for_clone, pitch=pitch, cpu_only=True,
                                   model_path=model_path,
                                   index_path=rvc_index or index_path)
            if cloned.startswith("ERROR"):
                return cloned
            out_path = Path(cloned)
            if not keep_wav:
                Path(base_for_clone).unlink(missing_ok=True)

        # Publish to Event Bus
        try:
            from jarvis.core.eventbus import get_bus
            get_bus().publish("voice.tts", {
                "text_len": len(text),
                "path": str(out_path),
                "played": play,
                "cloned": clone,
            })
        except Exception:  # noqa: BLE001
            pass

        if play:
            # Sinaliza speaking ANTES de tocar: o daemon wakeword mata
            # players no trigger (killTTS) e o próprio TTS no alto-falante
            # dispara o VAD → sem o sinal, ele corta a fala no meio.
            # (O brain já sinalizava; o CLI não — corte reportado 2026-09.)
            try:
                from jarvis.core.feedback import set_status as _set_spk
                _set_spk("speaking", text[:60])
            except Exception:
                pass
            try:
                _play(str(out_path))
            finally:
                try:
                    from jarvis.core.feedback import set_status as _set_idle
                    _set_idle("idle", "")
                except Exception:
                    pass
            if not keep_wav:
                # Tocou: some com o WAV (só --no-play mantém arquivo).
                Path(out_path).unlink(missing_ok=True)
                return "OK (played, wav removido)"
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

def voice_loop(audio_path: str, *, tts: bool = True, model_size: str = STT_MODEL_DEFAULT,
               debug_wav: str | None = None, clone: bool = False) -> int:
    """Pipeline completo para o brainCommand do wakeword.

    STT do WAV capturado → load check → roteia o pedido → TTS da resposta.
    Tolerante: cada etapa degrada sem quebrar as seguintes.

    Load shedding: se o LLM está sobrecarregado (todos os slots ocupados ou
    contexto >80%), retorna resposta busy via TTS sem tentar o LLM — evita
    sobrecarregar ainda mais e dá feedback imediato ao usuário.
    """
    import faulthandler
    faulthandler.enable()
    from jarvis.core.busy import check_load, handle_busy
    from jarvis.core.feedback import set_status
    from jarvis.core.logging import get_logger
    from jarvis.core.router import (
        handle_agent, handle_doctor, handle_fastpath, handle_nixos, handle_rag, route_request,
    )

    log = get_logger("voice")

    import time as _time
    _t_session = _time.time()
    _audio_meta = _audio_stats(audio_path)

    # 1. STT — via subprocess para isolar CTranslate2/torch de Kokoro/torch
    #    (CTranslate2 + Kokoro no mesmo processo causa Floating-point exception)
    set_status("transcribing", "Transcrevendo...")
    try:
        import shutil as _shutil
        _stt_bin = _shutil.which("jarvis") or "jarvis"
        _stt_cmd = [_stt_bin, "stt", "--model", model_size, audio_path]
        from jarvis.core.lang import stt_code as _stt_lang
        _stt_cmd += ["--language", _stt_lang() or "pt"]
        _stt_proc = subprocess.run(_stt_cmd, capture_output=True, text=True, timeout=60)
        text = (_stt_proc.stdout or "").strip()
        if _stt_proc.returncode != 0:
            stderr_out = (_stt_proc.stderr or "")[:200]
            set_status("error", f"STT falhou: {stderr_out[:60]}")
            print(f"ERROR: STT falhou (exit {_stt_proc.returncode}): {stderr_out}", file=sys.stderr)
            try:
                from jarvis.core.feedback import notify as _nfail, play_sound as _psnd
                _nfail("Jarvis", "Falha ao transcrever o áudio")
                _psnd("error")
            except Exception:
                pass
            return 1
        if not text:
            # Vazio (só ruído/VAD comeu tudo): volta a idle SEM erro —
            # follow-up em ambiente ruidoso gera isso direto (forense 2026-09).
            # rc=2: daemon NÃO estende follow-up (senão loop infinito).
            set_status("idle", "")
            print("(voz vazia)", file=sys.stderr)
            return 2
    except subprocess.TimeoutExpired:
        set_status("error", "STT timeout")
        print("ERROR: STT timeout (60s)", file=sys.stderr)
        try:
            from jarvis.core.feedback import notify as _nfail2, play_sound as _psnd2
            _nfail2("Jarvis", "STT demorou demais (timeout)")
            _psnd2("error")
        except Exception:
            pass
        return 1
    except Exception as exc:
        set_status("error", str(exc)[:80])
        print(f"ERROR: STT exceção: {exc}", file=sys.stderr)
        return 1
    if not text:
        set_status("idle", "")
        print("(voz vazia)", file=sys.stderr)
        return 0

    print(f"🎤 {text}", flush=True)
    _t_stt_done = _time.time()
    # Só wakeword, sem comando: o ack do confirm já cobriu. Sem turno LLM.
    # rc=2: daemon NÃO estende follow-up.
    if text.lower().strip().rstrip(".!,?;: ") in ("hey jarvis", "ei jarvis", "jarvis"):
        set_status("idle", "")
        print("(só wakeword, sem comando)", file=sys.stderr)
        return 2
    text = _strip_wakewords(text)
    if not text:
        set_status("idle", "")
        print("(só wakeword, sem comando)", file=sys.stderr)
        return 0
    _dbg: dict[str, Any] = {
        "audio": _audio_meta,
        "model_size": model_size,
        "clone": clone,
        "stt_s": round(_t_stt_done - _t_session, 3),
        "text_chars": len(text),
        "text": text[:200],
    }
    try:
        from jarvis.core.feedback import notify as _notify
        _notify("Jarvis ouviu", text[:120])
    except Exception:
        pass

    # 2. Roteamento
    _t_route = _time.time()
    route = route_request(text)
    _dbg["route"] = route.handler
    _dbg["route_s"] = round(_time.time() - _t_route, 3)
    try:
        from jarvis.core.feedback import notify as _notify2
        _notify2(f"Rota: {route.handler}", route.query[:120])
    except Exception:
        pass

    # 3. Load shedding — verifica carga ANTES de chamar o LLM
    #    Rotas que NÃO usam LLM (fastpath, doctor, nixos, rag) passam direto.
    #    Forense 2026-09: shed imediato perdia o turno quando o slot único
    #    estava ocupado por outra sessão (opencode/Roo). Espera até 25s.
    needs_llm = route.handler in ("agent",)
    if needs_llm:
        from jarvis.providers.llm import LLMClient
        from jarvis.core.config import get_config
        llm = LLMClient(get_config())
        load = check_load(llm)
        if load["busy"]:
            import time as _wt
            _deadline = _wt.time() + 25
            set_status("busy", "Aguardando modelo liberar…")
            while load["busy"] and _wt.time() < _deadline:
                _wt.sleep(2)
                load = check_load(llm)
        if load["busy"]:
            log.warn("voice_load_shed", detail={
                "reason": load["reason"],
                "text": text[:100],
            })
            return handle_busy(load, tts=tts)

    # 4. Executa a rota
    set_status("thinking", f"{route.handler}: {text[:40]}")
    _t_llm = _time.time()
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
            # Modo voz usa persona "agent" (terse, falável) — distinta do
            # modo texto, como todo agent comercial tem.
            out = handle_agent(route.query, persona_id="agent")
    except Exception as exc:  # noqa: BLE001
        set_status("error", str(exc)[:80])
        print(f"ERROR: rota '{route.handler}' falhou: {exc}", file=sys.stderr)
        return 1

    # 5. TTS — primeira frase é a resposta (Siri pattern: voz é unidirecional,
    #    parágrafo longo = espera longa; forense 2026-09). Texto completo no notify.
    answer = _text_for_tts(out)
    _dbg["llm_s"] = round(_time.time() - _t_llm, 3)
    _dbg["answer_chars"] = len(answer)
    set_status("speaking", answer[:60])
    _t_tts = _time.time()
    if tts:
        wav = speak(_tts_short(answer), clone=clone)
        if clone and wav.startswith("ERROR"):
            # Spike RVC efêmero (/tmp): sem ele, responde com Kokoro puro
            # em vez de silêncio (forense 2026-09).
            print(f"[voice] clone indisponível, fallback p/ TTS puro: {wav[:100]}", flush=True)
            wav = speak(_tts_short(answer), clone=False)
        print(f"🔊 {answer}", flush=True)
        try:
            from jarvis.core.feedback import notify as _notify3
            _notify3("Jarvis responde", answer[:300])
        except Exception:
            pass
        if wav.startswith("ERROR"):
            print(wav, file=sys.stderr)
    else:
        print(f"💬 {answer}", flush=True)

    if debug_wav:
        _dbg["tts_s"] = round(_time.time() - _t_tts, 3)
        _dbg["total_s"] = round(_time.time() - _t_session, 3)
        _write_debug_wav(audio_path, debug_wav, _dbg)

    set_status("done", "")
    return 0


def main_voice(argv: list[str] | None = None) -> int:
    """Entry point CLI: jarvis voice <wav> [--no-tts]."""
    import argparse

    parser = argparse.ArgumentParser(prog="jarvis voice", description="STT → roteador → TTS a partir de um WAV")
    parser.add_argument("wav", help="arquivo de áudio capturado pelo wakeword")
    parser.add_argument("--no-tts", action="store_true", help="não sintetizar resposta em voz")
    parser.add_argument("--model", default=STT_MODEL_DEFAULT, help="tamanho do modelo faster-whisper")
    parser.add_argument("--debug-wav", default=None, help="dir p/ salvar WAV + session.json de diagnóstico")
    parser.add_argument("--clone", action="store_true", help="converte resposta p/ timbre RVC (~+20s; exige envs do spike)")
    args = parser.parse_args(argv)

    if not Path(args.wav).exists():
        print(f"ERROR: arquivo não existe: {args.wav}", file=sys.stderr)
        return 1
    return voice_loop(args.wav, tts=not args.no_tts, model_size=args.model,
                      debug_wav=args.debug_wav, clone=args.clone)


def main_stt(argv: list[str] | None = None) -> int:
    """Entry point CLI: jarvis stt <wav> [--model small]."""
    import argparse

    parser = argparse.ArgumentParser(prog="jarvis stt", description="Transcreve um WAV (faster-whisper)")
    parser.add_argument("wav", help="arquivo de áudio")
    parser.add_argument("--model", default=STT_MODEL_DEFAULT, help="tamanho do modelo")
    parser.add_argument("--language", default=None, help="hint de idioma (ex: pt)")
    parser.add_argument("--debug-wav", default=None, help="dir p/ salvar WAV + session.json de diagnóstico")
    args = parser.parse_args(argv)

    if not Path(args.wav).exists():
        print(f"ERROR: arquivo não existe: {args.wav}", file=sys.stderr)
        return 1
    import time as _time
    _t0 = _time.time()
    text = transcribe(args.wav, model_size=args.model, language=args.language)
    if args.debug_wav:
        _write_debug_wav(args.wav, args.debug_wav, {
            "audio": _audio_stats(args.wav),
            "model_size": args.model,
            "language": args.language,
            "stt_s": round(_time.time() - _t0, 3),
            "text_chars": len(text),
        })
    print(text)
    return 0 if not text.startswith("ERROR") else 1


def main_tts(argv: list[str] | None = None) -> int:
    """Entry point CLI: jarvis speak <texto> [--voice af_heart] [--no-play] [--clone]."""
    import argparse

    parser = argparse.ArgumentParser(prog="jarvis speak", description="Sintetiza texto com Kokoro (TTS)")
    parser.add_argument("text", help="texto a falar")
    parser.add_argument("--voice", default=None, help="id da voz Kokoro (ex: af_heart, pf_dora, pm_alex); vazio = auto por idioma")
    parser.add_argument("--no-play", action="store_true", help="gera WAV sem tocar (mantém arquivo; sem ele, toca e apaga)")
    parser.add_argument("--clone", action="store_true", help="converte p/ timbre RVC (JARVIS_VOICE_CLONE_MODEL)")
    parser.add_argument("--speed", type=float, default=None, help="velocidade base Kokoro (padrão: emoção; clone aplica ×0.9)")
    parser.add_argument("--pitch", type=int, default=None, help="semitons RVC (-12..12; default 0 = neutro)")
    parser.add_argument("--base", default=None, choices=["kokoro", "antonio"],
                        help="voz base: kokoro (local) ou antonio (Edge TTS, jovem)")
    parser.add_argument("--rvc", default=None,
                        help="timbre RVC: jarvis|klein|silver, path .pth, ou vazio = env atual")
    parser.add_argument("--rvc-index", default=None, help="index .index (só com --rvc=path)")
    parser.add_argument("--rate", default=None, help="velocidade Edge (ex: -10; use =, ex: --rate=-10; só base antonio)")
    parser.add_argument("--style", default=None, help="estilo Edge mstts (cheerful/sad/angry/unfriendly; só base antonio)")
    args = parser.parse_args(argv)

    # id da voz → path (mesmo diretório do modelo, voices/<id>.pt).
    # Sem --voice: None → speak() decide pelo idioma (VOICE_BY_LANG).
    voice_path: str | None = None
    if args.voice:
        if Path(args.voice).exists():
            voice_path = args.voice
        else:
            voice_dir = Path(os.path.expanduser(KOKORO_VOICE_DEFAULT)).parent
            candidate = voice_dir / f"{args.voice}.pt"
            voice_path = str(candidate) if candidate.exists() else args.voice

    out = speak(args.text, voice=voice_path, play=not args.no_play, clone=args.clone, speed=args.speed, pitch=args.pitch,
                base=args.base, rvc=args.rvc, rvc_index=args.rvc_index, keep_wav=args.no_play, rate=args.rate, style=args.style)
    print(out)
    return 0 if not out.startswith("ERROR") else 1


if __name__ == "__main__":
    raise SystemExit(main_voice())

# ═══ IMPORTANT: How to use TTS ═══
# from jarvis.core.voice import speak
# result = speak('texto em português ou inglês')
# result returns path to WAV file
# Audio plays automatically via pw-play → mpv → paplay fallback
# Language auto-detected: PT-BR if accented chars found
# Voice: Kokoro-82M (pf_dora for PT-BR, af_heart for EN)
