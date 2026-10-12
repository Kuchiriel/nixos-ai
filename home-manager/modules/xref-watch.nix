{ config, lib, pkgs, ... }:
# xref-watch — weekly docs<->code cross-reference regression watch (12/10).
# Runs xref_audit.py --check (committed baseline); posts to the team
# channel ONLY on regression (new dangling links). GRAPH.md regen stays
# manual (goes through review + commit, never auto-written by timers).
{
  systemd.user.services.xref-watch = {
    Unit = {
      Description = "Weekly xref regression check (docs<->code)";
    };
    Service = {
      Type = "oneshot";
      ExecStart = ''
        ${pkgs.bash}/bin/bash -c '
          set -u
          OUT=$(${pkgs.python3}/bin/python3 \
            /home/nixos/projects/canary-official/dataset/tools/xref_audit.py \
            --check 2>&1 | tail -1)
          echo "$OUT"
          case "$OUT" in
            *CHECK\ FAIL*)
              /home/nixos/projects/team/tg.sh post \
                "[xref] cross-ref regression: $OUT" || true
              ;;
          esac
        '
      '';
    };
  };

  systemd.user.timers.xref-watch = {
    Unit = {
      Description = "Weekly xref regression check";
    };
    Timer = {
      OnCalendar = "Sun *-*-* 04:00:00";
      Persistent = true;
    };
    Install = {
      WantedBy = [ "timers.target" ];
    };
  };
}
