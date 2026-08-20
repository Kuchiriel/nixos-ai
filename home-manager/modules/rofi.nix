{ pkgs, lib, ... }:
# Tema rofi "jarvis-cyan" — porta do legado (Manjaro).
# O tema é aplicado via --theme na linha de comando do hyprland.
{
  home.packages = [ pkgs.rofi ];

  home.file."local/share/rofi/themes/jarvis-cyan.rasi".source =
    ../assets/rofi/jarvis-cyan.rasi;
}
