{ pkgs, lib, ... }:
# Tema rofi "jarvis-cyan" — porta do legado (Manjaro).
# Fonte: ~/.local/share/rofi/themes/jarvis-cyan.rasi do sistema legado
# (preto profundo 86%, ciano neon #00ffff, borda ciano, seleção azul 26%).
# Usado por SUPER+D (menu) e pelo prompt do JARVIS (SUPER+A).
{
  home.packages = [ pkgs.rofi ];

  home.file.".local/share/rofi/themes/jarvis-cyan.rasi".source =
    ../assets/rofi/jarvis-cyan.rasi;

  # Configuração do rofi com ícones Nerd Font e modos JARVIS
  home.file.".config/rofi/config.rasi".text = ''
    configuration {
        modi: "drun,run,window,jarvis";
        show-icons: true;
        terminal: "foot";
        drun-display-format: "{name}";
        location: 0;
        disable-history: false;
        hide-scrollbar: true;
        display-drun: "  Apps ";
        display-run: "  Run ";
        display-window: "󰕰  Window";
        sidebar-mode: true;
    }
  '';

  programs.rofi.enable = true;
}
