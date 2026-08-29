# lib/default.nix — project lib exports
#
# Uso em módulos (quando disponível via flake):
#   colors = lib.nixos-ai.colors;
#   fonts = lib.nixos-ai.fonts;
#   colors = projectLib.colors;  (via extraSpecialArgs)
#   fonts = projectLib.fonts;    (via extraSpecialArgs)
{
  lib,
  pkgs,
}: {
  # Port management utilities
  ports = import ./ports.nix {inherit lib;};

  # Coding rules injection utilities
  coding-rules = import ./coding-rules.nix {inherit lib;};

  # Agent configuration management utilities
  agents = import ./agents.nix {inherit lib;};

  # Fonts — single source (requer pkgs)
  fonts = import ./fonts.nix {inherit pkgs;};

  # Colors — paleta cyberpunk
  colors = import ./colors.nix;
}
