"""JARVIS Gaming — Resource Profiles (normal / gaming).

Quando um jogo está EFETIVAMENTE rodando, o sistema para serviços
pesados que competem por recursos:
  - llama-cpp-server (VRAM ~2.5GB + GPU compute)
  - llama-cpp-embeddings (CPU)
  - llama-cpp-rerank (CPU)
  - mpvpaper (iGPU compute)

Serviços MANTIDOS durante gaming (leves, sem competição):
  - qdrant (CPU-only, vector DB)
  - jarvis-wakeword (CPU-only, fast paths)
  - jarvis-vault, jarvis-idle, jarvis-telegram

Detecção multi-sinal (qualquer um = jogo ativo):
  1. GPU utilization via nvidia-smi (≥30% = jogo ativo)
  2. Hyprland fullscreen window (hyprctl clients -j)
  3. Steam game children (steam com filhos ≠ steamwebhelper)
  4. Proton/gamescope (pressure-vessel, gamescope)

Integração: NixOS module (modules/services/jarvis-gaming.nix)
            + systemd services + targets
"""
from __future__ import annotations

import json
import logging
import re
import subprocess
import time
from pathlib import Path
from typing import Any

log = logging.getLogger("jarvis.gaming")

# ═══════════════════════════════════════════════════════════════════
# Constantes
# ═══════════════════════════════════════════════════════════════════

# Serviços a PARAR durante gaming (pesados, competem por GPU/CPU/memória)
# System services
GAMING_STOP_SERVICES: list[str] = [
    "llama-cpp-server",
    "llama-cpp-embeddings",
    "llama-cpp-rerank",
    "qdrant",            # Vector DB — consome ~500MB RAM
    "mpvpaper",          # Wallpaper animation — consome iGPU
]

# User services a parar durante gaming
GAMING_STOP_USER_SERVICES: list[str] = [
    "hypridle",          # Idle manager — interfere com gaming
    "swaync",            # Notification daemon — popups atrapalham
]

# Serviços a MANTER durante gaming (leves, essenciais)
GAMING_KEEP_SERVICES: list[str] = [
    "pipewire",
    "wireplumber",
    "pipewire-pulse",
    "dbus-broker",
]

# Defaults
DEFAULT_GPU_THRESHOLD = 30  # Abaixado de 60% — MMOs/jogos leves usam 15-35% GPU
DEFAULT_GRACE_PERIOD = 30  # seconds
DEFAULT_SPIKE_DURATION = 3  # consecutive checks

# Processos internos do Steam (NÃO indicam jogo rodando)
STEAM_INTERNAL_PROCESSES = {
    "steamwebhelper",
    "steam",
    "steam_oOo",
    "crashhandler",
    " steamwebhelper",
}

# Arquivo de estado do perfil (em ~/.local/state/jarvis — sem precisar de sudo)
PROFILE_STATE_FILE = Path.home() / ".local/state/jarvis/gaming-profile"


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


def _check_hyprland_fullscreen() -> bool:
    """Verifica se há janela fullscreen via hyprctl (Hyprland)."""
    try:
        result = subprocess.run(
            ["hyprctl", "clients", "-j"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0 and result.stdout.strip():
            clients = json.loads(result.stdout)
            for client in clients:
                # Hyprland: fullscreen pode ser bool ou estado
                if client.get("fullscreen") is True:
                    log.debug(
                        "Game detected via Hyprland fullscreen: %s",
                        client.get("title", "unknown"),
                    )
                    return True
    except (
        FileNotFoundError,
        subprocess.TimeoutExpired,
        json.JSONDecodeError,
        KeyError,
        TypeError,
    ):
        pass
    return False


def _check_steam_game_children() -> bool:
    """Verifica se o Steam tem filhos que não são processos internos.

    Quando o Steam lança um jogo, cria processos filhos que não são
    steamwebhelper (UI) nem outros processos internos do Steam.
    """
    try:
        # Encontra o PID principal do Steam
        result = subprocess.run(
            ["pgrep", "-x", "steam"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return False

        steam_pid = result.stdout.strip().split("\n")[0].strip()

        # Lista filhos do Steam
        result = subprocess.run(
            ["pgrep", "-P", steam_pid],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return False

        child_pids = result.stdout.strip().split("\n")

        # Verifica se algum filho NÃO é processo interno do Steam
        for child_pid in child_pids:
            child_pid = child_pid.strip()
            if not child_pid:
                continue

            # Lê o nome do processo via /proc/PID/comm
            try:
                comm_path = Path(f"/proc/{child_pid}/comm")
                if comm_path.exists():
                    comm_name = comm_path.read_text().strip()
                    # Remove caracteres perigosos
                    comm_name = sanitize_process_name(comm_name)

                    # Verifica se é processo interno do Steam
                    is_internal = False
                    for internal in STEAM_INTERNAL_PROCESSES:
                        if internal in comm_name:
                            is_internal = True
                            break

                    if not is_internal:
                        log.debug(
                            "Game detected via Steam child process: %s (PID %s)",
                            comm_name,
                            child_pid,
                        )
                        return True
            except (OSError, PermissionError):
                continue

    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    return False


def _check_proton_gamescope() -> bool:
    """Verifica processos de Proton/gamescope (existente)."""
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


def _check_wurm_online() -> bool:
    """Detecta Wurm Online (Java game). Wurm roda como processo Java.
    Verifica se há processos Java com argumentos contendo 'wurm'."""
    try:
        result = subprocess.run(
            ["pgrep", "-f", "-i", "wurm"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            log.debug("Game detected via Wurm Online process")
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Also check for Java processes with Wurm in classpath
    try:
        result = subprocess.run(
            ["pgrep", "-f", "-i", "com.wurmonline"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode == 0 and result.stdout.strip():
            log.debug("Game detected via Wurm Online Java class")
            return True
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return False


def _check_java_game() -> bool:
    """Detecta jogos Java genéricos (processos Java com alto uso de CPU)."""
    try:
        # Check for Java processes using >20% CPU
        result = subprocess.run(
            ["pgrep", "-x", "java"],
            capture_output=True, text=True, timeout=3,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return False

        for pid in result.stdout.strip().split("\n"):
            pid = pid.strip()
            if not pid:
                continue
            try:
                # Read /proc/PID/stat for CPU usage
                stat_path = Path(f"/proc/{pid}/stat")
                if stat_path.exists():
                    stat = stat_path.read_text().split()
                    # utime + stime (field 14 + 15, 0-indexed 13+14)
                    if len(stat) > 15:
                        utime = int(stat[13])
                        stime = int(stat[14])
                        total = utime + stime
                        # High CPU time suggests active game
                        if total > 10000:  # arbitrary threshold
                            log.debug("Game detected via Java process with high CPU: PID %s", pid)
                            return True
            except (OSError, ValueError, IndexError):
                continue
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    return False


def detect_game(gpu_threshold: int = DEFAULT_GPU_THRESHOLD) -> bool:
    """Detecta se um jogo está EFETIVAMENTE rodando.

    Detecção multi-sinal (qualquer um = jogo ativo):
      1. GPU utilization via nvidia-smi (≥30% = jogo ativo)
      2. Hyprland fullscreen window (hyprctl clients -j)
      3. Steam game children (steam com filhos ≠ steamwebhelper)
      4. Proton/gamescope (pressure-vessel, gamescope)
      5. Wurm Online (Java game)
      6. Java games with high CPU usage

    Returns:
        True se jogo detectado, False caso contrário.
    """
    # 1. GPU utilization (primary signal — qualquer jogo pesado)
    gpu_util = _get_gpu_utilization()
    if gpu_util is not None and gpu_util >= gpu_threshold:
        log.debug("Game detected via GPU utilization: %d%%", gpu_util)
        return True

    # 2. Hyprland fullscreen (janela fullscreen = provavelmente jogo)
    if _check_hyprland_fullscreen():
        log.debug("Game detected via Hyprland fullscreen window")
        return True

    # 3. Steam game children (Steam com filhos ≠ internos)
    if _check_steam_game_children():
        log.debug("Game detected via Steam child process")
        return True

    # 4. Proton/gamescope (fallback para jogos via Proton)
    if _check_proton_gamescope():
        log.debug("Game detected via Proton/gamescope")
        return True

    # 5. Wurm Online (Java MMO)
    if _check_wurm_online():
        log.debug("Game detected via Wurm Online")
        return True

    # 6. Java games with high CPU (generic fallback)
    if _check_java_game():
        log.debug("Game detected via Java process with high CPU")
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


def _notify(title: str, msg: str, icon: str = "dialog-information") -> None:
    """Notificação visual via notify-send (best-effort)."""
    notify_bin = "/run/current-system/sw/bin/notify-send"
    try:
        subprocess.Popen(
            [notify_bin, "-t", "4000", "-i", icon, title, msg],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
    except (FileNotFoundError, OSError):
        pass


def _play_sound(name: str) -> None:
    """Toca um som do freedesktop (best-effort)."""
    sound_base = "/run/current-system/sw/share/sounds/freedesktop/stereo"
    sound_map = {
        "enter": "service-login.oga",
        "exit": "service-logout.oga",
    }
    sound_file = sound_map.get(name, name)
    if not sound_file.endswith(".oga"):
        sound_file += ".oga"
    canberra_bin = "/run/current-system/sw/bin/canberra-gtk-play"
    try:
        subprocess.run(
            [canberra_bin, "--file", f"{sound_base}/{sound_file}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, timeout=5,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        pass


def log_transition(
    from_profile: str,
    to_profile: str,
    reason: str,
    details: str = "",
) -> None:
    """Loga uma transição de perfil com notificação visual + sonora."""
    entry = {
        "ts": time.time(),
        "iso": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "from": from_profile,
        "to": to_profile,
        "reason": reason,
        "details": details,
    }
    log.info("Profile transition: %s → %s (%s)", from_profile, to_profile, reason)

    # Notificação visual
    if to_profile == "gaming":
        _notify("🎮 JARVIS Gaming", "Modo gaming ativo — serviços pesados pausados.", "input-gaming")
        _play_sound("enter")
    elif to_profile == "normal":
        _notify("🤖 JARVIS Normal", "Serviços restaurados — modo normal.", "emblem-default")
        _play_sound("exit")

    # Log em JSONL
    log_file = Path.home() / ".local/state/jarvis/gaming-transitions.jsonl"
    try:
        with log_file.open("a") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass  # Best-effort logging


def _stop_user_service(service: str) -> bool:
    """Para um serviço user systemd."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "stop", service],
            capture_output=True, timeout=15,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _start_user_service(service: str) -> bool:
    """Inicia um serviço user systemd."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "start", service],
            capture_output=True, timeout=30,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _service_user_is_active(service: str) -> bool:
    """Verifica se um serviço user systemd está ativo."""
    try:
        result = subprocess.run(
            ["systemctl", "--user", "is-active", "--quiet", service],
            capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def transition_to_gaming(manual: bool = False) -> list[str]:
    """Transição normal → gaming.

    Para serviços pesados e retorna a lista de serviços parados.
    Se manual=True, ignora detecção automática (para toggle via rofi).
    """
    stopped: list[str] = []
    reason = "manual_toggle" if manual else "game_detected"

    # Stop system services
    for service in GAMING_STOP_SERVICES:
        if _service_is_active(service):
            log.info("Stopping %s for gaming mode", service)
            if _stop_service(service):
                stopped.append(service)
                log.info("  %s stopped", service)
            else:
                log.warning("  Failed to stop %s", service)

    # Stop user services
    for service in GAMING_STOP_USER_SERVICES:
        if _service_user_is_active(service):
            log.info("Stopping user service %s for gaming mode", service)
            if _stop_user_service(service):
                stopped.append(f"user:{service}")
                log.info("  %s stopped", service)
            else:
                log.warning("  Failed to stop %s", service)

    # Save list of stopped services for restoration
    _save_stopped_services(stopped)

    write_profile_state("gaming")
    log_transition("normal", "gaming", reason,
                   f"stopped: {', '.join(stopped)}")
    return stopped


def transition_to_normal(manual: bool = False) -> list[str]:
    """Transição gaming → normal.

    Se manual=True, ignora detecção de jogo (para toggle via rofi).
    Reinicia serviços parados. Retorna lista de serviços iniciados.
    """
    # Double-check: game still running? (skip if manual)
    if not manual and detect_game():
        log.info("Game still active, cancelling return to normal")
        return []

    # Get list of previously stopped services
    previously_stopped = _load_stopped_services()

    started: list[str] = []

    # Restore system services
    for service in GAMING_STOP_SERVICES:
        if service in previously_stopped or (
            _service_is_enabled(service) and not _service_is_active(service)
        ):
            log.info("Starting %s (returning to normal)", service)
            if _start_service(service):
                started.append(service)
                log.info("  %s started", service)
            else:
                log.warning("  Failed to start %s", service)

    # Restore user services
    for service in GAMING_STOP_USER_SERVICES:
        user_key = f"user:{service}"
        if user_key in previously_stopped or not _service_user_is_active(service):
            log.info("Starting user service %s (returning to normal)", service)
            if _start_user_service(service):
                started.append(user_key)
                log.info("  %s started", service)
            else:
                log.warning("  Failed to start %s", service)

    # Clear saved state
    _clear_stopped_services()

    write_profile_state("normal")
    log_transition("gaming", "normal", "game_ended",
                   f"started: {', '.join(started)}")
    return started


def _save_stopped_services(stopped: list[str]) -> None:
    """Save list of stopped services for later restoration."""
    state_file = Path.home() / ".local/state/jarvis/gaming-stopped-services.json"
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps(stopped))
    except OSError:
        pass


def _load_stopped_services() -> list[str]:
    """Load list of previously stopped services."""
    state_file = Path.home() / ".local/state/jarvis/gaming-stopped-services.json"
    try:
        return json.loads(state_file.read_text())
    except (OSError, json.JSONDecodeError):
        return []


def _clear_stopped_services() -> None:
    """Clear saved stopped services state."""
    state_file = Path.home() / ".local/state/jarvis/gaming-stopped-services.json"
    try:
        state_file.unlink(missing_ok=True)
    except OSError:
        pass


def toggle_gaming() -> dict[str, Any]:
    """Toggle gaming mode on/off. Returns new state."""
    current = get_current_profile()
    if current == "gaming":
        started = transition_to_normal(manual=True)
        return {
            "profile": "normal",
            "action": "restored",
            "services_started": started,
        }
    else:
        stopped = transition_to_gaming(manual=True)
        return {
            "profile": "gaming",
            "action": "activated",
            "services_stopped": stopped,
        }


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
