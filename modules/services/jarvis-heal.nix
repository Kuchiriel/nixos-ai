{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.services.jarvis-heal;
  execCmd = "${pkgs.jarvis}/bin/jarvis heal --watch --interval ${toString cfg.interval} --cooldown ${toString cfg.cooldown}";
in {
  options.services.jarvis-heal = {
    enable = lib.mkEnableOption "daemon de self-heal do JARVIS (jarvis heal --watch)";

    interval = lib.mkOption {
      type = lib.types.int;
      default = 60;
      description = "Intervalo (s) entre verificações de saúde.";
    };

    cooldown = lib.mkOption {
      type = lib.types.int;
      default = 300;
      description = "Cooldown (s) entre restarts do mesmo serviço (anti-loop).";
    };

    user = lib.mkOption {
      type = lib.types.str;
      default = "nixos";
      description = "Usuário que roda o daemon (precisa de permissão para restartar os serviços).";
    };

    runAsRoot = lib.mkOption {
      type = lib.types.bool;
      default = false;
      description = ''
        Roda como serviço do SISTEMA (root) em vez de user. Necessário para
        restartar serviços do sistema (llama-cpp-server, qdrant) sem sudo.
      '';
    };
  };

  config = lib.mkIf (config.services.jarvis.enable && cfg.enable) {
    systemd.services.jarvis-heal = lib.mkIf cfg.runAsRoot {
      description = "JARVIS self-heal (root) — detecta serviços down e repara";
      after = ["jarvis.target"];
      partOf = ["jarvis.target"];
      wantedBy = ["jarvis.target"];
      serviceConfig = {
        Environment = ["JARVIS_JSONL=0"];
        ExecStart = execCmd;
        Restart = "on-failure";
        RestartSec = "30";
      };
    };

    systemd.user.services.jarvis-heal = lib.mkIf (!cfg.runAsRoot) {
      description = "JARVIS self-heal — detecta serviços down e repara";
      wantedBy = ["default.target"];
      serviceConfig = {
        Environment = ["JARVIS_JSONL=0"];
        ExecStart = execCmd;
        Restart = "on-failure";
        RestartSec = "30";
      };
    };
  };
}
