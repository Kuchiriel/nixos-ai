{ config, lib, pkgs, ... }:
# xref-watch — weekly docs<->code cross-reference regression watch (12/10).
# Runs xref_audit.py --check (committed baseline); posts to the team
# channel ONLY on regression (new dangling links). GRAPH.md regen stays
# manual (goes through review + commit, never auto-written by timers).
let
  # (12/10) writeShellScriptBin, NOT inline bash -c: systemd chokes on
  # nested quoting ("Unbalanced quoting", unit refused to load — measured).
  xref-check = pkgs.writeShellScriptBin "xref-check" ''
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
  '';
in {
  home.packages = [ xref-check ];

  systemd.user.services.xref-watch = {
    Unit = {
      Description = "Weekly xref regression check (docs<->code)";
    };
    Service = {
      Type = "oneshot";
      ExecStart = "${xref-check}/bin/xref-check";
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
