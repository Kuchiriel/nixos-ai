{
  config,
  lib,
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
        EnvironmentFile = "-/etc/jarvis-telegram.env";
        StandardOutput = "journal";
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
