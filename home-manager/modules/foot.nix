# Foot terminal — usa projectLib.fonts como single source
{
  lib,
  projectLib,
  ...
}: {
  programs.foot = {
    enable = true;
    settings = {
      main = {
        font = lib.mkForce projectLib.fonts.footFont;
      };
    };
  };
}
