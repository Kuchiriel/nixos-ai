{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.services.jarvis-webui-frontend;
  frontendDir = "/home/nixos/projects/nixos-ai/modules/ai/jarvis/src/jarvis/webui/frontend";
in {
  options.services.jarvis-webui-frontend = {
    enable = lib.mkEnableOption "Frontend SvelteKit do mission-control (preview da build de produção)";

    port = lib.mkOption {
      type = lib.types.port;
      default = 5173;
      description = "Porta do preview SvelteKit.";
    };
  };

  config = lib.mkIf (config.services.jarvis.enable && cfg.enable) {
    systemd.services.jarvis-webui-frontend = {
      description = "JARVIS — frontend mission-control (SvelteKit preview)";
      after = ["network-online.target" "jarvis-webui.service" "jarvis.target"];
      wants = ["network-online.target"];
      bindsTo = ["jarvis-webui.service"];
      partOf = ["jarvis.target"];
      wantedBy = ["jarvis.target" "multi-user.target"];
      serviceConfig = {
        Type = "simple";
        User = "nixos";
        WorkingDirectory = frontendDir;
        # Build de produção via `npm run build` no repo; preview serve o
        # bundle. Após editar o frontend: rebuild local + restart do serviço.
        ExecStart = "${pkgs.nodejs}/bin/npm run preview -- --port ${toString cfg.port} --host 127.0.0.1";
        Restart = "on-failure";
        RestartSec = "5";
        TimeoutStopSec = "10";
        ProtectSystem = "strict";
        PrivateTmp = true;
        NoNewPrivileges = true;
        RestrictSUIDSGID = true;
        MemoryMax = "1G";
        TasksMax = 64;
      };
    };
  };
}
