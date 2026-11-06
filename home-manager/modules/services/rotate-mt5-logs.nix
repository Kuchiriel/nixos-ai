{
  config,
  lib,
  pkgs,
  ...
}: {
  # (06/11/2026) ROTACAO DOS ARTEFATOS DO HARNESS (repo mt5).
  #
  # POR QUE: cada backtest copia o log do agente do MT5 (agent.log), que chega
  # a **263 MB por run**. Medido no host: 329 agent.logs = **35,2 GB** no repo;
  # um sweep de 342 variantes daria ~90 GB. Disco cheio + RAM apertada +
  # swap esgotado => o desktop do dono congela (foi o que travou em 06/11).
  #
  # O QUE FAZ: chama `backtest/rotate_logs.sh` (trunca os agent.logs grandes
  # GUARDANDO A CAUDA — o final tem as estatisticas e o REPORT.md ja tem o
  # resumo parseado — e remove runs antigos, preservando a evidencia).
  #
  # NAO e' um servico do JARVIS: roda como timer de USUARIO (nao precisa de
  # root) e so toca em ~/projects/mt5/backtest/runs.
  options.services.jarvis.rotateMt5Logs = {
    enable = lib.mkEnableOption "Rotacao diaria dos artefatos do harness mt5 (logs/truncamento)";
    projectPath = lib.mkOption {
      type = lib.types.str;
      default = "/home/nixos/projects/mt5";
      description = "Caminho do repo mt5 (onde esta backtest/rotate_logs.sh).";
    };
    dias = lib.mkOption {
      type = lib.types.int;
      default = 30;
      description = "Runs com mais dias sao removidos (a evidencia vai junto).";
    };
  };

  config = lib.mkIf (options.services.jarvis.rotateMt5Logs.enable) {
    systemd.user.services.mt5-rotate-logs = {
      description = "Rotaciona/trunca os artefatos do harness mt5 (logs grandes)";
      wantedBy = [ "timers.target" ];
      path = [
        pkgs.coreutils
        pkgs.findutils
        pkgs.gnugrep
        pkgs.gawk
      ];
      serviceConfig = {
        Type = "oneshot";
        # nao pode competir com um backtest rodando (o sweep usa o MT5)
        Nice = 10;
      };
      script = ''
        set -euo pipefail
        script="${options.services.jarvis.rotateMt5Logs.projectPath}/backtest/rotate_logs.sh"
        if [ -x "$script" ]; then
          BT_RUNS_DIR="${options.services.jarvis.rotateMt5Logs.projectPath}/backtest/runs" \
            "$script" --dias ${toString options.services.jarvis.rotateMt5Logs.dias}
        fi
      '';
    };

    systemd.user.timers.mt5-rotate-logs = {
      description = "Timer: rotacao diaria dos artefatos do harness mt5";
      wantedBy = [ "timers.target" ];
      timerConfig = {
        OnCalendar = "*-*-* 04:30:00";
        Persistent = true;
        RandomizedDelaySec = 600;
      };
      unit = "mt5-rotate-logs.service";
    };
  };
}
