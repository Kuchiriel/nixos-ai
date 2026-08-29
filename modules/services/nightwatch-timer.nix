# ═══ Nightwatch Timer — overnight autonomous execution ═══
#
# Runs jarvis nightwatch every day at 03:00.
# Independent of session — systemd handles scheduling.
#
# Usage:
#   systemctl --user start nightwatch    # run now
#   systemctl --user status nightwatch   # check status
#   journalctl --user -u nightwatch -f   # follow logs

{ config, lib, pkgs, ... }:

let
  jarvisEnv = config.services.jarvis.environment or {};
in {
  systemd.user.services.nightwatch = {
    Description = "JARVIS nightwatch — autonomous overnight maintenance";
    After = [ "llama-cpp-server.service" ];
    Wants = [ "llama-cpp-server.service" ];

    Service = {
      Type = "oneshot";
      Environment = [
        "PYTHONPATH=${config.services.jarvis.package or pkgs.jarvis}/lib/python3.13/site-packages"
        "JARVIS_PROJECT_ROOT=${config.services.jarvis.projectRoot or "/home/nixos/projects/nixos-ai"}"
      ] ++ lib.mapAttrsToList (n: v: "${n}=${v}") jarvisEnv;

      ExecStart = "${config.services.jarvis.package or pkgs.jarvis}/bin/jarvis nightwatch --tasks 20 --report-telegram --max-minutes 180";
      WorkingDirectory = config.services.jarvis.projectRoot or "/home/nixos/projects/nixos-ai";

      # Safety: restart on failure, but not too often
      Restart = "on-failure";
      RestartSec = 300;
      StartLimitIntervalSec = 3600;
      StartLimitBurst = 3;
    };

    Install = {
      WantedBy = [ "default.target" ];
    };
  };

  systemd.user.timers.nightwatch = {
    Description = "Run JARVIS nightwatch daily at 03:00";
    WantedBy = [ "timers.target" ];

    Timer = {
      OnCalendar = "*-*-* 03:00:00";
      Persistent = true;
      RandomizedDelaySec = 1200;  # 0-20min random delay
      AccuracySec = 300;
    };
  };
}
