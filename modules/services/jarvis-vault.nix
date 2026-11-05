{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.services.jarvis-vault;
in {
  options.services.jarvis-vault = {
    enable = lib.mkEnableOption "timer de resumo da memória de longo prazo do JARVIS (jarvis vault summarize)";

    since = lib.mkOption {
      type = lib.types.int;
      default = 7;
      description = "Janela (dias) de eventos a resumir.";
    };

    calendar = lib.mkOption {
      type = lib.types.str;
      default = "Sun *-*-* 03:00:00";
      description = "Agenda systemd (OnCalendar) do resumo semanal.";
    };

    user = lib.mkOption {
      type = lib.types.str;
      default = "nixos";
      description = "Usuário dono do vault (o mesmo do state_dir do JARVIS).";
    };
  };

  config = lib.mkIf (config.services.jarvis.enable && cfg.enable) {
    systemd.user.services.jarvis-vault-summarize = {
      description = "JARVIS — resumo de memória de longo prazo (vault)";
      serviceConfig = {
        Type = "oneshot";
        # (04/11, sweep) ExecStart AUSENTE: a unit era inválida (o
        # formatter comeu a linha no commit 6cd9c147) → no nixos-lab
        # (enable=true) o timer semanal disparava uma unit sem comando.
        # O CLI existe: `jarvis vault summarize --since N` (cli/main.py:1259).
        ExecStart = "${pkgs.jarvis}/bin/jarvis vault summarize --since ${toString cfg.since}";
        EnvironmentFile = "-/etc/jarvis-telegram.env";
        StandardOutput = "journal";
        RemainAfterExit = true;
      };
    };

    systemd.user.timers.jarvis-vault-summarize = {
      description = "JARVIS — agenda do resumo de memória";
      wantedBy = ["timers.target"];
      timerConfig = {
        OnCalendar = cfg.calendar;
        Persistent = true;
        Unit = "jarvis-vault-summarize.service";
      };
    };
  };
}
