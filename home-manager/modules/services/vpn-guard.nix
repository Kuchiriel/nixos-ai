# vpn-guard.nix — o guard de VPN (Mullvad x Tailscale) como unit DECLARATIVA
#
# O QUE ERA (medido 19/11, auditoria histórica)
#   As units `vpn-guard.service` e `vpn-guard.timer` viviam SOLTAS em
#   ~/.config/systemd/user (arquivos comuns, 143 B, sem symlink de Nix):
#   foram instaladas à mão durante o conserto do Mullvad (18/11) e nenhum
#   rebuild as recriaria. Numa máquina montada do zero o bypass da tailnet
#   cairia em silêncio de novo.
#
# O QUE ESTE MÓDULO FAZ
#   Declara o timer de 15 min que roda `scripts/vpn-guard fix`. O script:
#     1. lê o sinal real da tailnet (`tailscale status --json`, nunca o PID);
#     2. repara o ruleset `mullvad_tailscale` ANTES de desligar a VPN;
#     3. registra a decisão em ~/.local/state/vpn-guard/stopped;
#     4. não derruba a VPN se a tailnet estiver sadia.
#   `check` sai 0 sem agir quando não há nada a fazer (idempotente).
#
# MIGRAÇÃO (uma vez)
#   Mesma técnica do night-comms/team-suite: MOVER a unit solta para o
#   estado (evidência), senão o home-manager aborta o rebuild com "file in
#   the way" ao criar o symlink.
#
# ATIVAR
#   cd ~/projects/nixos-ai && ./rebuild-host.sh   (autorização do dono)
#   Depois: systemctl --user list-timers vpn-guard.timer
{ config, lib, pkgs, ... }:

let
  repo = config.home.homeDirectory + "/projects/nixos-ai";
  legacy = "${config.home.homeDirectory}/.local/state/jarvis/legacy-vpn-guard-2026-11-19";
in
{
  home.activation."a-migrate-legacy-vpn-guard" = lib.mkIf true
    (lib.hm.dag.entryBefore [ "checkFilesChanged" ] ''
      legacy_dir="${legacy}"
      mkdir -p "$legacy_dir"
      for f in vpn-guard.service vpn-guard.timer; do
        p="$HOME/.config/systemd/user/$f"
        if [ -e "$p" ] && [ ! -L "$p" ]; then
          mv "$p" "$legacy_dir/$f"
        fi
      done
      p="$HOME/.config/systemd/user/timers.target.wants/vpn-guard.timer"
      if [ -e "$p" ] && [ ! -L "$p" ]; then
        mv "$p" "$legacy_dir/vpn-guard.timer.wants"
      fi
    '');

  systemd.user.services.vpn-guard = {
    Unit = {
      Description = "Guarda 1 VPN por vez (Mullvad x Tailscale)";
    };
    Service = {
      Type = "oneshot";
      # Caminho do repo, como o jarvis-consolidate: o timer nunca depende de
      # rebuild para pegar a versão do script.
      ExecStart = "${repo}/scripts/vpn-guard fix";
      WorkingDirectory = repo;
    };
  };

  systemd.user.timers.vpn-guard = {
    Unit = {
      Description = "Checa a tailnet a cada 15 min (bypass do Mullvad)";
    };
    Timer = {
      OnBootSec = "3min";
      OnUnitActiveSec = "15min";
      Persistent = true;
    };
    Install = {
      WantedBy = [ "timers.target" ];
    };
  };
}
