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

  config = lib.mkIf cfg.enable {
    # Resumo semanal automático da memória episódica → vault markdown
    # git-syncado (Fase 7). Roda como serviço de usuário: o vault fica em
    # ~/.local/state/jarvis/vault e o git commit é feito pelo próprio jarvis.
    systemd.user.services.jarvis-vault-summarize = {
      description = "JARVIS — resumo de memória de longo prazo (vault)";
      serviceConfig = {
        Type = "oneshot";
        #         ExecStart = "${pkgs.jarvis}/bin/jarvis vault summarize --since ${toString cfg.since}";
        # token do Telegram para notificar conclusão no celular (se existir)
        EnvironmentFile = "-/etc/jarvis-telegram.env";
        # sem stdout no journal: o resultado vai para o vault + memória
        StandardOutput = "journal";
      };
    };

    systemd.user.timers.jarvis-vault-summarize = {
      description = "JARVIS — agenda do resumo de memória";
      wantedBy = ["timers.target"];
      timerConfig = {
        OnCalendar = cfg.calendar;
        Persistent = true;
        # Se o resumo demorar (LLM), não sobrepor com outra execução
        Unit = "jarvis-vault-summarize.service";
      };
    };
  };
}
