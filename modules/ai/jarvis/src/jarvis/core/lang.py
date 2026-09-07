"""Idioma do usuário como dado, não hardcode.

JARVIS_LANG: pt (default, perfil BR) | en | auto (segue LANG do sistema).
Derivados: stt_code() p/ Whisper, tts_code() p/ Kokoro, name() p/ prompts.
"""

from __future__ import annotations

import os

_TTS_MAP = {"pt": "p", "en": "a", "ja": "j", "zh": "z", "es": "e", "fr": "f"}


def lang() -> str:
    """Código do idioma (pt|en|...)."""
    forced = (os.environ.get("JARVIS_LANG", "") or "").lower()
    if forced and forced != "auto":
        return forced
    sys_lang = (os.environ.get("LANG", "") + os.environ.get("LC_ALL", "")).lower()
    if sys_lang.startswith("pt"):
        return "pt"
    if sys_lang[:2].isalpha() and not sys_lang.startswith("c."):
        return sys_lang[:2]
    return "pt"  # perfil do usuário é BR (AGENTS.md)


def name() -> str:
    """Nome p/ prompts: 'português (PT-BR)' | 'English' | ..."""
    return {"pt": "português (PT-BR)", "en": "English"}.get(lang(), lang())


def stt_code() -> str | None:
    """Hint de idioma p/ faster-whisper (None = autodetect)."""
    return lang()


def tts_code() -> str:
    """lang_code Kokoro."""
    return _TTS_MAP.get(lang(), "a")
