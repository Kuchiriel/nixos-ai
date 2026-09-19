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
    systemd.user.services.jarvis-notify-watcher = {
      description = "JARVIS MCU - Notification Watcher (EventBus)";
      wantedBy = [ "graphical-session.target" ];
      serviceConfig = {
        Type = "simple";
        ExecStart = "${pkgs.jarvis}/bin/jarvis watch --interval 30";
        Restart = "always";
        RestartSec = "10s";
        User = cfg.user;
        Environment = [
          "PATH=${pkgs.jarvis}/bin:${pkgs.coreutils}/bin:${pkgs.util-linux}/bin:${pkgs.alsa-utils}/bin"
          "DISPLAY=:0"
          "WAYLAND_DISPLAY=wayland-1"
          "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus"
          "JARVIS_STATUS_FILE=/tmp/jarvis-status.json"
          "JARVIS_NOTIFY_LAST=/tmp/jarvis-notify-last.json"
        ];
      };
    };
  };
}
