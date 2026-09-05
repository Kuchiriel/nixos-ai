{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.services.jarvis-webui;
in {
  options.services.jarvis-webui = {
    enable = lib.mkEnableOption "WebUI mission-control do JARVIS (FastAPI + SvelteKit)";

    port = lib.mkOption {
      type = lib.types.port;
      default = 8090;
      description = "Porta HTTP da WebUI.";
    };

    user = lib.mkOption {
      type = lib.types.str;
      default = "nixos";
      description = "Usuário dono do estado do JARVIS (tasks, memória, vault).";
    };
  };

  config = lib.mkIf (config.services.jarvis.enable && cfg.enable) {
    systemd.services.jarvis-webui = {
      description = "JARVIS — WebUI mission-control (tasks, serviços, chat, MCP)";
      after = ["network-online.target" "llama-cpp-server.service" "qdrant.service" "jarvis.target"];
      wants = ["network-online.target"];
      partOf = ["jarvis.target"];
      wantedBy = ["jarvis.target" "multi-user.target"];
      serviceConfig = {
        Type = "simple";
        User = cfg.user;
        ExecStart = "${pkgs.jarvis}/bin/jarvis-webui --port ${toString cfg.port}";
        Restart = "on-failure";
        RestartSec = "5";
        TimeoutStopSec = "10";
        # ── Sandboxing ──
        ProtectSystem = "strict";       # /usr e /boot read-only
        PrivateTmp = true;                # /tmp privado
        NoNewPrivileges = true;           # Sem escalada de privilégio
        RestrictSUIDSGID = true;          # Sem arquivos SUID/SGID
        # ── Resource limits ──
        MemoryMax = "1G";                 # FastAPI leve
        TasksMax = 64;
      };
    };
  };
}
