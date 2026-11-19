# duplex-voice.nix — o cliente de voz duplex como unit DECLARATIVA
#
# O QUE ERA (medido 19/11, auditoria-runtime)
#   A unit `duplex-voice.service` vivia SOLTA em
#   ~/.config/systemd/user/duplex-voice.service (arquivo comum, 618 B,
#   symlink de Nix nenhum): nenhum .nix do repo a declarava, nenhum
#   rebuild a recria, e `nix flake check` não via a existência dela. Uma
#   máquina montada do zero ficaria SEM VOZ, e o `systemctl status` mentia
#   sobre a origem da unit.
#
# O QUE ESTE MÓDULO FAZ
#   Declara a unit do cliente duplex (systemd de USUÁRIO), com o mesmo
#   contrato da unit solta e dois acertos:
#     - espera o ASR (:8097, whisper-server) e o default (:8092, MTP+LoRA);
#     - roda scripts/duplex-voice-run.sh (que resolve o LD_LIBRARY_PATH do
#       venv karaok e sobe os filhos ttsd/asrd);
#     - Restart=always: a voz é o serviço que o dono mais sente faltar;
#     - CAMINHOS ABSOLUTOS do store: a unit solta usava `/bin/sh`, `timeout`,
#       `seq` e `sleep` do PATH. Num systemd de usuário o PATH é mínimo e
#       esses comandos podem não existir — a espera viraria "porta fechada"
#       sem causa.
#
# POR QUE O DEFAULT PRECISA VIR PRIMEIRO
#   O cliente não sobe sem backend: o ExecStartPre espera a :8092 (o MTP com
#   o LoRA do registry, models.nix). Se o default não subir, a unit fica
#   esperando e o heal é quem deve levantar o default (ver modules/services/
#   jarvis-heal.nix e HEALABLE_UNITS em modules/ai/jarvis/src/jarvis/core/
#   heal.py).
#
# NÃO AFETAR
#   A unit é de USUÁRIO (fica em ~/.config/systemd/user). O default (:8092) é
#   de SISTEMA (modules/services/llama-uncensored.nix, gerado de models.nix).
#   Este módulo não toca no default: só no cliente.
#
# ATIVAR
#   O dono rebuilda:  cd ~/projects/nixos-ai && ./rebuild-host.sh
#   Depois: systemctl --user status duplex-voice.service
{ config, pkgs, lib, ... }:

let
  repo = "/home/nixos/projects/nixos-ai";
  # (19/11) Mesma espera da unit solta: 60 x 2 s = 120 s pelo ASR e pelo
  # default. Sem isso o cliente nasce surdo e só descobre minutos depois.
  # (19/11 P0) systemd NAO aceita valor multilinha em ExecStartPre: as linhas
  # seguintes sao lidas como novas diretivas e o parser fecha com
  # "expected entry key name but got '/'". Uma linha com ';' preserva a
  # semantica da unit solta (legacy) e os caminhos absolutos do store.
  waitPort = port: "for i in $(seq 1 60); do ${pkgs.coreutils}/bin/timeout 1 ${pkgs.bash}/bin/bash -c \"exec 3<>/dev/tcp/127.0.0.1/${toString port}\" && exit 0; ${pkgs.coreutils}/bin/sleep 2; done; exit 1";
in
{
  # (19/11) MIGRAÇÃO: a unit nasceu SOLTA em ~/.config/systemd/user. O
  # home-manager aborta o rebuild com "file in the way" quando o symlink
  # encontra um arquivo comum — mover para o estado preserva a evidência e
  # deixa o rebuild passar (mesma técnica do night-comms/team-suite).
  home.activation."a-migrate-legacy-duplex-voice" = lib.mkIf true
    (lib.hm.dag.entryBefore [ "checkFilesChanged" ] ''
      legacy_dir="$HOME/.local/state/jarvis/legacy-duplex-voice-2026-11-19"
      mkdir -p "$legacy_dir"
      p="$HOME/.config/systemd/user/duplex-voice.service"
      if [ -e "$p" ] && [ ! -L "$p" ]; then
        mv "$p" "$legacy_dir/duplex-voice.service"
      fi
    '');

  systemd.user.services.duplex-voice = {
    Unit = {
      # (19/11) o texto dizia "gate kernel v8"; o registry (models.nix) aponta
      # o v9 desde 14/11. A descrição não muda comportamento, mas mentia.
      Description = "JARVIS Duplex Voice (4B-MTP gate kernel v9 + RNNoise mic)";
      After = [ "default.target" ];
      Wants = [ "default.target" ];
    };
    Service = {
      Type = "simple";
      ExecStartPre = [
        "${pkgs.bash}/bin/bash -c '${waitPort 8097}'"
        "${pkgs.bash}/bin/bash -c '${waitPort 8092}'"
      ];
      ExecStart = "${repo}/scripts/duplex-voice-run.sh --debug";
      Restart = "always";
      RestartSec = 5;
      StandardOutput = "journal";
      StandardError = "journal";
    };
    Install = { WantedBy = [ "default.target" ]; };
  };
}
