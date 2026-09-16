{pkgs ? import <nixpkgs> {}}:
(pkgs.buildFHSEnv {
  name = "freebuff-fhs";
  targetPkgs = pkgs: (with pkgs; [
    udev
    alsa-lib
    glib
    nspr
    nss
    systemd
    python3Packages.botocore
    aider-chat
  ]);
  runScript = "bash";
}).env
