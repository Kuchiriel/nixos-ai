{ config, lib, pkgs, ... }:
let
  cfg = config.services.jarvis-notify;
in {
  options.services.jarvis-notify = {
    enable = lib.mkEnableOption "Sistema unificado de notificacoes audio com personalidade JARVIS MCU";
    user = lib.mkOption {
      type = lib.types.str;
      default = "nixos";
      description = "Usuario dono do servico.";
    };
  };

  config = lib.mkIf (config.services.jarvis.enable && cfg.enable) {
    environment.systemPackages = [
      (pkgs.writeShellScript "jarvis-notify" ''
        #!/usr/bin/env bash
        EVENT="$1"
        TEXT="$2"
        [ -z "$EVENT" ] && EVENT="unknown"
        PRIORITY="$3"
        [ -z "$PRIORITY" ] && PRIORITY="normal"
        STATE_DIR="/home/$USER/.local/state/jarvis"
        mkdir -p "$STATE_DIR"

        case "$EVENT" in
          charger-connect)
            [ -z "$TEXT" ] && TEXT="Senhor, o carregador esta conectado."
            [ "$PRIORITY" = "normal" ] && PRIORITY="info"
            ;;
          charger-disconnect)
            [ -z "$TEXT" ] && TEXT="Senhor, o carregador foi desconectado."
            ;;
          battery-low)
            [ -z "$TEXT" ] && TEXT="Senhor, a bateria esta baixa. Recomendo conectar o carregador."
            ;;
          battery-critical)
            [ -z "$TEXT" ] && TEXT="Senhor, bateria critica. Sistema sera suspenso para preservacao."
            ;;
          disk-alert)
            [ -z "$TEXT" ] && TEXT="Senhor, o disco esta acima de noventa por cento."
            ;;
          cpu-alert)
            [ -z "$TEXT" ] && TEXT="Senhor, a carga do processador esta elevada."
            ;;
          service-down)
            [ -z "$TEXT" ] && TEXT="Senhor, servico inacessivel."
            ;;
          thermal)
            [ -z "$TEXT" ] && TEXT="Senhor, temperatura elevada. Ventoinhas em accao."
            ;;
          network-down)
            [ -z "$TEXT" ] && TEXT="Senhor, conectividade de rede perdida."
            ;;
          network-up)
            [ -z "$TEXT" ] && TEXT="Senhor, conectividade de rede restaurada."
            ;;
          bluetooth-disconnect)
            [ -z "$TEXT" ] && TEXT="Senhor, dispositivo Bluetooth desconectado. Reconectando."
            ;;
          suspend)
            [ -z "$TEXT" ] && TEXT="Senhor, sistema sera suspenso em breve."
            ;;
          resume)
            [ -z "$TEXT" ] && TEXT="Senhor, sistema retomado."
            ;;
          security)
            [ -z "$TEXT" ] && TEXT="Senhor, novo acesso SSH detectado."
            ;;
          unknown)
            [ -z "$TEXT" ] && TEXT="Senhor, recebi um alerta. Analisando."
            ;;
        esac

        echo "[jarvis-notify] $EVENT: $TEXT"

        WAV_PATH="$STATE_DIR/notify-$EVENT.wav"
        # Write state file for waybar notification module
        printf '{"event": "%s", "priority": "%s", "text": "%s", "timestamp": %s}\n'           "$EVENT" "$PRIORITY" "$TEXT" "$(date +%s)" > "$STATE_DIR/notify-last.json" 2>/dev/null || true
        jarvis speak "$TEXT" --clone --no-play 2>/dev/null

        latest=$(ls -t "$STATE_DIR"/notify-*.wav 2>/dev/null | head -1)
        if [ -n "$latest" ]; then
          cp "$latest" "$WAV_PATH" 2>/dev/null
          aplay -q "$WAV_PATH" 2>/dev/null || true
        fi
      '')
    ];

    systemd.user.services.jarvis-notify-watcher = {
      Unit = {
        Description = "JARVIS MCU - Notification Watcher";
        After = [ "graphical-session.target" ];
      };
      Service = {
        Type = "simple";
        ExecStart = pkgs.writeShellScript "jarvis-notify-watcher" ''
          #!/usr/bin/env bash
          STATE_DIR="/home/$USER/.local/state/jarvis"
          mkdir -p "$STATE_DIR"
          echo "[jarvis-notify-watcher] Iniciado (pid $$)"

          while true; do
            ALERTS=$(jarvis triggers run 2>/dev/null || true)
            if [ -n "$ALERTS" ]; then
              jarvis-notify service-down "Senhor, alerta detectado pelo watchdog." 2>/dev/null || true
            fi
            sleep 30
          done
        '';
        Restart = "always";
        RestartSec = "10s";
        User = cfg.user;
        Environment = [
          "PATH=${pkgs.jarvis-voice}/bin:${pkgs.jarvis}/bin:${pkgs.coreutils}/bin:${pkgs.util-linux}/bin:${pkgs.alsa-utils}/bin"
          "DISPLAY=:0"
          "WAYLAND_DISPLAY=wayland-1"
          "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus"
          "JARVIS_RVC_PYTHON=/tmp/opencode/tts-venv/bin/python"
          "JARVIS_RVC_APP_DIR=/tmp/opencode/applio"
        ];
      };
      Install = {
        WantedBy = [ "graphical-session.target" ];
      };
    };
  };
}
