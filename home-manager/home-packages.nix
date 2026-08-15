{ pkgs, ... }: {
  fonts.fontconfig.enable = true;
  home.packages = with pkgs; [
    # Desktop essential apps
    foot
    yazi
    imv
    mpv
    pavucontrol
    telegram-desktop

    # Fonts / Icons
    font-awesome
    (nerdfonts.override { fonts = [ "JetBrainsMono" "NerdFontsSymbolsOnly" ]; })

    # Core CLI utils
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

    # Dev Runtime (Necessário para o Pi Agent CLI)
    nodejs

    # WM Utilities
    libnotify
    xdg-desktop-portal-gtk
    xdg-desktop-portal-hyprland
  ];
}
