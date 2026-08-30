{
  config,
  lib,
  pkgs,
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

  config = lib.mkIf (config.services.jarvis.enable && cfg.enable) {
    systemd.user.services.jarvis-idle-worker = {
      description = "JARVIS — worker de auto-manutenção em idle (self-knowledge)";
      serviceConfig = {
        Type = "oneshot";
        EnvironmentFile = "-/etc/jarvis-telegram.env";
        ExecStart = "${pkgs.jarvis}/bin/jarvis idle worker";
        # ── Sandboxing ──
        ProtectSystem = "strict";       # /usr e /boot read-only
        PrivateTmp = true;                # /tmp privado
        NoNewPrivileges = true;           # Sem escalada de privilégio
        RestrictSUIDSGID = true;          # Sem arquivos SUID/SGID
        # ── Resource limits ──
        CPUWeight = 1;                    # Baixa prioridade CPU
        Nice = 19;                        # Lowest priority
        IOSchedulingClass = "idle";       # I/O idle
        IOSchedulingPriority = 7;         # Lowest I/O priority
        MemoryMax = "512M";               # Max 512MB RAM
        TasksMax = 64;                    # Max 64 tasks
        StandardOutput = "journal";
      };
    };

    systemd.user.timers.jarvis-idle-worker = {
      description = "JARVIS — agenda do worker de idle";
      wantedBy = ["timers.target"];
      timerConfig = {
        OnUnitActiveSec = cfg.interval;
        Unit = "jarvis-idle-worker.service";
      };
    };
  };
}
