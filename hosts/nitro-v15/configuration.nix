{ config, pkgs, lib, stateVersion, hostname, user, ... }:

let
  servicesDir = ../../modules/services;
  dynamicServiceImports =
    if builtins.pathExists servicesDir then
      lib.mapAttrsToList
        (name: type: servicesDir + "/${name}")
        (lib.filterAttrs (name: type: type == "regular" && lib.hasSuffix ".nix" name) (builtins.readDir servicesDir))
    else [];
in

{
  imports = [
    ./hardware-configuration.nix
    ./local-packages.nix
    ./disko.nix
    ../../nixos/modules
  ] ++ dynamicServiceImports;

  programs.steam = {
    enable = true;
    remotePlay.openFirewall = true; # Open ports in the firewall for Steam Remote Play
    dedicatedServer.openFirewall = true; # Open ports in the firewall for Source Dedicated Server
  };

  environment.systemPackages = with pkgs; [
    # Sunshine (streaming) — módulo NixOS não existe; pacote + config manual
    sunshine
    # Utilitários do sistema
    pciutils
    git
    curl
    jq
    htop
    ethtool

    # Pacote do JARVIS via overlay
    jarvis
  ];

  # ── O SWITCH CENTRAL (Ambiente do Host Físico) ──────────────────────
  services.jarvis.enable = true;
  services.jarvis.environment = "host";

  # =========================================================================
  # 1. HARDWARE — Intel i7-13620H + RTX 4050 (dGPU) + Intel UHD (iGPU)
  # =========================================================================
  hardware.nvidia = {
    package = config.boot.kernelPackages.nvidiaPackages.stable;
    modesetting.enable = true;
    open = false;
    nvidiaSettings = true;
  };
  services.xserver.videoDrivers = [ "nvidia" ];

  hardware.graphics = {
    enable = true;
    enable32Bit = true;
    extraPackages = with pkgs; [ intel-media-driver ];
  };

  hardware.nvidia.prime = {
    offload.enable = true;
    offload.enableOffloadCmd = true;
    intelBusId = "PCI:0:2:0"; # Validar via lspci na máquina física
    nvidiaBusId = "PCI:1:0:0"; # Validar via lspci na máquina física
  };

  boot.kernelParams = [
    "nvidia-drm.modeset=1"
    "quiet"
    "loglevel=3"
    "iommu=pt"
    "pcie_aspm=force"          # Altere de "off" para "force" para reduzir calor da dGPU em idle
    "nvme_load=1"              # Adicione para carregar o NVMe precocemente no initrd
    "preempt=full"             # Adicione para forçar preempção total do kernel Zen
    "split_lock_detect=off"    # Adicione para desativar penalidades por split locks em IA
  ];

  # =========================================================================
  # 2. SERVIÇOS JARVIS & IA (Host)
  # =========================================================================
  services.llama-cpp-server.enable = true;
  services.llama-cpp-embeddings.enable = true;
  services.llama-cpp-rerank.enable = true;
  services.qdrant.enable = true;
  services.jarvis-vault.enable = true;
  services.jarvis-idle.enable = true;
  services.jarvis-telegram.enable = true;
  services.litellm.enable = true;
  programs.freebuff.enable = true;
  programs.jarvis-scripts.enable = true;

  environment.etc."litellm.env" = {
    text = "";
    mode = "0600";
  };

  # =========================================================================
  # 3. KERNEL, PERFORMANCE E ZRAM
  # =========================================================================
  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;

  # ADICIONE ESTA LINHA AQUI: Força o NixOS a compilar o sistema com o Kernel Zen
  boot.kernelPackages = lib.mkForce pkgs.linuxPackages_zen;

  # ADICIONE ESTAS DUAS LINHAS AQUI: Ativa o controle térmico e trava performance
  services.thermald.enable = true;
  powerManagement.cpuFreqGovernor = "performance";

  zramSwap = lib.mkForce {
    enable = true;
    memoryPercent = 50;
    algorithm = "zstd";
  };

  boot.kernel.sysctl = {
    "vm.swappiness" = 10;
    "net.core.default_qdisc" = "fq_codel";
    "net.ipv4.tcp_congestion_control" = "bbr";
    "net.ipv4.tcp_low_latency" = 1;            # Adicione: Otimização de baixa latência de rede
    "net.core.netdev_max_backlog" = 16384;     # Adicione: Expande fila contra gargalo da Claro
    "net.ipv4.tcp_fastopen" = 3;               # Adicione: Acelera conexões HTTP das tools web
  };

  # Garante que as pastas de banco vetorial (Qdrant) e modelos nasçam com +C (No CoW)
  # Regras de tmpfiles: limpeza e suporte a No CoW (+C) para Btrfs
  systemd.tmpfiles.rules = [
    "d /var/tmp 1777 root root 14d"
    "d /var/lib/qdrant 0755 jarvis jarvis - -"
    "h /var/lib/qdrant - - - - +C"
    "d /var/lib/jarvis/models 0755 jarvis jarvis - -"
    "h /var/lib/jarvis/models - - - - +C"
  ];

  # =========================================================================
  # 4. SESSÃO, LOGIN E INTERFACE (Greetd + Hyprland)
  # =========================================================================
  services.greetd = {
    enable = true;
    settings.default_session = {
      command = "${pkgs.tuigreet}/bin/tuigreet --time --remember --cmd start-hyprland";
      user = "greeter";
    };
  };

  # =========================================================================
  # 5. REDE, USUÁRIOS E SEGURANÇA
  # =========================================================================
  networking.hostName = hostname;
  networking.networkmanager.enable = true;
  time.timeZone = lib.mkForce "America/Sao_Paulo";
  networking.nameservers = [ "8.8.8.8" "1.1.1.1" ];
  networking.firewall.allowedTCPPorts = [ 22 8080 8081 4000 ];

  services.openssh = {
    enable = true;
    settings.PermitRootLogin = "yes";
  };

  users.users.${user} = {
    isNormalUser = true;
    extraGroups = [ "wheel" "video" "audio" "networkmanager" "qdrant" ];
  };

  security.sudo.extraRules = [{
    users = [ user ];
    commands = [{ command = "ALL"; options = [ "NOPASSWD" ]; }];
  }];

  # =========================================================================
  # 6. NIX — Caches, Performance e nix-ld
  # =========================================================================
  programs.nix-ld.enable = true;
  programs.nix-ld.libraries = with pkgs; [
    stdenv.cc.cc.lib
    zlib
    fuse3
    icu
    nss
    openssl
    curl
    expat
  ];

  nix.settings = {
    experimental-features = [ "nix-command" "flakes" ];
    auto-optimise-store = true;
    download-buffer-size = 536870912;
    http-connections = 25;
    max-substitution-jobs = 8;
    substituters = [
      "https://cache.nixos.org"
      "https://cache.nixos-cuda.org"
    ];
    trusted-public-keys = [
      "cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY="
      "cache.nixos-cuda.org:74DUi4Ye579gUqzH4ziL9IyiJBlDpMRn9MBN8oNan9M="
    ];
    trusted-users = [ "root" user ];
    keep-outputs = true;
    keep-derivations = true;
  };

  # =========================================================================
  # 7. SISTEMA
  # =========================================================================
  system.stateVersion = stateVersion;
}
