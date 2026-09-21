# chromium-cdp — browser dedicado do JARVIS (CDP :9223, perfil próprio)
#
# Para quê: agentes (jarvis/opencode/Buffy) dirigem um chromium LOGADO
# (fish.audio, colab…) via playwright connect_over_cdp, sem tocar no
# browser do dono. O wrapper `bin/chromium` do Nix sai cedo — apontar pro
# binário real senão o systemd mata o cgroup em ~1min (lição 21/09).
{ config, lib, pkgs, ... }:
let
  cfg = config.services.chromium-cdp;
in
{
  options.services.chromium-cdp = {
    enable = lib.mkEnableOption "Chromium dedicado p/ agentes via CDP (porta 9223)";
    user = lib.mkOption {
      type = lib.types.str;
      default = "nixos";
      description = "Usuário dono do perfil e da sessão gráfica.";
    };
    port = lib.mkOption {
      type = lib.types.int;
      default = 9223;
      description = "Porta do protocolo CDP (9222 é o default do playwright).";
    };
    startUrl = lib.mkOption {
      type = lib.types.str;
      default = "https://fish.audio/pt/app/";
      description = "URL aberta no arranque.";
    };
  };

  config = lib.mkIf (config.services.jarvis.enable && cfg.enable) {
    systemd.user.services.chromium-cdp = {
      description = "JARVIS - Chromium dedicado p/ agentes (CDP :${toString cfg.port})";
      wantedBy = [ "graphical-session.target" ];
      wants = [ "graphical-session.target" ];
      after = [ "graphical-session.target" ];
      serviceConfig = {
        Type = "simple";
        Restart = "on-failure";
        RestartSec = 10;
      };
      environment = {
        DISPLAY = ":0";
        WAYLAND_DISPLAY = "wayland-1";
      };
      # Áudio INTENCIONALMENTE ativo: o dono usa o playback do browser dos
      # agentes pra auditar os wavs gerados (TTS, fish, etc.). NÃO adicionar
      # --mute-audio.
      script = ''
        exec ${pkgs.chromium}/bin/chromium \
          --remote-debugging-port=${toString cfg.port} \
          --user-data-dir=/home/${cfg.user}/.config/jarvis-chromium \
          --no-first-run --no-default-browser-check \
          --start-maximized ${cfg.startUrl}
      '';
    };
  };
}
