# Foot terminal — usa lib.m3ta.fonts como single source
{lib, ...}: {
  programs.foot = {
    enable = true;
    settings = {
      main = {
        font = lib.mkForce lib.m3ta.fonts.footFont;
      };
    };
  };
}
