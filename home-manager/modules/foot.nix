# Foot terminal — tema cyberpunk preto+ciano
{ pkgs, ... }: {
  programs.foot = {
    enable = true;
    settings = {
      main = {
        font = {
          _type = "override";
          priority = 50;
          content = "JetBrainsMono Nerd Font:size=12";
        };
        dpi-aware = "no";
      };

      # Tema cyberpunk: preto (#0a0a0a) + ciano (#00ffff)
      colors-dark = {
        background = "0a0a0a";
        foreground = "00ffff";
        # Normal colors
        regular0 = "0a0a0a";   # black
        regular1 = "ff5555";   # red
        regular2 = "50fa7b";   # green
        regular3 = "f1fa8c";   # yellow
        regular4 = "00cccc";   # blue (ciano escuro)
        regular5 = "ff79c6";   # magenta
        regular6 = "8be9fd";   # cyan
        regular7 = "f8f8f2";   # white
        # Bright colors
        bright0 = "4d4d4d";    # bright black
        bright1 = "ff6e6e";    # bright red
        bright2 = "69ff94";    # bright green
        bright3 = "ffffa5";    # bright yellow
        bright4 = "00ffff";    # bright blue (ciano principal)
        bright5 = "ff92df";    # bright magenta
        bright6 = "a4ffff";    # bright cyan
        bright7 = "ffffff";    # bright white
      };

      # Cursor ciano
      cursor = {
        color = "00ffff 0a0a0a";  # foreground background
      };

      # Scrollback 10K linhas
      scrollback = {
        lines = 10000;
      };
    };
  };
}
