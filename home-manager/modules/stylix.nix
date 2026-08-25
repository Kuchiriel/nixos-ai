{
  pkgs,
  lib,
  ...
}: {

  # Força o bypass de fontes para passar por cima do bloco interno do Stylix
  fonts.fontconfig.enable = lib.mkForce true;

  home.packages = with pkgs; [
    dejavu_fonts
    jetbrains-mono
    noto-fonts
    noto-fonts-lgc-plus
    texlivePackages.hebrew-fonts
    noto-fonts-color-emoji
    font-awesome
    powerline-fonts
    powerline-symbols
    nerd-fonts.symbols-only
  ];

  stylix = {
    enable = true;
    polarity = "dark";
    # Paleta futurista em tons de azul escuro e ciano (Estética HUD/Jarvis)
    base16Scheme = "${pkgs.base16-schemes}/share/themes/oceanicnext.yaml"; # Exemplo de esquema azulado
    #base16Scheme = "${pkgs.base16-schemes}/share/themes/horizon-dark.yaml";

    targets = {
      neovim.enable = false;
      waybar.enable = false;
      wofi.enable = false;
      hyprland.enable = false;
      foot.enable = false; # Gerenciado por lib/fonts.nix
      hyprlock.enable = false;
    };

    cursor = {
      name = "DMZ-Black";
      size = 24;
      package = pkgs.vanilla-dmz;
    };

    fonts = {
      emoji = {
        name = "Noto Color Emoji";
        package = pkgs.noto-fonts-color-emoji;
      };
      monospace = {
        name = "JetBrains Mono";
        package = pkgs.jetbrains-mono;
      };
      sansSerif = {
        name = "Noto Sans";
        package = pkgs.noto-fonts;
      };
      serif = {
        name = "Noto Serif";
        package = pkgs.noto-fonts;
      };

      sizes = {
        terminal = 13;
        applications = 11;
      };
    };

    icons = {
      enable = true;
      package = pkgs.papirus-icon-theme;
      dark = "Papirus-Dark";
      light = "Papirus-Light";
    };

    image = pkgs.runCommand "solid-blue.png" {nativeBuildInputs = [pkgs.imagemagick];} ''
      magick convert -size 1x1 xc:blue $out
    '';
  };
}
