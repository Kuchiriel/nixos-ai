{ config, lib, pkgs, ... }:
# agents-watcher — O ÚNICO serviço dos agentes (consolidação 17/10, dono:
# "consolide tudo em um script e um serviço só, agnóstico de projeto").
# Substitui: agents-heartbeat-watchdog (service+timer, o ressuscitador do
# watcher), agent-progress-heartbeat (service+timer) e o agent-keepawake
# (hypridle.nix — o keepawake agora vive DENTRO do script, 24h).
#
# O systemd É o watchdog agora (Restart=always): nada de timer de
# reanimação — o vício de timers em cascata foi o que o dono mandou
# extinguir. O script se auto-calma quando não há janelas "OC |"
# (nada a acordar = ciclo silencioso, zero wtype-no-nada).
#
# ExecStart aponta pro CAMINHO VIVO do repo (mesmo padrão do antigo
# progress-heartbeat): editar o script NÃO pede rebuild; o serviço
# só descreve o ciclo de vida (restart, logs via journalctl --user).
#
# Prova viva: journalctl --user -u agents-watcher -f
{
  systemd.user.services.agents-watcher = {
    Unit = {
      Description = "Watcher único dos agentes (keepawake + eventos + wake de idle) — agnóstico de projeto";
      After = [ "graphical-session.target" ];
    };
    Service = {
      Type = "simple";
      ExecStart = "/home/nixos/projects/nixos-ai/scripts/agents-watcher.sh";
      Restart = "always";
      RestartSec = "30s";
    };
    Install.WantedBy = [ "default.target" ];
  };
}
