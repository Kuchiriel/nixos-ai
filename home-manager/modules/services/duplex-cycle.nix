# duplex-cycle.nix — esteira de qualidade do duplex no modo automático
#
# O QUE FAZ
#   Roda scripts/duplex-cycle.py uma vez por semana (domingo 05:00):
#   sweep -> conveyor -> gate heldout1/2 -> agent; grava reports/duplex-cycle/,
#   dá append no diário de medições e captura regressões com exit code.
#   Nenhuma mudança no duplex em produção: só bate no :8092/:8097 e lê logs.
#
# COMO ATIVAR
#   nix chama home-manager (via rebuild ou nh). Para refazer:
#       cd ~/projects/nixos-ai && ./rebuild-host.sh
#   Depois: systemctl --user start duplex-cycle.service para um run imediato.
#
# NÃO AFETAR
#   Se o ciclo acusasse vermelho numa sincronização de produção eventual
#   (o script nunca pula a produção: tudo é leitura), nada quebra. Só sai
#   com exit code 1 e um report em reports/duplex-cycle/<ts>/SUMMARY.md.

{ config, pkgs, lib, ... }:

let
  repo = "/home/nixos/projects/nixos-ai";
in
{
  systemd.user.services.duplex-cycle = {
    Unit = {
      Description = "DUPLEX — esteira de qualidade automática (roda o ciclo completo)";
    };
    Service = {
      Type = "oneshot";
      WorkingDirectory = repo;
      ExecStart = "${pkgs.python3}/bin/python3 ${repo}/scripts/duplex-cycle.py";
      Environment = [ "PATH=${pkgs.lib.makeBinPath [ pkgs.coreutils pkgs.util-linux pkgs.gawk pkgs.gnugrep ]}" ];
    };
  };

  systemd.user.timers.duplex-cycle = {
    Unit = { Description = "DUPLEX — esteira de qualidade semanal"; };
    Timer = {
      OnCalendar = "Sun *-*-* 05:00:00";
      Persistent = true;
    };
    Install = { WantedBy = [ "timers.target" ]; };
  };
}
