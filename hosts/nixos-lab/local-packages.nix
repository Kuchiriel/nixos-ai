{pkgs, ...}: {
  environment.systemPackages = with pkgs; [
    pciutils
    clinfo
    nvtopPackages.nvidia
    uwsm
    git
  ];

  services.udev.extraRules = ''
    ACTION=="add|change", KERNEL=="sd[a-z]|mmcblk[0-9]*|nvme[0-9]*", ATTR{queue/scheduler}="kyber"
  '';
}
