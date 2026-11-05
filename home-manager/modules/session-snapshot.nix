{ config, lib, pkgs, ... }:
# session-snapshot — o layout das janelas opencode sobrevive ao reboot (03/11).
#
# POR QUÊ: o Hyprland não restaura janelas e um reboot anterior (nsncd)
# perdeu as 6 janelas do opencode — as SESSÕES ficam no SQLite
# (~/.local/share/opencode/opencode.db), só as janelas somem. Agora:
#   - este timer captura o layout (ws + left/right + session id) a cada 60s
#     em ~/.local/state/jarvis/sessions-snapshot.tsv;
#   - o exec-once do Hyprland (modules/hyprland/main.nix) restaura do mesmo
#     arquivo no login — idempotente, pula o que já está aberto.
# O script é o mesmo dos dois lados: scripts/restore-sessions.sh.
{
  systemd.user.services.session-snapshot = {
    Unit = {
      Description = "Captura o layout das janelas opencode (restore no boot)";
    };
    Service = {
      Type = "oneshot";
      ExecStart = "/home/nixos/projects/nixos-ai/scripts/restore-sessions.sh --capture";
    };
  };

  systemd.user.timers.session-snapshot = {
    Unit = {
      Description = "Snapshot do layout opencode a cada 60s";
    };
    Timer = {
      OnBootSec = "2min";
      OnUnitActiveSec = "60s";
      Unit = "session-snapshot.service";
    };
    Install = {
      WantedBy = [ "timers.target" ];
    };
  };
}
