# lib/fonts.nix — Single source para fontes
#
# Uso:
#   fonts = import ./fonts.nix { inherit pkgs; };
#   fonts.mono.name       → "JetBrainsMono Nerd Font"
#   fonts.mono.size       → 14
#   fonts.footFont        → "JetBrainsMono Nerd Font:size=14"
#   fonts.cssFamily       → "JetBrainsMono Nerd Font, sans-serif"
{pkgs}: let
  mono = {
    name = "JetBrainsMono Nerd Font";
    size = 14;
    package = pkgs.jetbrains-mono;
  };
  sans = {
    name = "Noto Sans";
    package = pkgs.noto-fonts;
  };
  emoji = {
    name = "Noto Color Emoji";
    package = pkgs.noto-fonts-color-emoji;
  };
in {
  inherit mono sans emoji;

  # Helpers pré-formatados
  footFont = "${mono.name}:size=${toString mono.size}";
  cssFamily = "${mono.name}, sans-serif";
  nerdSymbols = "Symbols Nerd Font";
  allPackages = [mono.package sans.package emoji.package pkgs.nerd-fonts.symbols-only];
}
