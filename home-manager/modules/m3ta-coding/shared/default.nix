# Shared agent module exports para nixos-ai
# Imports all shared modules for the coding.agents namespace.
{
  imports = [
    ./git-identity.nix
    ./shared-options.nix
  ];
}
