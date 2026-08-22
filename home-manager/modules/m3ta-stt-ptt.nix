# Módulo Home Manager para stt-ptt (Push-to-Talk STT)
#
# Configura o stt-ptt do m3ta-nixpkgs com Whisper para reconhecimento
# de fala em tempo real.
#
# Usage em home.nix:
#   m3ta.stt-ptt.enable = true;
#   m3ta.stt-ptt.model = "ggml-large-v3-turbo";
#   m3ta.stt-ptt.language = "pt";
{
  config,
  lib,
  pkgs,
  ...
}:
with lib; let
  cfg = config.m3ta.stt-ptt;
in {
  options.m3ta.stt-ptt = {
    enable = mkEnableOption "Push-to-Talk Speech to Text com Whisper";

    model = mkOption {
      type = types.str;
      default = "ggml-large-v3-turbo";
      description = "Modelo Whisper a usar.";
    };

    language = mkOption {
      type = types.str;
      default = "auto";
      description = "Idioma para reconhecimento de fala.";
    };

    notifyTimeout = mkOption {
      type = types.int;
      default = 3000;
      description = "Timeout da notificação em ms.";
    };
  };

  config = mkIf cfg.enable {
    home.packages = [pkgs.stt-ptt];

    # Configura variáveis de ambiente para stt-ptt
    home.sessionVariables = {
      STT_PTT_MODEL = cfg.model;
      STT_PTT_LANGUAGE = cfg.language;
      STT_PTT_NOTIFY_TIMEOUT = toString cfg.notifyTimeout;
    };
  };
}
