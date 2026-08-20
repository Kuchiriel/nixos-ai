"""JARVIS Gaming — Resource Profiles (normal / gaming).

Quando um jogo está EFETIVAMENTE rodando (GPU utilization spike ou
processos de jogo detectados), o sistema para serviços pesados que
competem por recursos:
  - llama-cpp-server (VRAM ~2.5GB + GPU compute)
  - llama-cpp-embeddings (CPU)
  - llama-cpp-rerank (CPU)
  - mpvpaper (iGPU compute)

Serviços MANTIDOS durante gaming (leves, sem competição):
  - qdrant (CPU-only, vector DB)
  - jarvis-wakeword (CPU-only, fast paths)
  - jarvis-vault, jarvis-idle, jarvis-telegram

Detecção: GPU utilization via nvidia-smi (>60% = jogo ativo)
          + fallback para process tree (gamescope, proton, pressure-vessel)

Integração: NixOS module (modules/services/jarvis-gaming.nix)
            + systemd services + targets
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("jarvis.gaming")

# ═══════════════════════════════════════════════════════════════════
# Constantes
# ═══════════════════════════════════════════════════════════════════

# Serviços a PARAR durante gaming (pesados, competem por GPU/CPU)
GAMING_STOP_SERVICES: list[str] = [
    "llama-cpp-server",
    "llama-cpp-embeddings",
    "llama-cpp-rerank",
]

# Serviços a MANTER durante gaming (leves)
GAMING_KEEP_SERVICES: list[str] = [
    "qdrant",
    "jarvis-wakeword",
    "jarvis-vault",
    "jarvis-idle",
    "jarvis-telegram",
]

# Defaults
DEFAULT_GPU_THRESHOLD = 60
DEFAULT_GRACE_PERIOD = 30  # seconds
DEFAULT_SPIKE_DURATION = 3  # consecutive checks

# Arquivo de estado do perfil (em /var/lib/jarvis — já criado por tmpfiles)
PROFILE_STATE_FILE = Path("/var/lib/jarvis/resource-profile")


# ═══════════════════════════════════════════════════════════════════
# Detecção de jogo
# ═══════════════════════════════════════════════════════════════════


def _get_gpu_utilization() -> int | None:
    """Obtém GPU utilization via nvidia-smi. Retorna None se indisponível."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            return int(result.stdout.strip().split("\n")[0].strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    return None


def _check_game_processes() -> bool:
    """Verifica processos de jogo via pgrep."""
    # Gamescope (wrapper de jogo)
    try:
        result = subprocess.run(
            ["pgrep", "-x", "gamescope"],
            capture_output=True, timeout=3,
        )
        if result.returncode == 0:
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Proton / Steam Runtime (pressure-vessel)
    try:
        result = subprocess.run(
            ["pgrep", "-f", "pressure-vessel"],
            capture_output=True, timeout=3,
        )
        if result.returncode == 0:
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return False


def detect_game(gpu_threshold: int = DEFAULT_GPU_THRESHOLD) -> bool:
    """Detecta se um jogo está EFETIVAMENTE rodando.

    Primário: GPU utilization via nvidia-smi
    Secundário: process tree (gamescope, proton)

    Returns:
        True se jogo detectado, False caso contrário.
    """
    # 1. GPU utilization (primary signal)
    gpu_util = _get_gpu_utilization()
    if gpu_util is not None and gpu_util >= gpu_threshold:
        log.debug("Game detected via GPU utilization: %d%%", gpu_util)
        return True

    # 2. Process tree (fallback)
    if _check_game_processes():
        log.debug("Game detected via process tree")
        return True

    return False


def sanitize_process_name(name: str) -> str:
    """Remove caracteres perigosos de nomes de processo (anti-injection)."""
    # Remove shell metacharacters
    return re.sub(r'[;|$`&(){}[\]<>!]', '', name)


# ═══════════════════════════════════════════════════════════════════
# Transição de perfis
# ═══════════════════════════════════════════════════════════════════


def _service_is_active(service: str) -> bool:
    """Verifica se um serviço systemd está ativo."""
    try:
        result = subprocess.run(
            ["systemctl", "is-active", "--quiet", service],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _service_is_enabled(service: str) -> bool:
    """Verifica se um serviço systemd está habilitado."""
    try:
        result = subprocess.run(
            ["systemctl", "is-enabled", "--quiet", service],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _stop_service(service: str) -> bool:
    """Para um serviço systemd. Retorna True se bem-sucedido."""
    try:
        result = subprocess.run(
            ["systemctl", "stop", service],
            capture_output=True, timeout=30,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _start_service(service: str) -> bool:
    """Inicia um serviço systemd. Retorna True se bem-sucedido."""
    try:
        result = subprocess.run(
            ["systemctl", "start", service],
            capture_output=True, timeout=60,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def write_profile_state(profile: str, path: Path | None = None) -> None:
    """Escreve o estado atual do perfil em arquivo."""
    target = path or PROFILE_STATE_FILE
    try:
        target.write_text(profile)
    except OSError as exc:
        log.warning("Failed to write profile state: %s", exc)


def log_transition(
    from_profile: str,
    to_profile: str,
    reason: str,
    details: str = "",
) -> None:
    """Loga uma transição de perfil."""
    entry = {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "from": from_profile,
        "to": to_profile,
        "reason": reason,
        "details": details,
    }
    log.info("Profile transition: %s → %s (%s)", from_profile, to_profile, reason)
    # Also write to a JSONL log file
    log_file = Path("/var/log/jarvis-gaming.jsonl")
    try:
        with log_file.open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # Best-effort logging


def transition_to_gaming() -> list[str]:
    """Transição normal → gaming.

    Para serviços pesados e retorna a lista de serviços parados.
    """
    stopped: list[str] = []

    for service in GAMING_STOP_SERVICES:
        if _service_is_active(service):
            log.info("Stopping %s for gaming mode", service)
            if _stop_service(service):
                stopped.append(service)
                log.info("  %s stopped", service)
            else:
                log.warning("  Failed to stop %s", service)

    write_profile_state("gaming")
    log_transition("normal", "gaming", "game_detected",
                   f"stopped: {', '.join(stopped)}")
    return stopped


def transition_to_normal() -> list[str]:
    """Transição gaming → normal.

    Verifica se jogo ainda está ativo (cancelamento). Reinicia serviços
    parados. Retorna lista de serviços iniciados.
    """
    # Double-check: game still running?
    if detect_game():
        log.info("Game still active, cancelling return to normal")
        return []

    started: list[str] = []

    for service in GAMING_STOP_SERVICES:
        if _service_is_enabled(service) and not _service_is_active(service):
            log.info("Starting %s (returning to normal)", service)
            if _start_service(service):
                started.append(service)
                log.info("  %s started", service)
            else:
                log.warning("  Failed to start %s", service)

    write_profile_state("normal")
    log_transition("gaming", "normal", "game_ended",
                   f"started: {', '.join(started)}")
    return started


def get_current_profile() -> str:
    """Retorna o perfil atual (normal ou gaming)."""
    try:
        return PROFILE_STATE_FILE.read_text().strip()
    except OSError:
        return "normal"


def get_gpu_state() -> dict[str, Any]:
    """Obtém estado atual da GPU para observabilidade."""
    state: dict[str, Any] = {}
    try:
        result = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            parts = result.stdout.strip().split(",")
            if len(parts) >= 4:
                state = {
                    "gpu_utilization": int(parts[0].strip()),
                    "vram_used_mb": int(parts[1].strip()),
                    "vram_total_mb": int(parts[2].strip()),
                    "temperature_c": int(parts[3].strip()),
                }
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        pass
    return state
