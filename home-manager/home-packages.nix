{ pkgs, inputs, ... }: {
  fonts.fontconfig.enable = true;
  home.packages = with pkgs; [
    # Desktop essential apps
    foot
    yazi
    imv
    mpv
    pavucontrol
    
    # TUI tools (porta do legado Manjaro — abre via on-click no Waybar)
    bluetuith          # Bluetooth TUI (on-click no módulo bluetooth)
    ncpamixer          # Audio mixer TUI (on-click no módulo pulseaudio)
    networkmanagerapplet  # nmtui-connect (on-click no módulo network)
    calcurse           # Calendar TUI (on-click no clock)
    htop               # Process viewer alternativo ao btm
    intel-gpu-tools
    
    # Fonts / Icons
    font-awesome
    nerd-fonts.jetbrains-mono
    nerd-fonts.symbols-only

    # Core CLI utils
    aider-chat
    python3Packages.botocore
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
  ];
}

