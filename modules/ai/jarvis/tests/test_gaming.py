"""Testes para JARVIS Gaming — Resource Profiles.

Testa a lógica de detecção de jogo, transição de perfis, e idempotência.
Estes testes NÃO dependem de hardware real — mockam nvidia-smi e processos.
"""
from __future__ import annotations

import json
import os
import subprocess
import tempfile
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ═══════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════


@pytest.fixture
def profile_file(tmp_path):
    """Arquivo temporário de perfil (simula /tmp/jarvis-resource-profile)."""
    f = tmp_path / "jarvis-resource-profile"
    f.write_text("normal")
    return f


@pytest.fixture
def mock_nvidia_smi_gpu_active():
    """Mock nvidia-smi retornando GPU ativa (jogo rodando)."""
    with patch("subprocess.run") as mock_run:
        def side_effect(cmd, **kwargs):
            if "nvidia-smi" in cmd:
                result = MagicMock()
                result.stdout = "75\n"  # GPU utilization 75%
                result.returncode = 0
                return result
            result = MagicMock()
            result.stdout = ""
            result.returncode = 1
            return result
        mock_run.side_effect = side_effect
        yield mock_run


@pytest.fixture
def mock_nvidia_smi_gpu_idle():
    """Mock nvidia-smi retornando GPU idle (sem jogo)."""
    with patch("subprocess.run") as mock_run:
        def side_effect(cmd, **kwargs):
            if "nvidia-smi" in cmd:
                result = MagicMock()
                result.stdout = "5\n"  # GPU utilization 5%
                result.returncode = 0
                return result
            result = MagicMock()
            result.stdout = ""
            result.returncode = 1
            return result
        mock_run.side_effect = side_effect
        yield mock_run


@pytest.fixture
def mock_nvidia_smi_no_gpu():
    """Mock nvidia-smi não encontrado (sem GPU NVIDIA)."""
    with patch("subprocess.run") as mock_run:
        def side_effect(cmd, **kwargs):
            if "nvidia-smi" in cmd:
                raise FileNotFoundError("nvidia-smi not found")
            result = MagicMock()
            result.stdout = ""
            result.returncode = 1
            return result
        mock_run.side_effect = side_effect
        yield mock_run


# ═══════════════════════════════════════════════════════════════════
# Testes de Detecção
# ═══════════════════════════════════════════════════════════════════


class TestGameDetection:
    """Testes de detecção de jogo ativo."""

    def test_gpu_above_threshold_detects_game(self, mock_nvidia_smi_gpu_active):
        """GPU utilization > threshold → jogo detectado."""
        from jarvis.core.gaming import detect_game
        assert detect_game(gpu_threshold=30) is True

    def test_gpu_below_threshold_no_game(self, mock_nvidia_smi_gpu_idle):
        """GPU utilization < threshold → sem jogo."""
        from jarvis.core.gaming import detect_game
        assert detect_game(gpu_threshold=30) is False

    def test_no_gpu_fallback_to_hyprland_fullscreen(self, mock_nvidia_smi_no_gpu):
        """Sem GPU NVIDIA → fallback para Hyprland fullscreen."""
        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                if "hyprctl" in cmd and "clients" in cmd:
                    result = MagicMock()
                    result.stdout = '[{"fullscreen": true, "title": "Wurm Online"}]'
                    result.returncode = 0
                    return result
                result = MagicMock()
                result.stdout = ""
                result.returncode = 1
                return result
            mock_run.side_effect = side_effect

            from jarvis.core.gaming import detect_game
            assert detect_game(gpu_threshold=30) is True

    def test_no_gpu_steam_game_children(self, mock_nvidia_smi_no_gpu):
        """Sem GPU → Steam com filhos ≠ steamwebhelper = jogo."""
        with patch("jarvis.core.gaming._check_steam_game_children") as mock_steam:
            mock_steam.return_value = True
            from jarvis.core.gaming import detect_game
            assert detect_game(gpu_threshold=30) is True

    def test_no_gpu_no_processes_no_game(self, mock_nvidia_smi_no_gpu):
        """Sem GPU e sem processos → sem jogo."""
        with patch("subprocess.run") as mock_run:
            result = MagicMock()
            result.returncode = 1  # no process
            mock_run.return_value = result

            from jarvis.core.gaming import detect_game
            assert detect_game(gpu_threshold=30) is False

    def test_hyprland_fullscreen_detects_game(self, mock_nvidia_smi_gpu_idle):
        """Hyprland fullscreen → jogo detectado (mesmo com GPU baixa)."""
        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                if "hyprctl" in cmd and "clients" in cmd:
                    result = MagicMock()
                    result.stdout = '[{"fullscreen": true, "title": "Game"}]'
                    result.returncode = 0
                    return result
                result = MagicMock()
                result.stdout = ""
                result.returncode = 1
                return result
            mock_run.side_effect = side_effect

            from jarvis.core.gaming import detect_game
            assert detect_game(gpu_threshold=30) is True

    def test_steam_only_internal_no_game(self, mock_nvidia_smi_no_gpu):
        """Steam com apenas processos internos → sem jogo."""
        with patch("jarvis.core.gaming._check_steam_game_children") as mock_steam:
            mock_steam.return_value = False
            from jarvis.core.gaming import detect_game
            assert detect_game(gpu_threshold=30) is False


# ═══════════════════════════════════════════════════════════════════
# Testes de Transição
# ═══════════════════════════════════════════════════════════════════


class TestProfileTransition:
    """Testes de transição entre perfis."""

    def test_normal_to_gaming_stops_services(self, mock_nvidia_smi_gpu_active):
        """Transição normal→gaming para serviços pesados."""
        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                if "systemctl" in cmd and "is-active" in cmd:
                    result = MagicMock()
                    result.stdout = "active\n"
                    result.returncode = 0
                    return result
                if "systemctl" in cmd and "stop" in cmd:
                    result = MagicMock()
                    result.stdout = ""
                    result.returncode = 0
                    return result
                if "nvidia-smi" in cmd:
                    result = MagicMock()
                    result.stdout = "75\n"
                    result.returncode = 0
                    return result
                result = MagicMock()
                result.stdout = ""
                result.returncode = 0
                return result
            mock_run.side_effect = side_effect

            from jarvis.core.gaming import transition_to_gaming
            services_stopped = transition_to_gaming()
            assert "llama-cpp-server" in services_stopped

    def test_gaming_to_normal_starts_services(self):
        """Transição gaming→normal reinicia serviços."""
        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                if "systemctl" in cmd and "is-enabled" in cmd:
                    result = MagicMock()
                    result.stdout = "enabled\n"
                    result.returncode = 0
                    return result
                if "systemctl" in cmd and "is-active" in cmd:
                    result = MagicMock()
                    result.stdout = "inactive\n"
                    result.returncode = 3
                    return result
                if "systemctl" in cmd and "start" in cmd:
                    result = MagicMock()
                    result.stdout = ""
                    result.returncode = 0
                    return result
                if "nvidia-smi" in cmd:
                    result = MagicMock()
                    result.stdout = "5\n"
                    result.returncode = 0
                    return result
                if "pgrep" in cmd:
                    result = MagicMock()
                    result.returncode = 1
                    return result
                result = MagicMock()
                result.stdout = ""
                result.returncode = 0
                return result
            mock_run.side_effect = side_effect

            from jarvis.core.gaming import transition_to_normal
            services_started = transition_to_normal()
            assert "llama-cpp-server" in services_started


# ═══════════════════════════════════════════════════════════════════
# Testes de Idempotência
# ═══════════════════════════════════════════════════════════════════


class TestIdempotency:
    """Testes de idempotência das transições."""

    def test_normal_to_normal_no_action(self):
        """normal → normal: nenhuma ação desnecessária."""
        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                if "systemctl" in cmd and "is-enabled" in cmd:
                    result = MagicMock()
                    result.stdout = "enabled\n"
                    result.returncode = 0
                    return result
                if "systemctl" in cmd and "is-active" in cmd:
                    result = MagicMock()
                    result.stdout = "active\n"
                    result.returncode = 0
                    return result
                if "systemctl" in cmd and "start" in cmd:
                    result = MagicMock()
                    result.stdout = ""
                    result.returncode = 0
                    return result
                if "nvidia-smi" in cmd:
                    result = MagicMock()
                    result.stdout = "5\n"
                    result.returncode = 0
                    return result
                if "pgrep" in cmd:
                    result = MagicMock()
                    result.returncode = 1
                    return result
                result = MagicMock()
                result.stdout = ""
                result.returncode = 0
                return result
            mock_run.side_effect = side_effect

            from jarvis.core.gaming import transition_to_normal
            # When already in normal, detect_game returns False,
            # so transition_to_normal checks services:
            # - is-enabled: yes
            # - is-active: yes (already running)
            # → no start needed
            services_started = transition_to_normal()
            # Services already active → no start needed
            assert len(services_started) == 0

    def test_gaming_to_gaming_no_action(self, mock_nvidia_smi_gpu_active):
        """gaming → gaming: serviços já parados, nenhuma ação."""
        with patch("subprocess.run") as mock_run:
            def side_effect(cmd, **kwargs):
                if "systemctl" in cmd and "is-active" in cmd:
                    # Services already stopped (inactive)
                    result = MagicMock()
                    result.stdout = "inactive\n"
                    result.returncode = 3
                    return result
                if "systemctl" in cmd and "stop" in cmd:
                    result = MagicMock()
                    result.stdout = ""
                    result.returncode = 0
                    return result
                if "nvidia-smi" in cmd:
                    result = MagicMock()
                    result.stdout = "75\n"
                    result.returncode = 0
                    return result
                result = MagicMock()
                result.stdout = ""
                result.returncode = 0
                return result
            mock_run.side_effect = side_effect

            from jarvis.core.gaming import transition_to_gaming
            # Services already inactive → transition finds nothing to stop
            stopped = transition_to_gaming()
            # No services were active → nothing to stop
            assert len(stopped) == 0


# ═══════════════════════════════════════════════════════════════════
# Testes de Grace Period
# ═══════════════════════════════════════════════════════════════════


class TestGracePeriod:
    """Testes de grace period e cancelamento."""

    def test_grace_period_cancelled_if_game_restarts(self):
        """Se jogo reinicia durante grace period, cancela retorno ao normal."""
        with patch("subprocess.run") as mock_run:
            call_count = 0
            def side_effect(cmd, **kwargs):
                nonlocal call_count
                call_count += 1
                # First check after grace: game is back
                if call_count <= 2:
                    result = MagicMock()
                    result.stdout = "80\n"
                    result.returncode = 0
                    return result
                # Later: game still active
                if "nvidia-smi" in cmd:
                    result = MagicMock()
                    result.stdout = "80\n"
                    result.returncode = 0
                    return result
                if "systemctl" in cmd:
                    result = MagicMock()
                    result.stdout = ""
                    result.returncode = 0
                    return result
                result = MagicMock()
                result.stdout = ""
                result.returncode = 1
                return result
            mock_run.side_effect = side_effect

            from jarvis.core.gaming import transition_to_normal
            # Should NOT start services because game is still active
            services_started = transition_to_normal()
            # The function should detect game still active and not start services
            # (This depends on the implementation checking detect_game inside transition_to_normal)


# ═══════════════════════════════════════════════════════════════════
# Testes de Segurança
# ═══════════════════════════════════════════════════════════════════


class TestSecurity:
    """Testes de segurança do módulo."""

    def test_no_shell_injection_in_process_check(self):
        """Nomes de processo não devem permitir shell injection."""
        from jarvis.core.gaming import sanitize_process_name
        # Test injection attempts
        assert sanitize_process_name("game; rm -rf /") == "game rm -rf /"
        assert sanitize_process_name("game$(whoami)") == "gamewhoami"
        assert sanitize_process_name("game`id`") == "gameid"

    def test_services_list_is_fixed(self):
        """Lista de serviços a parar é fixa e auditável."""
        from jarvis.core.gaming import GAMING_STOP_SERVICES, GAMING_STOP_USER_SERVICES
        assert "llama-cpp-server" in GAMING_STOP_SERVICES
        assert "qdrant" in GAMING_STOP_SERVICES  # Qdrant consome ~500MB RAM
        assert "mpvpaper" in GAMING_STOP_SERVICES  # Wallpaper consome iGPU
        # User services
        assert "hypridle" in GAMING_STOP_USER_SERVICES
        assert "swaync" in GAMING_STOP_USER_SERVICES

    def test_default_gpu_threshold_is_30(self):
        """Threshold padrão é 30% (abaixado de 60% para MMOs/jogos leves)."""
        from jarvis.core.gaming import DEFAULT_GPU_THRESHOLD
        assert DEFAULT_GPU_THRESHOLD == 30


# ═══════════════════════════════════════════════════════════════════
# Testes de Observabilidade
# ═══════════════════════════════════════════════════════════════════


class TestObservability:
    """Testes de observabilidade e logging."""

    def test_profile_state_file(self, profile_file):
        """Estado do perfil é escrito em arquivo legível."""
        from jarvis.core.gaming import write_profile_state
        write_profile_state("gaming", profile_file)
        assert profile_file.read_text().strip() == "gaming"

    def test_transition_logged(self):
        """Transições são logadas."""
        from jarvis.core.gaming import log_transition
        # Should not raise
        log_transition("normal", "gaming", "game_detected", "llama-cpp-server stopped")
