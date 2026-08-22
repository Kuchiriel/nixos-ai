# Módulo Home Manager para stt-ptt (Push-to-Talk STT)
#
# Configura o stt-ptt do m3ta-nixpkgs com Whisper para reconhecimento
# de fala em tempo real. Usa wtype para simular tecla de atalho.
#
# Usage em home.nix:
#   cli.stt-ptt.enable = true;
#   cli.stt-ptt.model = "ggml-large-v3-turbo";
#   cli.stt-ptt.language = "pt";
{
  config,
  lib,
  pkgs,
  ...
}:
with lib; let
  cfg = config.m3ta.stt-ptt;

  # Re-exporta o módulo do m3ta-nixpkgs
  m3taModule = import "${./../../m3ta-nixpkgs}/modules/home-manager/cli/stt-ptt.nix";
in {
  imports = [m3taModule];

  options.m3ta.stt-ptt = {
    enable = mkAliasOption [] "cli.stt-ptt.enable";
    whisperPackage = mkAliasOption [] "cli.stt-ptt.whisperPackage";
    model = mkOption {
      type = types.str;
      default = "ggml-large-v3-turbo";
      description = "Modelo Whisper a usar.";
    };
    notifyTimeout = mkAliasOption [] "cli.stt-ptt.notifyTimeout";
    language = mkAliasOption [] "cli.stt-ptt.language";
  };

  config = mkIf cfg.enable {
    home.packages = [pkgs.stt-ptt];

    # Configura atalho de teclado para stt-ptt (Ctrl+Space)
    wayland.sessionVariables.STT_PTT_KEY = "space";
    wayland.sessionVariables.STT_PTT_MOD = "ctrl";

    # Garante que whisper-cpp model está disponível
    xdg.dataHome = let
      modelDir = "${config.xdg.dataHome}/stt-ptt/models";
    in pkgs.runCommand "stt-ptt-models" {} ''
      mkdir -p "$out"
    '';
  };
}
