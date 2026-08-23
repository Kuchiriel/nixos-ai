{user, ...}: {
  programs.nh = {
    enable = true;
    clean.enable = true;
    clean.extraArgs = "--keep-since 4d --keep 3";
    # nh 4.4.2+: o módulo nixpkgs define a env var NH_FLAKE (FLAKE é deprecated).
    flake = "/home/${user}/nixos-config-reborn";
  };
}
