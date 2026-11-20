{ config, lib, pkgs, ... }:
# (20/11) DATASET DE CONVERSAS DA FROTA — captura automática e append-only.
#
# POR QUE: o botão Bus do agent hub é só a ponta visível. O valor está no
# registro durável: ele vira dataset para auditoria, detecção de padrões de
# falha e melhorias da frota. Sem captura automática, só existe o que estava
# na tela no momento em que alguém olhou.
#
# FONTE: scripts/bus-paths.py agrega os 3 caminhos reais do bus:
#   bus-gh#100 (issue durável), coord-mcp (MCP da LAN), hub-wake (wakes do hub).
# SAÍDA: ~/.local/state/jarvis/bus-journal/YYYY-MM-DD.jsonl + manifest.json.
# IDEMPOTENTE: id = sha256(path|ts|from|kind|text); repetir não duplica.
# NÃO toca Qdrant, opencode.db, serviços de produção nem chaves.
{
  systemd.user.services.bus-journal = {
    Unit = {
      Description = "JARVIS — captura append-only das conversas da frota (dataset de melhorias)";
      After = [ "network-online.target" ];
      Wants = [ "network-online.target" ];
    };
    Service = {
      Type = "oneshot";
      WorkingDirectory = "/home/nixos/projects/nixos-ai";
      ExecStart = "/run/current-system/sw/bin/bash -c 'source /home/nixos/projects/nixos-ai/modules/ai/jarvis/jarvis-env.sh && \"$JARVIS_PY\" /home/nixos/projects/nixos-ai/scripts/bus-paths.py 100 --record >/dev/null'";
      Nice = 10;
      IOSchedulingClass = "idle";
      TimeoutStartSec = 180;
    };
  };

  systemd.user.timers.bus-journal = {
    Unit = {
      Description = "Captura periódica do bus da frota para o dataset local";
    };
    Timer = {
      OnBootSec = "5min";
      OnUnitActiveSec = "5min";
      Persistent = true;
      RandomizedDelaySec = 30;
    };
    Install = {
      WantedBy = [ "timers.target" ];
    };
  };
}
