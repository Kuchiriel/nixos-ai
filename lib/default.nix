# Library of helper functions for m3ta-nixpkgs
# Usage in your configuration:
#   let
#     m3taLib = inputs.m3ta-nixpkgs.lib.${system};
#   in ...
{lib}: {
  # Port management utilities
  ports = import ./ports.nix {inherit lib;};

  # Coding rules injection utilities
  coding-rules = import ./coding-rules.nix {inherit lib;};

  # Agent configuration management utilities
  agents = import ./agents.nix {inherit lib;};
}
