{pkgs, ...}: {
  environment.systemPackages = with pkgs; [
    pciutils
    clinfo
    nvtopPackages.nvidia # Monitoramento em tempo real da RTX 4050 e Intel UHD
    uwsm
    git
    curl
    jq
    htop
    unar # Descompactar .rar/.rar5 (livre; unrar original precisaria allowUnfree)
  ];

  # Regras de udev para otimizar o scheduler de I/O nos NVMes de alta performance
  services.udev.extraRules = ''
    ACTION=="add|change", KERNEL=="sd[a-z]|mmcblk[0-9]*|nvme[0-9]*", ATTR{queue/scheduler}="kyber"
  '';
}
