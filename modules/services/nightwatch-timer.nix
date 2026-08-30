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

      # ── Sandboxing ──
      ProtectSystem = "strict";       # /usr e /boot read-only
      PrivateTmp = true;                # /tmp privado
      NoNewPrivileges = true;           # Sem escalada de privilégio
      RestrictSUIDSGID = true;          # Sem arquivos SUID/SGID
      # ── Resource limits ──
      MemoryMax = "2G";                 # Max 2GB RAM (nightwatch needs more)
      TasksMax = 128;                   # Max 128 tasks
      TimeoutStartSec = "3600";         # 1 hour max runtime
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
