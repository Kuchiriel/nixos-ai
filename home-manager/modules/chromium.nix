{pkgs, ...}: {
  programs.chromium = {
    enable = true;

    # Esta linha injeta o Widevine diretamente no pacote do Chromium sem violar o useGlobalPkgs
    package = pkgs.chromium.override {enableWideVine = true;};

    extensions = [
      # Dark Reader
      {id = "eimadpbcbfnmbkopoojfekhnkhdbieeh";}

      # Unhook - Remove YouTube Recommended & Shorts
      {id = "khncfooichmfjbepaaaebmommgaepoid";}

      # FireShot
      {id = "mcbpblocgmgfnpjjppndjkmgjaogfceg";}
    ];
  };
}
