# lib/colors.nix — Single source para paleta de cores
#
# Uso:
#   colors = import ./colors.nix {};
#   colors.primary       → "00ffff"
#   colors.css.fg        → "#00ffff"
#   colors.hypr.shadow   → "rgba(00ffff33)"
#   colors.status.success → "50FA7B"
{
  # Paleta principal (cyberpunk)
  primary = "00ffff"; # ciano
  background = "0a0a0a"; # preto
  text = "ffffff"; # branco

  # Status colors
  status = {
    success = "50FA7B"; # verde
    warning = "FFB86C"; # laranja
    error = "FF5555"; # vermelho
    info = "6699CC"; # azul
  };

  # Compatibilidade com CSS (com #)
  css = {
    bg = "#0a0a0a";
    fg = "#00ffff";
    success = "#50FA7B";
    warning = "#FFB86C";
    error = "#FF5555";
    info = "#6699CC";
    shadow = "#00ffff33";
  };

  # Compatibilidade com Hyprland rgba
  hypr = {
    activeBorder = "rgba(00ffffcc) rgba(0088ffcc) 45deg";
    inactiveBorder = "rgba(595959aa)";
    shadow = "rgba(00ffff33)";
  };

  # Compatibilidade com waybar (0.0-1.0 opacity)
  waybar = {
    bg = "rgba(10, 10, 10, 0.85)";
    border = "2px solid #00ffff";
    text = "#00ffff";
  };
}
