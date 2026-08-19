"""Interfaces dos providers de voz.

Contratos mínimos para as fases de percepção/resposta (wakeword, STT,
TTS). Sem implementação aqui — as implementações chegam com os pacotes
(openwakeword, faster-whisper, kokoro-onnx) nas fases 8 e 9.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path


class STTProvider(ABC):
    """Speech-to-Text. Transcreve um arquivo de áudio para texto."""

    @abstractmethod
    def transcribe(self, audio_path: Path, *, language: str = "pt") -> str:
        ...


class TTSProvider(ABC):
    """Text-to-Speech. Gera áudio a partir de texto (retorna bytes wav)."""

    @abstractmethod
    def synthesize(self, text: str, *, voice: str, speed: float, language: str) -> bytes:
        ...


class WakewordProvider(ABC):
    """Detecção contínua de wake word em stream de áudio."""

    @abstractmethod
    def feed(self, audio_chunk: bytes) -> float:
        """Recebe um chunk PCM e retorna o score da wake word (0..1)."""
        ...
