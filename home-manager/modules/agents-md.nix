# ═══ ~/.agents.md — Linux Foundation Compatible ═══
# Contexto compartilhado para qualquer IA que trabalhe neste sistema.
# Referência: https://github.com/lnx-agents/AGENTS.md

{ pkgs, ... }:

{
  home.file.".agents.md".text = ''
    # AGENTS.md — Home Directory Context

    > This file provides context for AI agents working in this home directory.
    > For project-specific rules, see the project's own AGENTS.md.

    ## System Info

    - OS: NixOS (declarative, reproducible)
    - Shell: zsh
    - Editor: neovim
    - Terminal: foot
    - WM: Hyprland
    - AI: llama.cpp (Qwen3.6-35B-A3B, RTX 4050 6GB)

    ## Commands

    ```bash
    # Project
    cd ~/projects/nixos-ai
    ./rebuild-host.sh    # Rebuild NixOS
    nix develop --command python3 -m pytest  # Run tests

    # JARVIS
    jarvis dev            # REPL
    jarvis status         # System status
    jarvis doctor         # Health check
    jarvis waybar         # Waybar status
    jarvis remember "..." # Store memory
    jarvis recall "..."   # Recall memory
    ```

    ## Boundaries

    **Always do:**
    - Check git status before commits
    - Run tests before pushing
    - Use `nix develop` not `nix-shell`

    **Ask first:**
    - Modify configuration.nix
    - Change llama-server flags
    - Add new dependencies

    **Never do:**
    - `nixos-rebuild` directly (use rebuild-host.sh)
    - Edit /nix/store files
    - Restart LLM during active session
    - Push without testing

    ## Project Structure

    ```
    ~/projects/nixos-ai/
    ├── flake.nix              # NixOS configuration
    ├── modules/
    │   ├── ai/                # JARVIS, models, MCP
    │   ├── services/          # systemd services
    │   └── system/            # NixOS modules
    ├── home-manager/          # User configuration
    └── docs/                  # Documentation
    ```

    ## Context Window

    - Model: Qwen3.6-35B-A3B (32K context)
    - System prompt: ~15-20K tokens
    - Available: ~12-17K for conversation
    - Rule: output >50 lines = summarize in bullets
  '';
}
