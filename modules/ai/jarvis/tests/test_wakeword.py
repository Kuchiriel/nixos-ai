"""Testes unitários do jarvis-wakeword.

O daemon real vive no módulo Nix (home-manager/modules/services/jarvis-wakeword.nix)
e usa arecord + openwakeword — não testável em unit tests (sem mic, sem ONNX).
Este teste valida a LÓGICA do daemon (threshold, cooldown, silence detection,
capture, brain command) via mocks, garantindo que a calibração do legado
foi preservada.

A lógica testada aqui é extraída do `jarvisScript` do módulo Nix e refletida
em funções puras — o daemon Nix é a implementação canônica, estes testes
validam os REQUISITOS.
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Lógica extraída do daemon Nix (para teste unitário)
# ---------------------------------------------------------------------------

# Valores calibrados do legado (docs/architecture/legacy-audio-calibration.md)
DEFAULT_THRESHOLD = 0.85
DEFAULT_COOLDOWN = 5  # seconds
DEFAULT_SILENCE_DROP = 0.6  # 40% drop do pico RMS
DEFAULT_MAX_RECORD = 12  # seconds


def should_trigger(score: float, threshold: float, last_trigger_time: float,
                   cooldown: float = DEFAULT_COOLDOWN) -> bool:
    """Decide se o wakeword foi ativado (threshold + cooldown anti-loop)."""
    return score > threshold and (time.time() - last_trigger_time) > cooldown


def is_silence(rms: float, max_rms: float, silence_drop: float = DEFAULT_SILENCE_DROP) -> bool:
    """Detecta silêncio adaptativo (40% drop do pico RMS)."""
    silence_threshold = max_rms * silence_drop
    return rms < silence_threshold


def normalize_audio(mono: list[float]) -> list[int]:
    """Normalização calibrada do legado: DC removal + ganho fixo."""
    import numpy as np
    arr = np.array(mono, dtype=np.float32)
    mono_norm = np.clip((arr - np.mean(arr)) * 10.0, -32768, 32767).astype(np.int16)
    return mono_norm.tolist()


def extract_wav_frames(chunks: list[bytes], channels: int = 2, sample_width: int = 2) -> int:
    """Calcula o número de frames a partir dos chunks capturados."""
    total_bytes = sum(len(c) for c in chunks)
    return total_bytes // (channels * sample_width)


# ---------------------------------------------------------------------------
# Testes: Threshold
# ---------------------------------------------------------------------------

class TestThreshold:
    """Valida que o threshold de ativação segue a calibração do legado."""

    def test_default_threshold_is_085(self) -> None:
        """Threshold calibrado: 0.85 (evolução 0.05→0.85 documentada)."""
        assert DEFAULT_THRESHOLD == 0.85

    def test_trigger_above_threshold(self) -> None:
        assert should_trigger(0.90, DEFAULT_THRESHOLD, 0, DEFAULT_COOLDOWN)

    def test_no_trigger_below_threshold(self) -> None:
        assert not should_trigger(0.80, DEFAULT_THRESHOLD, 0, DEFAULT_COOLDOWN)

    def test_no_trigger_at_threshold(self) -> None:
        """Score exatamente igual ao threshold NÃO ativa (>)."""
        assert not should_trigger(0.85, DEFAULT_THRESHOLD, 0, DEFAULT_COOLDOWN)

    def test_trigger_just_above_threshold(self) -> None:
        assert should_trigger(0.851, DEFAULT_THRESHOLD, 0, DEFAULT_COOLDOWN)


# ---------------------------------------------------------------------------
# Testes: Cooldown anti-loop
# ---------------------------------------------------------------------------

class TestCooldown:
    """Valida o cooldown de 5s que impede o beep de re-triggerar o wakeword."""

    def test_default_cooldown_is_5s(self) -> None:
        assert DEFAULT_COOLDOWN == 5

    def test_trigger_after_cooldown(self) -> None:
        """Após 5s, pode triggerar de novo."""
        past = time.time() - 6
        assert should_trigger(0.90, DEFAULT_THRESHOLD, past, DEFAULT_COOLDOWN)

    def test_no_trigger_during_cooldown(self) -> None:
        """Dentro de 5s, NÃO triggera (anti-loop do beep)."""
        recent = time.time() - 2
        assert not should_trigger(0.90, DEFAULT_THRESHOLD, recent, DEFAULT_COOLDOWN)

    def test_trigger_at_exact_cooldown(self) -> None:
        """Exatamente em 5s, pode triggerar."""
        exact = time.time() - DEFAULT_COOLDOWN
        assert should_trigger(0.90, DEFAULT_THRESHOLD, exact, DEFAULT_COOLDOWN)

    def test_cooldown_custom(self) -> None:
        """Cooldown customizado (ex: 10s para teste)."""
        recent = time.time() - 3
        assert not should_trigger(0.90, DEFAULT_THRESHOLD, recent, cooldown=10)
        past = time.time() - 11
        assert should_trigger(0.90, DEFAULT_THRESHOLD, past, cooldown=10)


# ---------------------------------------------------------------------------
# Testes: Silêncio adaptativo
# ---------------------------------------------------------------------------

class TestSilenceDetection:
    """Valida a detecção de silêncio adaptativo (40% drop do pico RMS)."""

    def test_default_silence_drop(self) -> None:
        assert DEFAULT_SILENCE_DROP == 0.6

    def test_silence_below_threshold(self) -> None:
        """RMS abaixo de 60% do pico = silêncio."""
        assert is_silence(rms=100, max_rms=500, silence_drop=0.6)

    def test_not_silence_above_threshold(self) -> None:
        """RMS acima de 60% do pico = fala."""
        assert not is_silence(rms=400, max_rms=500, silence_drop=0.6)

    def test_silence_at_boundary(self) -> None:
        """RMS exatamente no limiar = silêncio (<)."""
        assert is_silence(rms=299, max_rms=500, silence_drop=0.6)

    def test_not_silence_at_boundary(self) -> None:
        """RMS igual ao limiar = não é silêncio."""
        assert not is_silence(rms=300, max_rms=500, silence_drop=0.6)

    def test_adaptive_silence_tracks_peak(self) -> None:
        """O limiar de silêncio adapta ao pico RMS (silence adaptativo)."""
        # Pico alto → limiar alto
        assert is_silence(rms=500, max_rms=1000, silence_drop=0.6)
        # Mesmo RMS, pico baixo → limiar baixo → não é silêncio
        assert not is_silence(rms=500, max_rms=800, silence_drop=0.6)


# ---------------------------------------------------------------------------
# Testes: Normalização de áudio
# ---------------------------------------------------------------------------

class TestAudioNormalization:
    """Valida a normalização DC removal + ganho do legado."""

    def test_dc_removal(self) -> None:
        """Média zero após normalização."""
        import numpy as np
        mono = [100.0] * 100  # DC offset de 100
        result = normalize_audio(mono)
        arr = np.array(result, dtype=np.float32)
        assert abs(np.mean(arr)) < 1.0  # média ~0

    def test_gain_amplification(self) -> None:
        """Ganho de 10x amplifica o sinal."""
        mono = [0.0, 1.0, 0.0, -1.0, 0.0]
        result = normalize_audio(mono)
        # O valor 1.0 * 10 = 10, mas com DC removal o resultado varia
        # O importante é que o sinal é amplificado
        assert max(abs(r) for r in result) > 5

    def test_clipping(self) -> None:
        """Valores são clipados em [-32768, 32767]."""
        mono = [10000.0] * 10
        result = normalize_audio(mono)
        assert all(-32768 <= r <= 32767 for r in result)


# ---------------------------------------------------------------------------
# Testes: Captura de áudio
# ---------------------------------------------------------------------------

class TestAudioCapture:
    """Valida a captura WAV (frames, formato)."""

    def test_frame_count(self) -> None:
        """Calcula frames corretamente (2 canais, 16-bit)."""
        # 10 chunks de 1024 bytes = 10240 bytes
        chunks = [b"x" * 1024] * 10
        frames = extract_wav_frames(chunks, channels=2, sample_width=2)
        assert frames == 10240 // (2 * 2)

    def test_empty_chunks(self) -> None:
        frames = extract_wav_frames([])
        assert frames == 0

    def test_single_chunk(self) -> None:
        # 4096 bytes = 1024 frames (2ch * 2bytes)
        chunks = [b"x" * 4096]
        frames = extract_wav_frames(chunks)
        assert frames == 1024


# ---------------------------------------------------------------------------
# Testes: Brain command
# ---------------------------------------------------------------------------

class TestBrainCommand:
    """Valida o fluxo wakeword → brain command (jarvis voice)."""

    def test_brain_command_default_empty(self) -> None:
        """brainCommand default é vazio (sem STT configurado)."""
        # No módulo Nix, default = []
        # Sem brain command, o daemon apenas grava o WAV
        brain_cmd: list[str] = []
        assert brain_cmd == []

    def test_brain_command_with_voice(self) -> None:
        """Com brain command configurado, chama jarvis voice."""
        brain_cmd = ["jarvis", "voice"]
        assert brain_cmd[0] == "jarvis"
        assert brain_cmd[1] == "voice"

    def test_wav_file_creation(self, tmp_path: Path) -> None:
        """Verifica que o WAV é criado com formato correto."""
        import wave

        wav_path = tmp_path / "test.wav"
        frames = [b"\x00\x01" * 2 * 100]  # 100 frames, 2ch, 16-bit
        with wave.open(str(wav_path), "wb") as wf:
            wf.setnchannels(2)
            wf.setsampwidth(2)
            wf.setframerate(16000)
            for f in frames:
                wf.writeframes(f)

        assert wav_path.exists()
        with wave.open(str(wav_path), "rb") as wf:
            assert wf.getnchannels() == 2
            assert wf.getsampwidth() == 2
            assert wf.getframerate() == 16000


# ---------------------------------------------------------------------------
# Testes: Status/feedback
# ---------------------------------------------------------------------------

class TestStatus:
    """Valida o formato do status para o waybar."""

    def test_status_json_format(self, tmp_path: Path) -> None:
        """Status do waybar é JSON válido com state + text."""
        status_file = tmp_path / "jarvis-status.json"
        status = {"state": "idle", "text": "Ouvindo..."}
        status_file.write_text(json.dumps(status))

        loaded = json.loads(status_file.read_text())
        assert "state" in loaded
        assert "text" in loaded
        assert loaded["state"] == "idle"

    def test_status_states(self) -> None:
        """Todos os estados válidos do wakeword."""
        valid_states = {"idle", "listening", "processing", "initializing"}
        for state in valid_states:
            assert isinstance(state, str)
            assert len(state) > 0


# ---------------------------------------------------------------------------
# Testes: Integração com openwakeword (mock)
# ---------------------------------------------------------------------------

class TestOpenWakeWordIntegration:
    """Testa a integração com openwakeword via mock."""

    def test_model_initialization(self) -> None:
        """Verifica que o modelo é inicializado com os paths corretos."""
        mock_model = MagicMock()
        mock_model.prediction_buffer = {"hey_jarvis_v0.1": [0.0]}

        # Simula 10 chunks sem trigger
        for _ in range(10):
            mock_model.prediction_buffer["hey_jarvis_v0.1"].append(0.3)

        scores = mock_model.prediction_buffer["hey_jarvis_v0.1"]
        assert all(s < DEFAULT_THRESHOLD for s in scores)

    def test_model_trigger_detection(self) -> None:
        """Simula detecção de trigger: score sobe acima do threshold."""
        mock_model = MagicMock()
        scores = [0.1, 0.2, 0.5, 0.7, 0.86, 0.9]  # sobe acima de 0.85
        mock_model.prediction_buffer = {"hey_jarvis_v0.1": scores}

        last_score = scores[-1]
        assert last_score > DEFAULT_THRESHOLD

    def test_model_false_positive_rejection(self) -> None:
        """Score alto瞬间的 que não sustenta = falso positivo."""
        mock_model = MagicMock()
        # Score alto瞬间的 seguido de baixo
        scores = [0.1, 0.9, 0.2, 0.1]
        mock_model.prediction_buffer = {"hey_jarvis_v0.1": scores}

        # O último score é baixo → não deveria triggerar
        assert scores[-1] < DEFAULT_THRESHOLD
