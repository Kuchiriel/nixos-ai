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
  jarvisPackage = pkgs.jarvis;
  projectRoot = "/home/nixos/projects/nixos-ai";
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
      ExecStart = "${jarvisPackage}/bin/jarvis nightwatch --tasks 10 --report-telegram";
      WorkingDirectory = projectRoot;
      User = "nixos";

      # Capture all output to journal for audit trail
      StandardOutput = "journal";
      StandardError = "journal";

      # Safety: do NOT restart on failure (prevents crash loops)
      Restart = "no";
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
