# Coding rules management utilities para nixos-ai
#
# Fornece funções para configurar regras de coding para agentes de IA
# (OpenCode, Pi) em projetos. Regras são definidas no repositório AGENTS
# e podem ser seletivamente incluídas por linguagem, framework e concerns.
#
# Usage:
#   let
#     m3taLib = import ./default.nix { inherit lib; };
#     rules = m3taLib.coding-rules.mkCodingRules {
#       agents = inputs.agents;
#       languages = [ "python" "nix" ];
#       concerns = [ "coding-style" "naming" "testing" ];
#       frameworks = [ "fastapi" ];
#     };
#   in {
#     devShells.default = pkgs.mkShell {
#       shellHook = rules.shellHook;
#       inherit (rules) instructions;
#     };
#   }
{lib}: let
  codingRulesLib = import "${./../m3ta-nixpkgs}/lib/coding-rules.nix" {inherit lib;};
in {
  inherit (codingRulesLib) mkCodingRules;
}
