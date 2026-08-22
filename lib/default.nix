# Biblioteca de helpers para nixos-ai
#
# Esta biblioteca expõe as utilidades do m3ta-nixpkgs (ports, coding-rules,
# agents) de forma acessível via `let m3ta = import ./default.nix { lib; };`
#
# Usage:
#   let
#     m3ta = import ./lib { inherit lib; };
#     portHelpers = m3ta.ports.mkPortHelpers {
#       ports = { qdrant = 6333; llama-cpp = 8080; };
#       hostPorts = { nitro-v15 = { qdrant = 6334; }; };
#     };
#   in ...
{lib}: let
  ports = import ./ports.nix {inherit lib;};
  agents = import ./agents.nix {inherit lib;};
  coding-rules = import ./coding-rules.nix {inherit lib;};
in {
  inherit ports agents coding-rules;
}
