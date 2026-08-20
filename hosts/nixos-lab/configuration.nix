{ config, pkgs, lib, stateVersion, hostname, user, ... }:

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

security.sudo.extraRules = [
  {
    users = [ "nixos" ];
    commands = [
      {
        command = "ALL";
        options = [ "NOPASSWD" ];
      }
    ];
  }
];

  programs.nix-ld.enable = true;
  programs.nix-ld.libraries = with pkgs; [
    stdenv.cc.cc.lib
    zlib
    glibc
    openssl
    curl
  ];

  imports = [
    ../../modules/services/qdrant.nix
    ./hardware-configuration.nix
    ./local-packages.nix
    ../../nixos/modules
  ] ++ dynamicServiceImports;

  environment.systemPackages = with pkgs; [
    # Outros pacotes do sistema...
    inputs.self.packages.${pkgs.system}.jarvis
  ];


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
  #services.xserver.videoDrivers = [ "nvidia" ];

  hardware.nvidia = {
    modesetting.enable = true;
    open = true;
    nvidiaSettings = true;
    package = config.boot.kernelPackages.nvidiaPackages.stable;
  };

  hardware.nvidia.prime = {
    offload.enable = true;
    offload.enableOffloadCmd = true;
    intelBusId = "PCI:0:2:0"; # Validar via lspci na máquina física
    nvidiaBusId = "PCI:1:0:0"; # Validar via lspci na máquina física
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
      "https://cache.nixos-cuda.org"
    ];
    trusted-public-keys = [
      "cache.nixos.org-1:6NCHdD59X431o0gWypbMrAURkbJ16ZPMQFGspcDShjY="
      "cache.nixos-cuda.org:74DUi4Ye579gUqzH4ziL9IyiJBlDpMRn9MBN8oNan9M="
    ];
    # Sem isto, o user nixos não baixa binários pré-compilados (compila gcc/numpy toda vez)
    trusted-users = [ "root" user ];
    # Impede que gcc seja removido entre rebuilds (evita re-download de 264MB)
    keep-outputs = true;
    keep-derivations = true;
  };

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
    "net.ifnames=0"
    "pci=noaer"                # Desativa log excessivo de erros PCIe Advanced Error Reporting
    "pcie_aspm=off"
  ];

  # Desativa offloading de rede na interface eth0 para estabilizar a rede virtual
  #networking.interfaces.eth0.ethtoolCommands = "-K eth0 gro off tso off gso off";

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
    "net.core.netdev_max_backlog" = 16384;     # Movido para cá
    "net.ipv4.tcp_fastopen" = 3;  
  };

  # =========================================================================
  # 4. PACOTES, SERVIÇO LLAMA-CPP E FIREWALL
  # =========================================================================

  # ── JARVIS-ENV: switch central de ambiente (água) ────────────────────
  # Todos os módulos bebem daqui: llama-cpp (perfil), waybar (módulos),
  # mpvpaper (wallpaper animado), hyprland (animações). O lab é "vm";
  # o host físico (Acer Nitro V15) declarará "host" — 1 linha e o corpo
  # inteiro reage no rebuild (Qwen3.6-35B MoE + GPU + iGPU offload).
  services.jarvis.enable = true;
  services.jarvis.environment = "vm";

  services.llama-cpp-server.enable = true;
  # O perfil segue o switch acima (default); sobrescreva aqui se precisar.
  # Servidor dedicado de embeddings (Fase 4 — RAG) com nomic-embed-text-v2-moe
  services.llama-cpp-embeddings.enable = true;
  # Servidor dedicado de reranking (Fase 10 — RAG SOTA) com bge-reranker-v2-m3
  services.llama-cpp-rerank.enable = true;
  # Vault de memória de longo prazo — resumo semanal automático (Fase 7)
  services.jarvis-vault.enable = true;
  # Modo idle — self-knowledge quando o sistema está ocioso (Fase 4a):
  # benchmark/regression/eval-rag em segundo plano com yield automático
  services.jarvis-idle.enable = true;
  # Canal Telegram (Fase 9) — aprovação assíncrona do agente. O token fica
  # em /etc/jarvis-telegram.env (chmod 600, fora do repo): sem o arquivo, o
  # serviço aguarda — crie o bot (BotFather) e preencha antes do switch.
  services.jarvis-telegram.enable = true;
  # LiteLLM (cascade/fallback/handover — porta do legado): módulo OFICIAL do
  # nixpkgs em :4000 (127.0.0.1), roteia local → nuvem grátis (Groq→Gemini→
  # OpenRouter) com fallbacks em cadeia. A config cascade vem de
  # modules/services/litellm-cascade.nix. Testável já no lab; chaves em
  # /etc/litellm.env (fora do repo). Sem o arquivo, serve só a rota local.
  services.litellm.enable = true;
  # Freebuff CLI — o agente de coding gratuito (freebuff.com) declarativo,
  # para o host final ter o mesmo fluxo de trabalho deste lab.
  programs.freebuff.enable = true;
  # Scripts de manutenção declarativos no store (rebuild/clean/fix-qdrant)
  # — sem depender de arquivos soltos na raiz do repo.
  programs.jarvis-scripts.enable = true;

  environment.etc."litellm.env" = {
    text = "";
    mode = "0600";
  };

  environment.systemPackages = with pkgs; [
    home-manager
    pciutils
    git
    curl
    jq
    htop
    ethtool
    # JARVIS — pacote Python do sistema (agente, doctor, RAG, CLI).
    # Vem do overlay aiOverlay (flake.nix) e é construído a partir dos
    # fontes em modules/ai/jarvis/ (versionados no repo = declarativos).
    jarvis
  ];

  # Liberando portas necessárias no Firewall
  # 22 (ssh), 8080 (llama.cpp chat), 8081 (llama.cpp embeddings) — 11434 era resquício do Ollama (legado Manjaro)
  networking.firewall.allowedTCPPorts = [ 22 8080 8081 4000 ];

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
      # 26.05: pkgs.greetd.tuigreet renomeado para pkgs.tuigreet
      # start-hyprland é o wrapper que configura XDG_RUNTIME_DIR, dbus, etc.
      command = "${pkgs.tuigreet}/bin/tuigreet --time --remember --cmd start-hyprland";
      user = "greeter";
    };
  };

  # dbus-broker: o reload (re-exec) trava ~90s nesta VM (Hyper-V) e o restart
  # derruba o bus do sistema durante a ativação (o NixOS usa reload de propósito:
  # "Don't restart dbus. Bad things tend to happen if we do."). Aqui o bus NÃO
  # é tocado no switch — a config do bus (etc/dbus-1) é aplicada no próximo boot.
  systemd.services.dbus-broker.reloadIfChanged = lib.mkForce false;
  systemd.services.dbus-broker.restartIfChanged = lib.mkForce false;
  systemd.user.services.dbus-broker.reloadIfChanged = lib.mkForce false;
  systemd.user.services.dbus-broker.restartIfChanged = lib.mkForce false;

  # Stylix injeta um overlay (nixos-icons) no escopo do home-manager, o que
  # dispara o warning do HM (useGlobalPkgs + nixpkgs.overlays será erro no
  # futuro). Usamos papirus-icon-theme — o overlay não é necessário aqui.
  home-manager.users.${user}.nixpkgs.overlays = lib.mkForce null;

  system.stateVersion = stateVersion;
}
