{ config, lib, pkgs, ... }:
# night-comms — a PASSADA DE MADRUGADA DA COMUNICAÇÃO (dono, 07/11).
#
# POR QUE (o dono): o slot das 03:30 era ocupado por `team-suite.timer`,
# um arquivo SOLTO em ~/.config/systemd/user/ (fora do Nix) que rodava os
# bots do `team/` no **projeto de teste de jogo** (o "dungeon"): features
# + validação, de um time de bots que não ajuda em nada no trabalho real.
#
# O dono pediu: achar o serviço de madrugada e adaptá-lo para o NOSSO
# propósito — a comunicação entre os agentes. Agora o slot é do
# `night-comms`:
#   1. lê o BUS de coord (a fonte da verdade dos agentes opencode);
#   2. entrega a cada agente com pendência uma NOTA (noReply=true: entra
#      na sessão, o agente NÃO roda, ZERO token);
#   3. manda o quadro da noite para o dono no Telegram;
#   4. grava o registro em ~/.local/state/jarvis/night-comms.jsonl.
#
# Quem ACORDA o agente é o `agents-watcher.sh` (o watcher do bus) — esta
# passada é o estado da noite: ninguém perde o que chegou de madrugada.
#
# O script (nixos-ai/scripts/night-comms.py) usa o mesmo caminho de
# entrega do resto do harness (coord_roster.send_message: bus + wake).
{
  # MIGRAÇÃO (uma vez): o `team-suite.timer` (o JOGO DE TESTE) era um unit
  # SOLTO em ~/.config/systemd/user — fora do Nix (e fora do git). O dono
  # mandou usar o slot das 03:30 para a comunicação. Mesma técnica do
  # bench-nightly: MOVER (não apagar — fica como evidência) para o estado,
  # e deixar o home-manager criar os symlinks do night-comms.
  home.activation."a-migrate-legacy-team-suite" = lib.mkIf true
    (lib.hm.dag.entryBefore [ "checkFilesChanged" ] ''
      legacy_dir="$HOME/.local/state/jarvis/legacy-team-suite-2026-11-07"
      mkdir -p "$legacy_dir"
      for f in team-suite.service team-suite.timer; do
        p="$HOME/.config/systemd/user/$f"
        if [ -e "$p" ] && [ ! -L "$p" ]; then
          mv "$p" "$legacy_dir/$f"
        fi
      done
      for f in team-suite.timer; do
        p="$HOME/.config/systemd/user/timers.target.wants/$f"
        if [ -e "$p" ] && [ ! -L "$p" ]; then
          mv "$p" "$legacy_dir/$f.wants"
        fi
      done
      systemctl --user disable --now team-suite.timer >/dev/null 2>&1 || true
    '');

  systemd.user.services = {
    night-comms = {
      Unit = {
        Description = "Madrugada: quadro do bus + pendencias entregues aos agentes (nota, zero token)";
      };
      Service = {
        Type = "oneshot";
        WorkingDirectory = "/home/nixos/projects/nixos-ai";
        # O launcher do JARVIS resolve o PYTHONPATH (mesmo env do MCP/CLI:
        # nunca divergir os tres — o CLI perdia o `requests` e o rag-index
        # pendurava sem erro).
        ExecStart = "/run/current-system/sw/bin/bash -c 'source /home/nixos/projects/nixos-ai/modules/ai/jarvis/jarvis-env.sh && exec \"$JARVIS_PY\" /home/nixos/projects/nixos-ai/scripts/night-comms.py'";
        Nice = 10;
        # A passada é leve (le o bus, entrega notas, avisa o Telegram).
        TimeoutStartSec = 300;
      };
    };
  };

  systemd.user.timers = {
    night-comms = {
      Unit = {
        Description = "Madrugada da comunicacao (00:00, slot do antigo team-suite)";
      };
      Timer = {
        OnCalendar = "00:00";
        Persistent = true;
        RandomizedDelaySec = 600;
      };
      Install = {
        WantedBy = [ "timers.target" ];
      };
    };
  };
}
