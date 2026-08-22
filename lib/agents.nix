# Agent configuration management utilities para nixos-ai
#
# Fornece funções para carregar definições canônicas de agents e renderizá-las
# para diferentes ferramentas de IA (OpenCode, Claude Code, Pi).
#
# Usage:
#   let
#     m3taLib = import ./default.nix { inherit lib; };
#     canonical = m3taLib.agents.loadCanonical {
#       agentsInput = inputs.agents; # seu repositório AGENTS pessoal
#     };
#     opencodeAgents = m3taLib.agents.renderForOpencode {
#       inherit pkgs canonical;
#       modelOverrides = { chiron = "anthropic/claude-sonnet-4"; };
#     };
#   in ...
{lib}: let
  agentsLib = import "${./../m3ta-nixpkgs}/lib/agents.nix" {inherit lib;};
in {
  inherit (agentsLib) loadCanonical renderForOpencode;
}
