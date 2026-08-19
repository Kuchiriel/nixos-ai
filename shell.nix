{ pkgs ? import <nixpkgs> {} }:

(pkgs.buildFHSEnv {
  name = "freebuff-fhs";
  targetPkgs = pkgs: (with pkgs; [
    udev
    alsa-lib
    glib
    nspr
    nss
    systemd
  ]);
  runScript = "bash";
}).env
