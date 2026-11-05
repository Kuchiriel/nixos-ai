{
  imports = [
    ./agents-md.nix
    ./jarvismodes.nix
    # Modelos de voz (kokoro/whisper/openwakeword) — links em ~/.local/share.
    # Antes só o wakeword (desabilitado) os referenciava -> GC levou os
    # store paths e o TTS Kokoro morreu (fallback espeak = voz horrível).
    ./jarvis-models.nix
    ./alacritty.nix
    ./bat.nix
    ./chromium.nix
    ./eza.nix
    ./foot.nix
    ./git.nix
    ./hyprland
    ./lazygit.nix
    ./mpvpaper.nix
    ./neovim.nix
    ./obsidian.nix
    ./ranger.nix
    ./rofi.nix
    ./audiobook.nix
    ./starship.nix
    ./stylix.nix
    ./swaync
    ./tmux.nix
    ./waybar.nix
    # Default source do pipewire = mic DIGITAL (o Stereo está morto e o
    # AEC3 captura do default ⇒ duplex surdo). Ver o módulo p/ o porque.
    ./services/wireplumber-default-source.nix
    # (05/11) MCP de coordenação entre IAs por HTTP na tailnet.
    ./services/coord-mcp.nix
    ./wofi
    ./zathura.nix
    ./zsh.nix
  ];
}
