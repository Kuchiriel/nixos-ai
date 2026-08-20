{ config, lib, pkgs, ... }:
# ═══════════════════════════════════════════════════════════════════════
# JARVIS GAMING — Resource Profiles (normal / gaming)
#
# Quando um jogo está EFETIVAMENTE rodando (GPU utilization spike),
# o sistema para serviços pesados que competem por recursos:
#   - llama-cpp-server (VRAM ~2.5GB + GPU compute)
#   - llama-cpp-embeddings (CPU)
#   - llama-cpp-rerank (CPU)
#   - mpvpaper (iGPU compute)
#
# Serviços MANTIDOS durante gaming (leves, sem competição):
#   - qdrant (CPU-only, vector DB)
#   - jarvis-wakeword (CPU-only, fast paths)
#   - jarvis-vault, jarvis-idle, jarvis-telegram
#
# Detecção: GPU utilization via nvidia-smi (>60% por 5s = jogo ativo)
# Transição: systemd targets + scripts de stop/start
# Grace period: 30s entre jogo terminar e retorno ao normal
# ═══════════════════════════════════════════════════════════════════════

let
  cfg = config.services.jarvis-gaming;

  # Serviços a PARAR durante gaming (pesados, competem por GPU/CPU)
  gamingStopServices = [
    "llama-cpp-server"
    "llama-cpp-embeddings"
    "llama-cpp-rerank"
  ];

  # Serviços a MANTER durante gaming (leves)
  # (não precisamos de lista — apenas NÃO os paramos)

  # Threshold de GPU utilization para considerar "jogo rodando"
  # 60% é conservador: Steam desktop usa ~5-15%, jogos usam 70-100%
  gpuThreshold = cfg.gpuUtilizationThreshold;

  # Tempo mínimo de GPU spike para confirmar jogo (evita falsos positivos)
  gpuSpikeDuration = cfg.gpuSpikeDurationSeconds;

  # Grace period após jogo terminar
  gracePeriod = cfg.gracePeriodSeconds;

  # ═══════════════════════════════════════════════════════════════════
  # Script de detecção de jogo
  # ═══════════════════════════════════════════════════════════════════
  # Verifica GPU utilization via nvidia-smi.
  # Retorna 0 se jogo está ativo, 1 se não.
  # Also checks for game processes (steam children, proton, gamescope).
  gameDetectScript = pkgs.writeShellScriptBin "jarvis-game-detect" ''
    set -euo pipefail

    # 1. GPU utilization check via nvidia-smi
    if command -v nvidia-smi &>/dev/null; then
      GPU_UTIL=$(nvidia-smi --query-gpu=utilization.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' ')
      if [ -n "$GPU_UTIL" ] && [ "$GPU_UTIL" -ge ${toString gpuThreshold} ] 2>/dev/null; then
        echo "gpu_active"
        exit 0
      fi
    fi

    # 2. Process tree check: steam game processes
    # Steam games run as children of steam or steamwebhelper
    # Proton games run via pressure-vessel or gamescope
    if pgrep -x "gamescope" &>/dev/null; then
      echo "gamescope_active"
      exit 0
    fi

    # Check for proton/wine processes (indicates game running under Proton)
    if pgrep -f "pressure-vessel" &>/dev/null; then
      echo "proton_active"
      exit 0
    fi

    # Check for game processes (common game executables)
    # This is a fallback — GPU utilization is the primary signal
    if pgrep -f "game_(linux|exe|bin)" &>/dev/null; then
      echo "game_process_active"
      exit 0
    fi

    exit 1
  '';

  # ═══════════════════════════════════════════════════════════════════
  # Script de transição normal → gaming
  # ═══════════════════════════════════════════════════════════════════
  transitionToGaming = pkgs.writeShellScriptBin "jarvis-transition-to-gaming" ''
    set -euo pipefail

    LOG_PREFIX="[jarvis-gaming]"
    echo "$LOG_PREFIX Transitioning to GAMING profile"

    # Log current GPU state before transition
    if command -v nvidia-smi &>/dev/null; then
      echo "$LOG_PREFIX GPU state before transition:"
      nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv 2>/dev/null | head -3
    fi

    # Stop heavy services
    ${lib.concatMapStringsSep "\n" (svc: ''
      if systemctl is-active --quiet ${svc} 2>/dev/null; then
        echo "$LOG_PREFIX Stopping ${svc}..."
        systemctl stop ${svc}
        echo "$LOG_PREFIX ${svc} stopped"
      else
        echo "$LOG_PREFIX ${svc} already stopped"
      fi
    '') gamingStopServices}

    # Log GPU state after transition
    if command -v nvidia-smi &>/dev/null; then
      sleep 1  # Wait for VRAM release
      echo "$LOG_PREFIX GPU state after transition:"
      nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv 2>/dev/null | head -3
    fi

    echo "$LOG_PREFIX GAMING profile active"
    echo "gaming" > /tmp/jarvis-resource-profile
  '';

  # ═══════════════════════════════════════════════════════════════════
  # Script de transição gaming → normal
  # ═══════════════════════════════════════════════════════════════════
  transitionToNormal = pkgs.writeShellScriptBin "jarvis-transition-to-normal" ''
    set -euo pipefail

    LOG_PREFIX="[jarvis-gaming]"
    echo "$LOG_PREFIX Grace period elapsed, checking if still gaming..."

    # Double-check: is a game still running?
    if ${gameDetectScript}/bin/jarvis-game-detect &>/dev/null; then
      echo "$LOG_PREFIX Game still active, cancelling return to normal"
      exit 0
    fi

    echo "$LOG_PREFIX Transitioning to NORMAL profile"

    # Log GPU state before restore
    if command -v nvidia-smi &>/dev/null; then
      echo "$LOG_PREFIX GPU state before restore:"
      nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total,temperature.gpu --format=csv 2>/dev/null | head -3
    fi

    # Restart services (only if they were enabled in the host config)
    ${lib.concatMapStringsSep "\n" (svc: ''
      if systemctl is-enabled --quiet ${svc} 2>/dev/null; then
        if ! systemctl is-active --quiet ${svc} 2>/dev/null; then
          echo "$LOG_PREFIX Starting ${svc}..."
          systemctl start ${svc}
          echo "$LOG_PREFIX ${svc} started"
        else
          echo "$LOG_PREFIX ${svc} already running"
        fi
      fi
    '') gamingStopServices}

    echo "$LOG_PREFIX NORMAL profile active"
    echo "normal" > /tmp/jarvis-resource-profile
  '';

  # ═══════════════════════════════════════════════════════════════════
  # Watcher daemon — monitora GPU e transiciona perfis
  # ═══════════════════════════════════════════════════════════════════
  watcherScript = pkgs.writeShellScriptBin "jarvis-gaming-watcher" ''
    set -euo pipefail

    LOG_PREFIX="[jarvis-gaming-watcher]"
    echo "$LOG_PREFIX Starting game detection watcher"

    CURRENT_PROFILE="normal"
    SPIKE_COUNT=0
    IDLE_COUNT=0
    SPIKE_THRESHOLD=${toString gpuSpikeDuration}  # consecutive spikes to confirm game
    IDLE_THRESHOLD=${toString (gracePeriod / 2)}  # consecutive idle checks before transition
    CHECK_INTERVAL=2  # seconds between checks

    # Initialize profile file
    echo "$CURRENT_PROFILE" > /var/lib/jarvis/resource-profile

    while true; do
      if ${gameDetectScript}/bin/jarvis-game-detect &>/dev/null; then
        # GPU spike detected
        SPIKE_COUNT=$((SPIKE_COUNT + 1))
        IDLE_COUNT=0

        if [ "$CURRENT_PROFILE" = "normal" ] && [ "$SPIKE_COUNT" -ge "$SPIKE_THRESHOLD" ]; then
          echo "$LOG_PREFIX Game confirmed ($SPIKE_COUNT consecutive spikes), transitioning to gaming"
          ${transitionToGaming}/bin/jarvis-transition-to-gaming
          CURRENT_PROFILE="gaming"
          echo "$CURRENT_PROFILE" > /var/lib/jarvis/resource-profile
        fi
      else
        # No GPU spike
        IDLE_COUNT=$((IDLE_COUNT + 1))
        SPIKE_COUNT=0

        if [ "$CURRENT_PROFILE" = "gaming" ] && [ "$IDLE_COUNT" -ge "$IDLE_THRESHOLD" ]; then
          echo "$LOG_PREFIX No game for $IDLE_COUNT checks, starting grace period"
          # Wait grace period, then check again
          sleep ${toString gracePeriod}
          ${transitionToNormal}/bin/jarvis-transition-to-normal
          CURRENT_PROFILE="normal"
          echo "$CURRENT_PROFILE" > /var/lib/jarvis/resource-profile
          IDLE_COUNT=0
        fi
      fi

      sleep "$CHECK_INTERVAL"
    done
  '';
in
{
  options.services.jarvis-gaming = {
    enable = lib.mkEnableOption "JARVIS Gaming Resource Profiles";

    gracePeriodSeconds = lib.mkOption {
      type = lib.types.int;
      default = 30;
      description = ''
        Seconds to wait after game ends before returning to normal profile.
        Prevents thrashing between games (e.g., closing one game and launching another).
      '';
    };

    gpuUtilizationThreshold = lib.mkOption {
      type = lib.types.int;
      default = 60;
      description = ''
        GPU utilization percentage threshold to consider a game is running.
        Steam desktop: ~5-15%. Games: ~70-100%. 60% is conservative.
      '';
    };

    gpuSpikeDurationSeconds = lib.mkOption {
      type = lib.types.int;
      default = 3;
      description = ''
        Number of consecutive 2-second checks with GPU above threshold
        before confirming a game is running. Prevents false positives.
        Total confirmation time = gpuSpikeDurationSeconds * 2 seconds.
      '';
    };
  };

  config = lib.mkIf cfg.enable {
    # ═══════════════════════════════════════════════════════════════════
    # System packages (binários para feedback visual/sonoro)
    # ═══════════════════════════════════════════════════════════════════
    environment.systemPackages = [
      gameDetectScript
      transitionToGaming
      transitionToNormal
      watcherScript
      pkgs.libnotify    # notify-send
      pkgs.libcanberra-gtk3  # canberra-gtk-play
    ];

    # ═══════════════════════════════════════════════════════════════════
    # Tmpfiles — garante que /var/lib/jarvis existe
    # ═══════════════════════════════════════════════════════════════════
    systemd.tmpfiles.rules = [
      "d /var/lib/jarvis 0755 root root -"
    ];

    # ═══════════════════════════════════════════════════════════════════
    # Systemd service — game detection watcher
    # ═══════════════════════════════════════════════════════════════════
    systemd.services.jarvis-gaming-watcher = {
      description = "JARVIS Gaming — game detection and resource profile manager";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      wantedBy = [ "multi-user.target" ];

      serviceConfig = {
        ExecStart = "${watcherScript}/bin/jarvis-gaming-watcher";
        Restart = "on-failure";
        RestartSec = 5;

        # Precisa de root para systemctl stop/start de serviços do sistema
        # (llama-cpp-server, embeddings, rerank são system services)
        User = "root";

        # Limites de recursos para o watcher (leve)
        CPUQuota = "10%";
        MemoryMax = "100M";

        # Segurança: proteção do filesystem
        ProtectSystem = "full";  # /etc, /usr, /boot read-only
        ProtectHome = "read-only";
        ReadWritePaths = ["/var/lib/jarvis"];
        NoNewPrivileges = false;  # Precisa de systemctl
      };
    };

    # ═══════════════════════════════════════════════════════════════════
    # Systemd service — oneshot for manual transition
    # ═══════════════════════════════════════════════════════════════════
    systemd.services.jarvis-gaming-transition = {
      description = "JARVIS Gaming — manual profile transition";
      serviceConfig = {
        Type = "oneshot";
        ExecStart = "${transitionToGaming}/bin/jarvis-transition-to-gaming";
        ExecStop = "${transitionToNormal}/bin/jarvis-transition-to-normal";
      };
    };
  };
}
