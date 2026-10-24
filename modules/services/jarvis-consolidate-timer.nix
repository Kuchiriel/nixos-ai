# ═══ JARVIS Memory Consolidate Timer — dedup de memórias, todo dia 03:00 ═══
#
# P1.6 (ROADMAP-INTELIGENCIA): consolidate_memories() agrupa memórias
# duplicadas por embedding (cos > 0.92) e remove redundância — memória
# episódica compacta = recall mais preciso (paper Self-Evolving 2602.06052:
# consolidação noturna, сонно→consolidado; MemGPT: Warm→Cold).
#
# Invoca o SOURCE do repo (python -m jarvis.cli.main) porque o `jarvis`
# instalado no sistema pode estar stale entre rebuilds — o timer nunca
# depende de rebuild. Default é dry-run; o timer aplica (--apply).
# Logs: journalctl -u jarvis-consolidate (e stdout no journal).
{ config, lib, pkgs, ... }:

{
  systemd.services.jarvis-consolidate = {
    description = "JARVIS — dedup/consolidação de memórias episódicas (nightly)";
    after = [ "qdrant.service" ];
    wants = [ "qdrant.service" ];
    serviceConfig = {
      Type = "oneshot";
      User = "nixos";
      # (24/10, P2.7 HB) REFLECT → CONSOLIDATE, nesta ordem: reflect
      # EXTRAI lições do log do dia (hábitos, erros, temas), consolidate
      # DEDUPA em seguida. Um timer, ordem determinística, um journal.
      ExecStart = [
        "/home/nixos/projects/karaok/.venv/bin/python3 /home/nixos/projects/nixos-ai/scripts/jarvis-reflect.py"
        "/home/nixos/projects/karaok/.venv/bin/python3 -m jarvis.cli.main consolidate --apply"
      ];
      WorkingDirectory = "/home/nixos/projects/nixos-ai/modules/ai/jarvis/src";
      Environment = [
        "PYTHONPATH=/home/nixos/projects/nixos-ai/modules/ai/jarvis/src"
      ];
    };
  };
  systemd.timers.jarvis-consolidate = {
    description = "JARVIS memory consolidate diário 03:00";
    wantedBy = [ "timers.target" ];
    timerConfig = {
      OnCalendar = "03:00";
      Persistent = true;
    };
  };
}
