# NixOS Rules for nixos-ai

## Project Structure
- `modules/ai/` - AI services (llama-cpp, jarvis, mcp-nixos)
- `modules/services/` - System services (qdrant, litellm, etc.)
- `home-manager/` - User environment configuration
- `hosts/` - Host-specific configurations
- `overlays/` - Nix overlays
- `nixos/` - NixOS modules

## Nix Code Conventions (AGENTS)

### Formatting
- Use `alejandra` for formatting
- camelCase for variables, `PascalCase` for types
- 2 space indentation (alejandra default)
- No trailing whitespace

### Module Patterns
Standard module function signature:
```nix
{ config, lib, pkgs, ... }:
{
  options.myService.enable = lib.mkEnableOption "my service";
  config = lib.mkIf config.myService.enable {
    services.myService.enable = true;
  };
}
```

### Conditionals and Merging
- Use `mkIf` for conditional config
- Use `mkMerge` to combine multiple config sets
- Use `mkOptionDefault` for defaults that can be overridden

```nix
config = lib.mkMerge [
  (lib.mkIf cfg.enable { ... })
  (lib.mkIf cfg.extraConfig { ... })
];
```

### Anti-Patterns (NEVER USE)
- `with pkgs;` — polui namespace, use refs explícitas (pkgs.vim, pkgs.git)
- `builtins.fetchTarball` — use flake inputs
- `import <nixpkgs>` em flakes — use inputs
- `builtins.getAttr`/`builtins.hasAttr` — use lib.attrByPath/lib.optionalAttrs

### Home Manager Patterns
```nix
{ config, pkgs, lib, ... }:
{
  home.packages = [ pkgs.ripgrep pkgs.fd ];
  programs.zsh.enable = true;
  xdg.configFile."myapp/config".text = "...";
}
```

### Overlays
```nix
{ config, lib, pkgs, ... }:
let
  myOverlay = final: prev: {
    myPackage = prev.myPackage.overrideAttrs (old: { ... });
  };
in
{
  nixpkgs.overlays = [ myOverlay ];
}
```

### File Organization
```
flake.nix              # Entry point
modules/               # NixOS modules
  services/
    my-service.nix
overlays/              # Package overrides
  default.nix
```

## Testing
- Run `nix-instantiate --parse` to validate syntax
- Use `--dry-run` before actual rebuilds
- Test with `nix build .#package-name` for individual packages

## WEB SEARCH
Use tavily_search when you need to verify:
- Latest version of a package in nixpkgs
- Documented NixOS options for a specific module
- Known bugs in modules (GitHub issues)
- Usage examples for Home Manager modules
- Breaking changes between nixpkgs versions
Priority: HIGH — nixpkgs changes fast, model data is from Q1 2025
