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
    systemd.user.services.jarvis-focus = {
      Unit = {
        Description = "JARVIS — Focus Mode Manager (EventBus)";
        After = [ "graphical-session.target" ];
      };
      Service = {
        Type = "simple";
        ExecStart = "${pkgs.jarvis}/bin/jarvis focus-daemon";
        Restart = "always";
        RestartSec = "5s";
        User = cfg.user;
        Environment = [
          "PATH=${pkgs.jarvis}/bin:${pkgs.python3}/bin:${pkgs.coreutils}/bin:${pkgs.util-linux}/bin"
          "DISPLAY=:0"
          "WAYLAND_DISPLAY=wayland-1"
          "DBUS_SESSION_BUS_ADDRESS=unix:path=/run/user/1000/bus"
          "JARVIS_STATUS_FILE=/tmp/jarvis-status.json"
          "JARVIS_NOTIFY_LAST=/tmp/jarvis-notify-last.json"
          "JARVIS_FOCUS_STATE=/tmp/jarvis-focus-state"
        ];
      };
    };
  };
}
