# Foot terminal — usa lib/fonts.nix como single source
{pkgs, lib, ...}: let
  fonts = import ../../../lib/fonts.nix {inherit pkgs;};
in {
  programs.foot = {
    enable = true;
    settings = {
      main = {
        font = lib.mkForce fonts.footFont;
      };
    };
  };
}
