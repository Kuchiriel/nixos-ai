# NixOS Rules for nixos-ai

## Project Structure
- `modules/ai/` - AI services (llama-cpp, jarvis, mcp-nixos)
- `modules/services/` - System services (qdrant, litellm, etc.)
- `home-manager/` - User environment configuration
- `hosts/` - Host-specific configurations
- `overlays/` - Nix overlays
- `nixos/` - NixOS modules

## Nix Style Guide
- Use 2 spaces for indentation
- Use `let/in` for local variables
- Prefer `mkOption` for configurable options
- Document options with `description`
- Validate with `nix-instantiate --parse` before commit

## Common Patterns
```nix
# Service definition
systemd.services.my-service = {
  description = "My Service";
  after = [ "network-online.target" ];
  wantedBy = [ "multi-user.target" ];
  script = ''exec ${pkgs.my-package}/bin/my-service'';
};

# Home Manager module
home.packages = with pkgs; [
  package1
  package2
];
```

## Testing
- Run `nix-instantiate --parse` to validate syntax
- Use `--dry-run` before actual rebuilds
- Test with `nix build .#package-name` for individual packages
