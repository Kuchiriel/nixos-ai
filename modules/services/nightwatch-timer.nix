# Nightwatch Timer — autonomous maintenance (opt-in, resource-guarded)
#
# Runs `jarvis nightwatch` on a schedule for bounded, evidence-driven improvements.
# Disabled by default: enable explicitly when you want unattended runs.
#
# Why disabled by default (history): previously contended for GPU/resources and
# collided with other nightly jobs; the loop must be bounded, observable, and
# must not fight interactive/bench/GPU work.

{ config, lib, pkgs, ... }:

let
  cfg = config.services.jarvis.nightwatch;
  jarvisPackage = pkgs.jarvis;
  testPythonEnv = pkgs.jarvis-test-env;

  # Skip run if GPU/LLM-heavy work is active (bench/qwen or a heavy GPU job).
  # Avoids contending with the owner or scheduled benches.
  guardScript = pkgs.writeShellScript "nightwatch-guard" ''
    set -euo pipefail
    # Skip if bench-qwen is running (scheduled GPU/LLM work).
    if ${config.systemd.package}/bin/systemctl --user --quiet is-active bench-qwen.service 2>/dev/null; then
      echo "nightwatch: skipped (bench-qwen.service active)"
      exit 0
    fi
    # Best-effort: skip if another nightwatch run is active.
    if ${config.systemd.package}/bin/systemctl is-active --quiet nightwatch.service 2>/dev/null; then
      echo "nightwatch: skipped (nightwatch.service already active)"
      exit 0
    fi
    exec "$@"
  '';
in {
  options.services.jarvis.nightwatch = {
    enable = lib.mkEnableOption "Nightwatch autonomous maintenance timer (opt-in)";

    projectRoot = lib.mkOption {
      type = lib.types.str;
      default = "/home/nixos/projects/nixos-ai";
      description = "Working directory / project scope for nightwatch.";
    };

    projects = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "nixos-ai" ];
      description = "Projects passed to --projects (explicit scope; avoids unsafe auto-discovery).";
    };

    tasks = lib.mkOption {
      type = lib.types.ints.positive;
      default = 3;
      description = "Max tasks per run (--tasks). Keep small for bounded, reviewable runs.";
    };

    extraArgs = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ "--report-telegram" ];
      description = "Extra arguments passed to `jarvis nightwatch`.";
    };

    onCalendar = lib.mkOption {
      type = lib.types.str;
      # 03:30 avoids 03:00 jarvis-consolidate; adjust if schedule changes.
      default = "*-*-* 03:30:00";
      description = "systemd OnCalendar for the timer (pick a window free of GPU/LLM contention).";
    };

    randomizedDelaySec = lib.mkOption {
      type = lib.types.str;
      default = "900";
      description = "RandomizedDelaySec to avoid thundering herd on rebuild catch-up.";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.nightwatch = {
      description = "JARVIS nightwatch — bounded autonomous maintenance";
      after = [ "llama-cpp-server.service" "jarvis.target" "llama-cpp-ik.service" "network-online.target" ];
      wants = [ "network-online.target" ];
      # No wantedBy: timer is the trigger (avoid running on every rebuild/switch).

      serviceConfig = {
        Type = "oneshot";
        Environment = [
          "PYTHONPATH=${jarvisPackage}/lib/python3.13/site-packages"
          "JARVIS_TEST_PYTHON=${testPythonEnv}/bin/python3"
          "JARVIS_PROJECT_ROOT=${cfg.projectRoot}"
          "PATH=${testPythonEnv}/bin:/run/wrappers/bin:/run/current-system/sw/bin:${pkgs.git}/bin:${pkgs.coreutils}/bin:${pkgs.gnugrep}/bin:${pkgs.findutils}/bin:${pkgs.gnused}/bin"
        ];
        ExecStart =
          let
            args = lib.escapeShellArgs (
              [ "--tasks" (toString cfg.tasks) ]
              ++ [ "--projects" ] ++ cfg.projects
              ++ cfg.extraArgs
            );
          in
            "${guardScript} ${jarvisPackage}/bin/jarvis nightwatch ${args}";
        WorkingDirectory = cfg.projectRoot;
        User = "nixos";

        StandardOutput = "journal";
        StandardError = "journal";
        Restart = "no";

        # Restore machine state after run (privileged stoppost, ExecStart stays unprivileged).
        ExecStopPost = "+/bin/sh -c '/run/current-system/sw/bin/systemctl stop llama-cpp-ik.service || true; /run/current-system/sw/bin/systemctl start llama-cpp-server.service || true'";

        # Sandboxing
        ProtectSystem = "strict";
        PrivateTmp = true;
        NoNewPrivileges = true;
        RestrictSUIDSGID = true;
        # Resource limits (bounded run)
        MemoryMax = "2G";
        TasksMax = 128;
        TimeoutStartSec = "3600";
      };
    };

    systemd.timers.nightwatch = {
      description = "Run JARVIS nightwatch (bounded, opt-in)";
      wantedBy = [ "timers.target" ];

      timerConfig = {
        OnCalendar = cfg.onCalendar;
        # No Persistent: avoid catch-up firing on rebuild/reload (can steal GPU at bad time).
        RandomizedDelaySec = cfg.randomizedDelaySec;
        AccuracySec = "300";
      };
    };
  };
}
