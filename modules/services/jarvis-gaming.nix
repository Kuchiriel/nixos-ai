{
  config,
  lib,
  pkgs,
  ...
}:
# ═══════════════════════════════════════════════════════════════════════
# JARVIS GAMING — Resource Profiles (normal / gaming)
#
# Quando um jogo está EFETIVAMENTE rodando (GPU utilization spike),
# o sistema para serviços pesados que competem por recursos:
#   - llama-cpp-server (VRAM ~2.5GB + GPU compute)
#   - llama-cpp-embeddings (CPU)
#   - llama-cpp-rerank (CPU)
#
# Serviços MANTIDOS durante gaming (leves, sem competição):
#   - qdrant (CPU-only, vector DB)
#   - jarvis-heal, jarvis-idle, jarvis-telegram, jarvis-vault
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

  gpuThreshold = cfg.gpuUtilizationThreshold;
  gpuSpikeDuration = cfg.gpuSpikeDurationSeconds;
  gracePeriod = cfg.gracePeriodSeconds;

  # ═══════════════════════════════════════════════════════════════════
  # Script de detecção de jogo
  # ═══════════════════════════════════════════════════════════════════
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

    # 2. Hyprland fullscreen window check
    if command -v hyprctl &>/dev/null; then
      if hyprctl clients -j 2>/dev/null | python3 -c "
    import sys, json
    try:
        clients = json.load(sys.stdin)
        for c in clients:
            if c.get('fullscreen') is True:
                sys.exit(0)
        sys.exit(1)
    except:
        sys.exit(1)
    " 2>/dev/null; then
        echo "hyprland_fullscreen"
        exit 0
      fi
    fi

    # 3. Steam game children check
    STEAM_PID=$(pgrep -x "steam" 2>/dev/null | head -1)
    if [ -n "$STEAM_PID" ]; then
      STEAM_INTERNAL="steamwebhelper|steam_oOo|crashhandler"
      for CHILD_PID in $(pgrep -P "$STEAM_PID" 2>/dev/null); do
        COMM=$(cat /proc/$CHILD_PID/comm 2>/dev/null || echo "")
        if [ -n "$COMM" ] && ! echo "$COMM" | grep -qE "$STEAM_INTERNAL"; then
          echo "steam_game_active"
          exit 0
        fi
      done
    fi

    # 4. Proton/gamescope check
    if pgrep -x "gamescope" &>/dev/null; then
      echo "gamescope_active"
      exit 0
    fi

    if pgrep -f "pressure-vessel" &>/dev/null; then
      echo "proton_active"
      exit 0
    fi

    exit 1
  '';

  transitionToGaming = pkgs.writeShellScriptBin "jarvis-transition-to-gaming" ''
    set -euo pipefail
    LOG_PREFIX="[jarvis-gaming]"
    echo "$LOG_PREFIX Transitioning to GAMING profile"

    ${lib.concatMapStringsSep "\n" (svc: ''
        if systemctl is-active --quiet ${svc} 2>/dev/null; then
          echo "$LOG_PREFIX Stopping ${svc}..."
          systemctl stop ${svc}
          echo "$LOG_PREFIX ${svc} stopped"
        fi
      '') gamingStopServices}

    echo "$LOG_PREFIX GAMING profile active"
    echo "gaming" > /tmp/jarvis-resource-profile
  '';

  transitionToNormal = pkgs.writeShellScriptBin "jarvis-transition-to-normal" ''
    set -euo pipefail
    LOG_PREFIX="[jarvis-gaming]"
    echo "$LOG_PREFIX Grace period elapsed, checking if still gaming..."

    if ${gameDetectScript}/bin/jarvis-game-detect &>/dev/null; then
      echo "$LOG_PREFIX Game still active, cancelling return to normal"
      exit 0
    fi

    echo "$LOG_PREFIX Transitioning to NORMAL profile"

    ${lib.concatMapStringsSep "\n" (svc: ''
        if systemctl is-enabled --quiet ${svc} 2>/dev/null; then
          if ! systemctl is-active --quiet ${svc} 2>/dev/null; then
            echo "$LOG_PREFIX Starting ${svc}..."
            systemctl start ${svc}
          fi
        fi
      '') gamingStopServices}

    echo "$LOG_PREFIX NORMAL profile active"
    echo "normal" > /tmp/jarvis-resource-profile
  '';

  watcherScript = pkgs.writeShellScriptBin "jarvis-gaming-watcher" ''
    set -euo pipefail
    LOG_PREFIX="[jarvis-gaming-watcher]"
    echo "$LOG_PREFIX Starting game detection watcher"

    CURRENT_PROFILE="normal"
    SPIKE_COUNT=0
    IDLE_COUNT=0
    SPIKE_THRESHOLD=${toString gpuSpikeDuration}
    IDLE_THRESHOLD=${toString (gracePeriod / 2)}
    CHECK_INTERVAL=2

    echo "$CURRENT_PROFILE" > /var/lib/jarvis/resource-profile

    while true; do
      if ${gameDetectScript}/bin/jarvis-game-detect &>/dev/null; then
        SPIKE_COUNT=$((SPIKE_COUNT + 1))
        IDLE_COUNT=0

        if [ "$CURRENT_PROFILE" = "normal" ] && [ "$SPIKE_COUNT" -ge "$SPIKE_THRESHOLD" ]; then
          echo "$LOG_PREFIX Game confirmed ($SPIKE_COUNT consecutive spikes), transitioning to gaming"
          ${transitionToGaming}/bin/jarvis-transition-to-gaming
          CURRENT_PROFILE="gaming"
          echo "$CURRENT_PROFILE" > /var/lib/jarvis/resource-profile
        fi
      else
        IDLE_COUNT=$((IDLE_COUNT + 1))
        SPIKE_COUNT=0

        if [ "$CURRENT_PROFILE" = "gaming" ] && [ "$IDLE_COUNT" -ge "$IDLE_THRESHOLD" ]; then
          echo "$LOG_PREFIX No game for $IDLE_COUNT checks, starting grace period"
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
in {
  options.services.jarvis-gaming = {
    enable = lib.mkEnableOption "JARVIS Gaming Resource Profiles";

    gracePeriodSeconds = lib.mkOption {
      type = lib.types.int;
      default = 30;
      description = "Seconds to wait after game ends before returning to normal profile.";
    };

    gpuUtilizationThreshold = lib.mkOption {
      type = lib.types.int;
      default = 60;
      description = "GPU utilization percentage threshold to consider a game is running.";
    };

    gpuSpikeDurationSeconds = lib.mkOption {
      type = lib.types.int;
      default = 3;
      description = "Number of consecutive 2-second checks with GPU above threshold before confirming game.";
    };
  };

  config = lib.mkIf (config.services.jarvis.enable && cfg.enable) {
    environment.systemPackages = [
      gameDetectScript
      transitionToGaming
      transitionToNormal
      watcherScript
      pkgs.libnotify
      pkgs.libcanberra-gtk3
    ];

    systemd.tmpfiles.rules = [
      "d /var/lib/jarvis 0755 root root -"
    ];

    systemd.services.jarvis-gaming-watcher = {
      description = "JARVIS Gaming — game detection and resource profile manager";
      after = ["network-online.target" "jarvis.target"];
      wants = ["network-online.target"];
      partOf = ["jarvis.target"];
      wantedBy = ["jarvis.target"];

      serviceConfig = {
        ExecStart = "${watcherScript}/bin/jarvis-gaming-watcher";
        Restart = "on-failure";
        RestartSec = 5;
        # Root required: gaming watcher reads GPU utilization via nvidia-smi
        # which needs direct /dev/nvidia* access. The nixos user in the
        # "video" group can read GPU state, but nvidia-smi also needs
        # permission to query GPU power/thermal state which requires root.
        User = "root";
        CPUQuota = "10%";
        MemoryMax = "100M";
        ProtectSystem = "full";
        ProtectHome = "read-only";
        ReadWritePaths = ["/var/lib/jarvis"];
        NoNewPrivileges = false;
      };
    };

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
