# Módulos de coding agents para nixos-ai
#
# Este módulo agrupa os sub-módulos de coding agents (opencode, pi)
# do m3ta-nixpkgs.
#
# Usage em home.nix:
#   imports = [ ./modules/m3ta-coding ];
#   coding.agents.opencode.enable = true;
#   coding.agents.opencode.agentsInput = inputs.agents;
{
  config,
  lib,
  pkgs,
  ...
}: {
  imports = [
    ./opencode.nix
    ./pi.nix
    ./shared/default.nix
  ];
}
