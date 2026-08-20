{ pkgs, ... }: {

  # Permite pacotes proprietários e ativa o DRM Widevine para o Chromium
  nixpkgs.config = {
    allowUnfree = true;
    chromium.enableWideVine = true;
  };

  programs.chromium = {
    enable = true;
    extensions = [
      # Dark Reader
      { id = "eimadpbcbfnmbkopoojfekhnkhdbieeh"; }

      # Unhook - Remove YouTube Recommended & Shorts
      { id = "khncfooichmfjbepaaaebmommgaepoid"; }

      # FireShot
      { id = "mcbpblocgmgfnpjjppndjkmgjaogfceg"; }
    ];
  };
}
