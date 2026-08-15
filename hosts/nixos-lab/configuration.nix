{ config, pkgs, lib, stateVersion, hostname, ... }:

let
  # Carrega dinamicamente todos os arquivos .nix dentro do diretório de serviços
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
    ../../modules/services/qdrant.nix
    ./hardware-configuration.nix
    ./local-packages.nix
    ../../nixos/modules
  ] ++ dynamicServiceImports;

  stylix.homeManagerIntegration.autoImport = false;

  # =========================================================================
  # 1. HARDWARE, VIRTUALIZAÇÃO E GRAPHICS (HYPER-V)
  # =========================================================================

  # Habilita drivers de integração do Hyper-V
  virtualisation.hypervGuest.enable = true;

  # Suporte a gráficos (NixOS 24.11+)
  hardware.graphics = {
    enable = true;
    enable32Bit = true;
  };

  # Driver NVIDIA (Mantido para compatibilidade declarativa)
  services.xserver.videoDrivers = [ "nvidia" ];

  hardware.nvidia = {
    modesetting.enable = true;
    open = true;
    nvidiaSettings = true;
    package = config.boot.kernelPackages.nvidiaPackages.stable;
  };

  # Variáveis de ambiente para estabilidade em VM / Wayland
  environment.sessionVariables = {
    WLR_NO_HARDWARE_CURSORS = "1";
    WLR_RENDERER_ALLOW_SOFTWARE = "1";
    NIXPKGS_ALLOW_UNFREE = "1";
  };

  # =========================================================================
  # 2. CONFIGURAÇÕES DO NIX
  # =========================================================================

  nix.settings = {
    experimental-features = [ "nix-command" "flakes" ];
    auto-optimise-store = true;
    download-buffer-size = 536870912; # 500 MiB
    http-connections = 25;
    max-substitution-jobs = 8;

    # Caches Comunitários com o endpoint oficial corrigido
    substituters = [
      "https://cache.nixos.org" 
      "https://nixos-cuda.org"
    ];
    trusted-public-keys = [
      "cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY="
      "nix-community.cachix.org-1:mB9FSh9qf2dCimDSUo8Zy7bkq5CX+/rkCWyvRCYg3Fs="
    ];
  };

  programs.nh = {
    enable = true;
    clean.enable = true;
    clean.extraArgs = "--keep-since 4d --keep 3";
    flake = pkgs.lib.mkForce "/home/nixos/nixos-config-reborn";
  };

  # Limpeza automática de diretórios de estado/cache estagnados em /var
  systemd.tmpfiles.rules = [
    # Limpa arquivos em /var/tmp que não foram acessados há mais de 14 dias
    "d /var/tmp 1777 root root 14d"
    
    # Remove automaticamente pastas/caches residuais em /var/lib/private não modificados há mais de 30 dias
    "e /var/lib/private/ollama - - - 30d"
  ];

  # =========================================================================
  # 3. KERNEL E PERFORMANCE
  # =========================================================================

  boot.loader.systemd-boot.enable = true;
  boot.loader.efi.canTouchEfiVariables = true;

  boot.kernelPackages = lib.mkForce pkgs.linuxPackages;

  boot.kernelParams = [
    "quiet"
    "loglevel=3"
    "libahci.ignore_sss=1"
    "iommu=pt"
  ];

  zramSwap = lib.mkForce {
    enable = true;
    memoryPercent = 50;
    algorithm = "zstd";
  };

  boot.kernel.sysctl = {
    "vm.swappiness" = 150;
    "net.core.default_qdisc" = "fq_codel";
    "net.ipv4.tcp_congestion_control" = "bbr";
    "net.ipv4.tcp_low_latency" = 1;
  };

  # =========================================================================
  # 4. PACOTES, SERVIÇO LLAMA-CPP E FIREWALL
  # =========================================================================

  nixpkgs.config.allowUnfree = true;

  services.llama-cpp-server.enable = true;

  environment.systemPackages = with pkgs; [
    home-manager
    pciutils
    git
    curl
    jq
    htop
  ];

  # Liberando portas necessárias no Firewall
  networking.firewall.allowedTCPPorts = [ 22 8080 11434 ];

  # =========================================================================
  # 5. REDE, USUÁRIOS E LOCALIZAÇÃO
  # =========================================================================

  networking.hostName = hostname;
  networking.networkmanager.enable = true;
  time.timeZone = lib.mkForce "America/Sao_Paulo";
  networking.nameservers = [ "8.8.8.8" "1.1.1.1" ];

  services.openssh = {
    enable = true;
    settings.PermitRootLogin = "yes";
  };

  users.users.nixos = {
    isNormalUser = true;
    extraGroups = [ "wheel" "networkmanager" "qdrant" ];
  };

  services.greetd = {
    enable = true;
    settings.default_session = {
      command = "${pkgs.greetd.tuigreet}/bin/tuigreet --time --remember --cmd Hyprland";
      user = "greeter";
    };
  };

  system.stateVersion = stateVersion;
}
