{ config, lib, pkgs, ... }:
let
  cfg = config.services.charger-watch;
in {
  options.services.charger-watch = {
    enable = lib.mkEnableOption "Servico que toca WAV ao conectar/desconectar carregador";
    user = lib.mkOption {
      type = lib.types.str;
      default = "nixos";
      description = "Usuario dono dos arquivos WAV e do state.";
    };
    interval = lib.mkOption {
      type = lib.types.int;
      default = 5;
      description = "Intervalo de polling em segundos.";
    };
    onWav = lib.mkOption {
      type = lib.types.path;
      default = "/home/nixos/.local/state/jarvis/charger-conectado.wav";
      description = "Caminho para o WAV tocado ao conectar o carregador.";
    };
    offWav = lib.mkOption {
      type = lib.types.path;
      default = "/home/nixos/.local/state/jarvis/charger-desconectado.wav";
      description = "Caminho para o WAV tocado ao desconectar o carregador.";
    };
  };

  config = lib.mkIf (config.services.jarvis.enable && cfg.enable) {
    systemd.user.services.charger-watch = {
      description = "JARVIS - Charger Connect/Disconnect Audio Notifier";
      wantedBy = [ "graphical-session.target" ];
      serviceConfig = {
        Type = "simple";
        ExecStart = pkgs.writeShellScript "charger-watch" ''
          #!/usr/bin/env bash
          INTERVAL="${toString cfg.interval}"
          AC="/sys/class/power_supply/ACAD/online"
          OFF="${cfg.offWav}"
          ON_MSG="${cfg.onWav}"
          LAST=0
          ac_status() { cat "$AC" 2>/dev/null || echo 1; }
          echo $$ > /tmp/charger-watch.pid
          LAST=$(ac_status)
          echo "charger-watch: monitorando $AC (intervalo $INTERVALs, pid $$)"
          while true; do
            ON=$(ac_status)
            if [ "$LAST" = "1" ] && [ "$ON" = "0" ]; then
              echo "[$(date +%H:%M:%S)] DESCONECTADO"
              aplay -q "$OFF" 2>/dev/null
            elif [ "$LAST" = "0" ] && [ "$ON" = "1" ]; then
              echo "[$(date +%H:%M:%S)] CONECTADO"
              aplay -q "$ON_MSG" 2>/dev/null
            fi
            LAST=$ON
            sleep "$INTERVAL"
          done
        '';
        Restart = "always";
        RestartSec = "10s";
        User = cfg.user;
        Environment = [
          "PATH=${pkgs.coreutils}/bin:${pkgs.util-linux}/bin:${pkgs.alsa-utils}/bin"
          "DISPLAY=:0"
          "WAYLAND_DISPLAY=wayland-1"
          "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus"
        ];
      };
    };
  };
}
