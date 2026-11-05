{ config, lib, pkgs, ... }:
# agents-keepawake — segura o idle da TELA enquanto houver agente vivo
# (opencode TUI/CLI/serve, freebuff, buffy, duplex-voice).
#
# SEPARADO do agents-watcher (17/10): o watcher é o ciclo de eventos/wake
# e roda SÓ quando o dono está AFK (sem Install.WantedBy por decisão
# dele). O keepawake é o oposto — tem que estar SEMPRE ligado, senão a
# tela dorme no meio do trabalho. Por isso são dois serviços com
# responsabilidades distintas, mas UM único script de keepawake
# (scripts/agents-keepawake.sh) — o watcher não tem mais cópia própria.
#
# hypridle: ignore_dbus_inhibit=false → respeita o lock systemd-inhibit.
# Sem agente vivo → o loop solta o lock e a tela volta a dormir.
#
# Prova viva: journalctl --user -u agents-keepawake -f
{
  systemd.user.services.agents-keepawake = {
    Unit = {
      Description = "Keepawake dos agentes — segura o idle da tela enquanto opencode/voz vivem";
      After = [ "graphical-session.target" ];
    };
    Service = {
      Type = "simple";
      ExecStart = "/home/nixos/projects/nixos-ai/scripts/agents-keepawake.sh";
      Restart = "always";
      RestartSec = "10s";
    };
    Install = {
      WantedBy = [ "default.target" ];
    };
  };
}
