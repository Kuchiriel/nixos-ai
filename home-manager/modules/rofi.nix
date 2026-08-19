{ pkgs, lib, ... }:
# Tema rofi "jarvis-cyan" — porta do legado (Manjaro).
# Fonte: ~/.local/share/rofi/themes/jarvis-cyan.rasi do sistema legado
# (preto profundo 86%, ciano neon #00ffff, borda ciano, seleção azul 26%).
# Usado por SUPER+D (menu) e pelo prompt do JARVIS (SUPER+A).
{
  home.packages = [ pkgs.rofi ];

  home.file.".local/share/rofi/themes/jarvis-cyan.rasi".source =
    ../assets/rofi/jarvis-cyan.rasi;

  # Rofi sem service/daemon — só o tema + binário; o menu é chamado pelos
  # keybindings do hyprland (wofi primeiro, rofi como fallback).
  programs.rofi.enable = true;
}
