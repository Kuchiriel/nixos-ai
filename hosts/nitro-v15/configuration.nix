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
    # Força o Steam a rodar na NVIDIA por padrão
    package = pkgs.steam.overrideAttrs (old: {
      nativeBuildInputs = (old.nativeBuildInputs or []) ++ [ pkgs.makeWrapper ];
      postInstall = (old.postInstall or "") + ''
        wrapProgram $out/bin/steam \
          --set __NV_PRIME_RENDER_OFFLOAD "1" \
          --set __GLX_VENDOR_LIBRARY_NAME "nvidia"
      '';
    });
  };

  programs.thunar = {
    enable = true;
    plugins = with pkgs.xfce; [
      thunar-archive-plugin
      thunar-volman
    ];
  };

  programs.mtr.enable = true;

  stylix.targets.gnome.enable = false;    # Exemplo para GNOME
  stylix.targets.feh.enable = false;      # Comum em WMs leves como i3 ou Sway
  stylix.targets.console.enable = true; # Mantém as cores no terminal

  hardware.uinput.enable = true;

  environment.systemPackages = with pkgs; [
    # Sunshine (streaming) — módulo NixOS não existe; pacote + config manual
    sunshine
    discord
    gvfs
    # Utilitários do sistema
    pciutils
    git
    curl
    jq
    htop
    ethtool
    xclip
    cloudflare-warp
    # Pacote do JARVIS via overlay
    #jarvis
  ];

  # Habilita o gerenciamento de volumes e montagem de mídia
  services.gvfs.enable = true;
  services.udisks2.enable = true;

  services.cloudflare-warp.enable = true;

  # Suporte a NTFS (essencial para ler/escrever em partições do Windows)
  boot.supportedFilesystems = [ "ntfs" ];

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
    "pcie_aspm=force"          # Reduz calor da dGPU em idle
    "nvme_load=1"              # Carrega o NVMe precocemente no initrd
    "preempt=full"             # Preempção total do kernel Zen
    "split_lock_detect=off"    # Desativa penalidades por split locks em IA
    # Performance tweaks para llama.cpp / inferência:
    "intel_idle.max_cstate=1"  # Limita C-states a C1: menor wake latency, +1-3% decode
    "nvme_core.io_timeout=10"  # Timeout I/O NVMe mais agressivo
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
  services.jarvis-gaming.enable = true;
  services.litellm.enable = true;
  programs.freebuff.enable = true;
  programs.jarvis-scripts.enable = true;

  environment.etc."litellm.env" = {
    text = "";
    mode = "0600";
  };

  environment.etc."nanorc".text = ''
    set tabsize 2
    set tabstospaces
  '';

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
    "vm.nr_hugepages" = 16384;                  # 32GB * 50% / 2MB = 16384 pages: Huge Pages para KV cache do llama.cpp
    "kernel.sched_child_runs_first" = 1;        # Processos filhos rodam mais rápido (inferência)
    "net.core.default_qdisc" = "fq_codel";
    "net.ipv4.tcp_congestion_control" = "bbr";
    "net.ipv4.tcp_low_latency" = 1;             # Baixa latência de rede
    "net.core.netdev_max_backlog" = 16384;      # Expande fila contra gargalo da Claro
    "net.ipv4.tcp_fastopen" = 3;                # Acelera conexões HTTP das tools web
  };

  # I/O scheduler para NVMe: 'none' é melhor que 'kyber' para devices non-rotational
  services.udev.extraRules = ''
    ACTION=="add|change", KERNEL=="nvme[0-9]*n[0-9]*", ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="none"
  '';

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
  # CSS customizado para gtkgreet (tema cyberpunk preto+ciano)
  environment.etc."greetd/gtkgreet.css".source = ./gtkgreet.css;

  services.greetd = {
    enable = true;
    settings.default_session = {
      command = "${pkgs.gtkgreet}/bin/gtkgreet -l -s /etc/greetd/gtkgreet.css";
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
    extraGroups = [ "wheel" "video" "audio" "networkmanager" "qdrant" "input" "uinput" ];
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
