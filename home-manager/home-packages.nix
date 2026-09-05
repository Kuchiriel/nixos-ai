{
  pkgs,
  ...
}: {
  fonts.fontconfig.enable = true;
  home.packages = with pkgs; [
    # AI CLIs
    kilo
    antigravity-ide

    # Desktop essential apps
    foot
    yazi
    imv
    mpv
    pavucontrol

    # TUI tools (porta do legado Manjaro — abre via on-click no Waybar)
    bluetuith # Bluetooth TUI (on-click no módulo bluetooth)
    ncpamixer # Audio mixer TUI (on-click no módulo pulseaudio)
    networkmanagerapplet # nmtui-connect (on-click no módulo network)
    calcurse # Calendar TUI (on-click no clock)
    htop # Process viewer alternativo ao btm
    intel-gpu-tools

    # Fonts / Icons (Adaptado para compatibilidade estável do Nixpkgs 26.05)
    font-awesome
    nerd-fonts.jetbrains-mono
    nerd-fonts.symbols-only

    # Core CLI utils
    nodejs # npx para MCP servers (Roo Dev, etc.)
    bc
    bottom
    brightnessctl
    cliphist
    ffmpeg
    fzf
    grimblast
    hyprpicker
    ntfs3g
    playerctl
    ripgrep
    unzip
    wget
    wl-clipboard
    yt-dlp
    zip

    # WM Utilities
    libnotify
    xdg-desktop-portal-gtk
    xdg-desktop-portal-hyprland
    yad # GUI dialogs para NixOS-AI Launcher

    # ── packages ──────────────────────────────────────
    # sidecar: terminal multiplexer/UX para CLI agents
    # sidecar
    # stt-ptt: Push-to-Talk Speech-to-Text com Whisper
    # stt-ptt
    # talk: Text-to-Speech com ElevenLabs para notificações
    # talk  # REMOVIDO: redundante com Kokoro TTS do jarvis voice
  ];
}

