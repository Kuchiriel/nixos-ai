{
  config,
  lib,
  pkgs,
  ...
}: let
  cfg = config.services.jarvis-telegram;
in {
  options.services.jarvis-telegram = {
    enable = lib.mkEnableOption "canal Telegram do JARVIS (aprovação assíncrona — Fase 9)";

    environmentFile = lib.mkOption {
      type = lib.types.path;
      default = "/etc/jarvis-telegram.env";
      description = ''
        Arquivo com as credenciais (chmod 600, fora do repo/store):
          JARVIS_TELEGRAM_TOKEN=<token do BotFather>
          JARVIS_TELEGRAM_CHAT_ID=<seu chat_id (ou lista, vírgula)>
        Para descobrir seu chat_id: mande uma mensagem para o bot e chame
        https://api.telegram.org/bot<TOKEN>/getUpdates (campo chat.id).
        O `-` no EnvironmentFile faz o systemd IGNORAR a ausência do arquivo:
        sem token o serviço fica parado até você criar o bot e preencher o
        arquivo — depois é só `sudo systemctl restart jarvis-telegram`.
      '';
    };

    user = lib.mkOption {
      type = lib.types.str;
      default = "nixos";
      description = "Usuário dono do estado do JARVIS (memória/vault/audit).";
    };
  };

  config = lib.mkIf (config.services.jarvis.enable && cfg.enable) {
    systemd.services.jarvis-telegram = {
      description = "JARVIS — canal Telegram (aprovação assíncrona)";
      after = ["network-online.target" "jarvis.target"];
      wants = ["network-online.target"];
      partOf = ["jarvis.target"];
      wantedBy = ["jarvis.target"];
      serviceConfig = {
        Type = "simple";
        User = cfg.user;
        EnvironmentFile = "-${cfg.environmentFile}";
        ExecStart = "${pkgs.jarvis}/bin/jarvis telegram";
        Restart = "on-failure";
        RestartSec = "5";
        TimeoutStopSec = "10";
      };
    };
  };
}
