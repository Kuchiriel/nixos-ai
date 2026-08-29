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
  jarvisPackage = config.services.jarvis.package or pkgs.jarvis;
  projectRoot = config.services.jarvis.projectRoot or "/home/nixos/projects/nixos-ai";
in {
  systemd.services.nightwatch = {
    description = "JARVIS nightwatch — autonomous overnight maintenance";
    after = [ "llama-cpp-server.service" ];
    wants = [ "llama-cpp-server.service" ];

    serviceConfig = {
      Type = "oneshot";
      Environment = [
        "PYTHONPATH=${jarvisPackage}/lib/python3.13/site-packages"
        "JARVIS_PROJECT_ROOT=${projectRoot}"
      ];
      ExecStart = "${jarvisPackage}/bin/jarvis nightwatch --tasks 20 --report-telegram --max-minutes 180";
      WorkingDirectory = projectRoot;
      User = "nixos";

      # Safety: restart on failure, but not too often
      Restart = "on-failure";
      RestartSec = 300;
      StartLimitIntervalSec = 3600;
      StartLimitBurst = 3;
    };
  };

  systemd.timers.nightwatch = {
    description = "Run JARVIS nightwatch daily at 03:00";
    wantedBy = [ "timers.target" ];

    timerConfig = {
      OnCalendar = "*-*-* 03:00:00";
      Persistent = true;
      RandomizedDelaySec = 1200;
      AccuracySec = 300;
    };
  };
}
