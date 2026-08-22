{ config, lib, pkgs, ... }:

let
  cfg = config.services.jarvis-telegram;
in
{
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
        sem token o serviço fica parado (o CLI sai limpo) até você criar o
        bot e preencher o arquivo — depois é só `sudo systemctl restart
        jarvis-telegram` (ou o próximo rebuild).
      '';
    };

    user = lib.mkOption {
      type = lib.types.str;
      default = "nixos";
      description = "Usuário dono do estado do JARVIS (memória/vault/audit).";
    };
  };

  config = lib.mkIf cfg.enable {
    # Bot em long-polling (sem webhook — funciona atrás de NAT). Restart
    # on-failure: o self-heal do systemd cobre quedas de rede do Telegram.
    systemd.services.jarvis-telegram = {
      description = "JARVIS — canal Telegram (aprovação assíncrona)";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      wantedBy = [ "multi-user.target" ];
#       path = [ pkgs.jarvis ];
      serviceConfig = {
        Type = "simple";
        User = cfg.user;
        # `-` = não falha se o arquivo ainda não existe (aguarda o token)
        EnvironmentFile = "-${cfg.environmentFile}";
        #ExecStart = "${pkgs.jarvis}/bin/jarvis telegram";
        Restart = "on-failure";
        RestartSec = "5";
        # sem timeout: long-polling mantém a conexão aberta
        TimeoutStopSec = "10";
      };
    };
  };
}
