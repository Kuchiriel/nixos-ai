{ config, lib, pkgs, ... }:

let
  cfg = config.services.jarvis-heal;
in
{
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

  config = lib.mkIf cfg.enable {
    # O usuário precisa conseguir restartar os serviços vigiados: em modo user,
    # só reinicia serviços do próprio usuário; para serviços do sistema, ou
    # `runAsRoot = true` (serviço systemd do sistema) ou sudo NOPASSWD restrito
    # à allowlist (llama-cpp-server, llama-cpp-embeddings, qdrant).
    systemd.services.jarvis-heal = lib.mkIf cfg.runAsRoot {
      description = "JARVIS self-heal (root) — detecta serviços down e repara";
      wantedBy = [ "multi-user.target" ];
      serviceConfig = {
        ExecStart = "${pkgs.jarvis}/bin/jarvis heal --watch --interval ${toString cfg.interval} --cooldown ${toString cfg.cooldown}";
        Environment = [ "JARVIS_JSONL=0" ];
        Restart = "on-failure";
        RestartSec = "30";
        # Audit/lições da memória ficam em ~root/.local/state/jarvis
      };
    };

    systemd.user.services.jarvis-heal = lib.mkIf (!cfg.runAsRoot) {
      description = "JARVIS self-heal — detecta serviços down e repara";
      wantedBy = [ "default.target" ];
      serviceConfig = {
        ExecStart = "${pkgs.jarvis}/bin/jarvis heal --watch --interval ${toString cfg.interval} --cooldown ${toString cfg.cooldown}";
        Environment = [ "JARVIS_JSONL=0" ];
        Restart = "on-failure";
        RestartSec = "30";
      };
    };
  };
}
