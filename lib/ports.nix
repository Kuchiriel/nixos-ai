# Port management utilities para nixos-ai
#
# Gerencia portas de serviços centralizadamente com suporte a overrides
# por host. Ideal para serviços como qdrant, llama-cpp, mcp etc.
#
# Usage:
#   let
#     m3taLib = import ./default.nix { inherit lib; };
#     myPorts = {
#       ports = {
#         qdrant = 6333;
#         llama-cpp = 8080;
#         mcp = 3000;
#       };
#       hostPorts = {
#         nitro-v15 = { qdrant = 6334; };
#       };
#     };
#     portHelpers = m3taLib.ports.mkPortHelpers myPorts;
#   in {
#     services.qdrant.port = portHelpers.getPort "qdrant" "nitro-v15";
#   }
{lib}: let
  # Re-exporta a função mkPortHelpers do m3ta-nixpkgs
  mkPortHelpers = portsConfig:
    (import "${./../m3ta-nixpkgs}/lib/ports.nix" {inherit lib;}).mkPortHelpers portsConfig;
in {
  inherit mkPortHelpers;
}
