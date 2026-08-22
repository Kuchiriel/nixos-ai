{ lib, ... }: {
  programs.foot = {
    enable = true;
    settings = {
      main = {
        font = lib.mkForce "JetBrainsMono Nerd Font:size=14";
      };
    };
  };
}
