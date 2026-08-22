# lib/colors.nix — Single source para paleta de cores
# Todas as cores usam # prefix para compatibilidade CSS
{
  # Paleta principal (cyberpunk)
  primary = "#00ffff"; # ciano
  background = "#0a0a0a"; # preto
  text = "#ffffff"; # branco

  # Status colors (com # para CSS)
  status = {
    success = "#50FA7B"; # verde
    warning = "#FFB86C"; # laranja
    error = "#FF5555"; # vermelho
    info = "#6699CC"; # azul
  };

  # Compatibilidade com Hyprland rgba (sem #)
  hypr = {
    activeBorder = "rgba(00ffffcc) rgba(0088ffcc) 45deg";
    inactiveBorder = "rgba(595959aa)";
    shadow = "rgba(00ffff33)";
  };

  # Compatibilidade com waybar
  waybar = {
    bg = "rgba(10, 10, 10, 0.85)";
    border = "2px solid #00ffff";
    text = "#00ffff";
  };
}
