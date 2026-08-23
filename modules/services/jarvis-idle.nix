{
  config,
  lib,
  ...
}: let
  cfg = config.services.jarvis-idle;
in {
  options.services.jarvis-idle = {
    enable = lib.mkEnableOption "modo idle do JARVIS (self-knowledge quando o sistema está ocioso)";

    interval = lib.mkOption {
      type = lib.types.str;
      default = "5min";
      description = "Intervalo do timer systemd entre execuções do worker.";
    };

    maxLoad = lib.mkOption {
      type = lib.types.float;
      default = 2.0;
      description = "Teto de carga média (1min) para considerar o sistema ocioso.";
    };

    idleCheck = lib.mkOption {
      type = lib.types.bool;
      default = true;
      description = ''
        Consulta o IdleHint do logind além da carga. Com o logind pendurado
        (VM pós-upgrade sem reboot), o worker nunca trava: timeout curto e
        fallback para a decisão por carga.
      '';
    };

    user = lib.mkOption {
      type = lib.types.str;
      default = "nixos";
      description = "Usuário dono do state_dir do JARVIS (heartbeats do idle).";
    };
  };

  config = lib.mkIf cfg.enable {
    # Auto-manutenção em segundo plano (Fase 4a). O worker roda a cada poucos
    # minutos e executa NO MÁXIMO uma tarefa de self-knowledge por vez quando:
    #   - carga < maxLoad (gate primário e confiável)
    #   - IdleHint do logind (quando responde; senão decide pela carga)
    # O yield é automático: CPUWeight=1/Nice=19/IO-idle fazem o kernel ceder
    # a CPU quando o usuário (ou um jogo) precisa — sem detectar jogo.
    systemd.user.services.jarvis-idle-worker = {
      description = "JARVIS — worker de auto-manutenção em idle (self-knowledge)";
      serviceConfig = {
        Type = "oneshot";
        #         ExecStart = "${pkgs.jarvis}/bin/jarvis idle worker --max-load ${toString cfg.maxLoad}" + lib.optionalString (!cfg.idleCheck) " --no-idle-check";
        # token do Telegram para notificar conclusão no celular (se existir)
        EnvironmentFile = "-/etc/jarvis-telegram.env";
        # yield automático: nunca compete com o usuário / jogos
        CPUWeight = 1;
        Nice = 19;
        IOSchedulingClass = "idle";
        IOSchedulingPriority = 7;
        # sem stdout no journal: o resultado vai para o heartbeat JSON
        StandardOutput = "journal";
      };
    };

    systemd.user.timers.jarvis-idle-worker = {
      description = "JARVIS — agenda do worker de idle";
      wantedBy = ["timers.target"];
      timerConfig = {
        OnUnitActiveSec = cfg.interval;
        # se uma execução demorar (benchmark), não sobrepor
        Unit = "jarvis-idle-worker.service";
      };
    };
  };
}
