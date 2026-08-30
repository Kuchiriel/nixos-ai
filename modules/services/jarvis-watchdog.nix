# Jarvis Watchdog — monitoramento proativo com TTS
#
# Roda como serviço systemd user.
# Verifica GPU, RAM, disk, serviços a cada intervalo.
# Se detecta problema: fala via TTS + atualiza waybar.
#
# Ativar: services.jarvis-watchdog.enable = true;

{ config, lib, pkgs, ... }:

let
  cfg = config.services.jarvis-watchdog;
in {
  options.services.jarvis-watchdog = {
    enable = lib.mkEnableOption "JARVIS watchdog — monitoramento proativo com TTS";
    interval = lib.mkOption {
      type = lib.types.int;
      default = 60;
      description = "Intervalo entre verificações (segundos).";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.user.services.jarvis-watchdog = {
      description = "JARVIS watchdog — monitora e fala quando tem problema";
      serviceConfig = {
        Type = "simple";
        EnvironmentFile = "-/etc/jarvis-telegram.env";
        ExecStart = "${pkgs.jarvis}/bin/jarvis watchdog --interval ${cfg.interval}";
        Restart = "on-failure";
        RestartSec = 30;
        # Sandboxing (relaxed for GPU/sensor access)
        PrivateTmp = true;
        NoNewPrivileges = true;
        # Resources
        CPUWeight = 50;
        MemoryMax = "256M";
        TasksMax = 32;
        StandardOutput = "journal";
        StandardError = "journal";
      };
    };
  };
}
