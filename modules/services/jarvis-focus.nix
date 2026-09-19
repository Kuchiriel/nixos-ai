{ config, lib, pkgs, ... }:
let
  cfg = config.services.jarvis-focus;
  USER = "nixos";
in {
  options.services.jarvis-focus = {
    enable = lib.mkEnableOption "Modo foco — silencia notificacoes nao-criticas";
    user = lib.mkOption {
      type = lib.types.str;
      default = "nixos";
      description = "Usuario dono do servico.";
    };
  };

  config = lib.mkIf cfg.enable {
    environment.systemPackages = [
      (pkgs.writeShellScript "jarvis-focus" ''
        #!/usr/bin/env bash
        STATE_FILE="/tmp/jarvis-focus-state"
        ACTION="$1"
        [ -z "$ACTION" ] && ACTION="toggle"

        case "$ACTION" in
          enable)
            echo '{"focused": true}' > "$STATE_FILE"
            notify-send "Modo Foco" "Notificacoes criticas apenas." 2>/dev/null || true
            echo "Focus mode ENABLED"
            ;;
          disable)
            echo '{"focused": false}' > "$STATE_FILE"
            notify-send "Modo Normal" "Todas as notificacoes ativas." 2>/dev/null || true
            echo "Focus mode DISABLED"
            ;;
          toggle)
            if [ -f "$STATE_FILE" ]; then
              FOCUSED=$(python3 -c "import json; print(json.load(open('$STATE_FILE')).get('focused', False))" 2>/dev/null || echo "false")
            else
              FOCUSED="false"
            fi
            if [ "$FOCUSED" = "true" ]; then
              echo '{"focused": false}' > "$STATE_FILE"
              notify-send "Modo Normal" "Todas as notificacoes ativas." 2>/dev/null || true
              echo "Focus mode DISABLED"
            else
              echo '{"focused": true}' > "$STATE_FILE"
              notify-send "Modo Foco" "Notificacoes criticas apenas." 2>/dev/null || true
              echo "Focus mode ENABLED"
            fi
            ;;
          status)
            if [ -f "$STATE_FILE" ]; then
              FOCUSED=$(python3 -c "import json; print(json.load(open('$STATE_FILE')).get('focused', False))" 2>/dev/null || echo "false")
            else
              FOCUSED="false"
            fi
            echo "Focus mode: $FOCUSED"
            ;;
          *)
            echo "Usage: jarvis-focus {enable|disable|toggle|status}"
            ;;
        esac
      '')
    ];

    systemd.user.services.jarvis-focus = {
      Unit = {
        Description = "JARVIS — Focus Mode Manager";
        After = [ "graphical-session.target" ];
      };
      Service = {
        Type = "simple";
        ExecStart = pkgs.writeShellScript "jarvis-focus-daemon" ''
          #!/usr/bin/env bash
          STATE_FILE="/home/''${USER:-nixos}/.local/state/jarvis/focus-state"
          NOTIFY_FILE="/home/''${USER:-nixos}/.local/state/jarvis/notify-last.json"
          mkdir -p "/home/''${USER:-nixos}/.local/state/jarvis"
          echo "[jarvis-focus] Iniciado (pid $$)"

          while true; do
            if [ -f "$STATE_FILE" ]; then
              FOCUSED=$(python3 -c "import json; print(json.load(open('$STATE_FILE')).get('focused', False))" 2>/dev/null || echo "false")
            else
              FOCUSED="false"
            fi

            if [ -f "$NOTIFY_FILE" ]; then
              EVENT=$(python3 -c "import json; d=json.load(open('$NOTIFY_FILE')); print(d.get('event','none'))" 2>/dev/null || echo "none")
              PRIORITY=$(python3 -c "import json; d=json.load(open('$NOTIFY_FILE')); print(d.get('priority','normal'))" 2>/dev/null || echo "normal")

              if [ "$FOCUSED" = "true" ] && [ "$PRIORITY" != "critical" ] && [ "$PRIORITY" != "error" ]; then
                PRIORITY="info"
              fi

              python3 -c "import json; json.dump({'event': '$EVENT', 'priority': '$PRIORITY', 'focused': '$FOCUSED'}, open('$NOTIFY_FILE', 'w'))" 2>/dev/null || true
            fi

            sleep 2
          done
        '';
        Restart = "always";
        RestartSec = "5s";
        User = cfg.user;
        Environment = [
          "PATH=${pkgs.python3}/bin:${pkgs.coreutils}/bin:${pkgs.util-linux}/bin"
          "DISPLAY=:0"
          "WAYLAND_DISPLAY=wayland-1"
          "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus"
        ];
      };
      Install = {
        WantedBy = [ "graphical-session.target" ];
      };
    };
  };
}
