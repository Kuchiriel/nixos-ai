# Foot terminal — usa m3taLib.fonts como single source
{lib, m3taLib, ...}: {
  programs.foot = {
    enable = true;
    settings = {
      main = {
        font = lib.mkForce m3taLib.fonts.footFont;
      };
    };
  };
}
