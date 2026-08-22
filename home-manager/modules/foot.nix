# Foot terminal — fonte padronizada
# NOTA: Quando lib/ for exportado pelo flake, migrar para:
#   fonts = lib.m3ta.fonts;
{lib, ...}: {
  programs.foot = {
    enable = true;
    settings = {
      main = {
        font = lib.mkForce "JetBrainsMono Nerd Font:size=14";
      };
    };
  };
}
