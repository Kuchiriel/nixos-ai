# lib/default.nix — m3ta lib exports
#
# Uso em módulos (quando disponível via flake):
#   colors = lib.m3ta.colors;
#   fonts = lib.m3ta.fonts;
{lib, pkgs}: {
  # Port management utilities
  ports = import ./ports.nix {inherit lib;};

  # Coding rules injection utilities
  coding-rules = import ./coding-rules.nix {inherit lib;};

  # Agent configuration management utilities
  agents = import ./agents.nix {inherit lib;};

  # Fonts — single source (requer pkgs)
  fonts = import ./fonts.nix {inherit pkgs;};

  # Colors — paleta cyberpunk
  colors = import ./colors.nix {};
}
