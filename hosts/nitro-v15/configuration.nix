{
  config,
  pkgs,
  lib,
  stateVersion,
  hostname,
  user,
  ...
}: {
  imports =
    [
      ./hardware-configuration.nix
      ./local-packages.nix
      ./disko.nix
      ../../nixos/modules
      ../../modules/services/default.nix
    ];

  services.charger-watch.enable = true;
  services.charger-watch.interval = 3;
  services.charger-watch.user = user;
  services.chromium-cdp.enable = true;   # browser dos agentes (CDP :9223)
  services.chromium-cdp.user = user;
  # jarvis-notify/focus DESLIGADOS (12/10, IMP-017): units em crash-loop
  # (273+ restarts) chamando `jarvis watch` / `jarvis focus-daemon`,
  # subcomandos com função pronta mas NUNCA registrados no argparse
  # (main.py:752,768 sem add_parser) — e os corpos são sleep-placeholders.
  # Religar só com lógica real + wire + fumaça. Reverter: enable = true.
  services.jarvis-notify.enable = false;
  services.jarvis-focus.enable = false;

  services.avahi = {
    enable = true;
    nssmdns4 = true;
    openFirewall = true;
  };

  programs.steam = {
    enable = true;
    # Steam client UI DEVE rodar na iGPU (Intel) para evitar segfault
    # no XRandR sob XWayland. Jogos usam NVIDIA via prime-run.
    package = pkgs.steam.overrideAttrs (old: {
      nativeBuildInputs = (old.nativeBuildInputs or []) ++ [pkgs.makeWrapper];
      postInstall =
        (old.postInstall or "")
        + ''
          wrapProgram $out/bin/steam \
            --set __NV_PRIME_RENDER_OFFLOAD "0" \
            --set __GLX_VENDOR_LIBRARY_NAME "intel" \
            --set MESA_LOADER_DRIVER_OVERRIDE "iris"
        '';
    });
  };

  virtualisation.docker = {
    enable = true;
  };

  # Suporte NVIDIA em containers (substitui o deprecado
  # virtualisation.docker.enableNvidia).
  hardware.nvidia-container-toolkit.enable = true;

  programs.thunar = {
    enable = true;
    plugins = with pkgs; [
      thunar-archive-plugin
      thunar-volman
    ];
  };

  programs.mtr.enable = true;

  stylix.targets.gnome.enable = false; # Exemplo para GNOME
  stylix.targets.feh.enable = false; # Comum em WMs leves como i3 ou Sway
  stylix.targets.console.enable = true; # Mantém as cores no terminal

  hardware.uinput.enable = true;

  environment.systemPackages = with pkgs; [
    # Sunshine (streaming) — módulo NixOS não existe; pacote + config manual
    sunshine
    discord
    file-roller
    gvfs
    # Utilitários do sistema
    pciutils
    git
    curl
    jq
    # (26/10) Proton VPN — GUI + WireGuard
    proton-vpn
    wireguard-tools
    htop
    ethtool
    grim
    slurp
    wl-clipboard
    cloudflare-warp
    xxd # hex dump (análise de formatos binários: .spr/.dat/.shapes de clients)
    # Pacote do JARVIS via overlay (único: STT/TTS p/ wakeword brainCommand)
    jarvis
    # Voz: G2P do Kokoro + captura/teste de áudio
    espeak-ng
    sox
    alsa-utils
    # PIL/Pillow + pytesseract system-wide (2026-10-02, pedido do dono).
    # Motivo: vision.py do jarvis redimensiona a captura antes de mandar p/ a
    # API de visão; sem PIL ele mandava PNG cru de 1,5MB e o Gemini respondia
    # "Unable to process input image". pytesseract é o fallback OCR final da
    # cascata. ATENÇÃO: isto NÃO basta p/ o processo `jarvis` — ele roda com o
    # python3 do próprio store do pacote, que não enxerga systemPackages. O
    # PYTHONPATH efetivo do jarvis é montado em modules/ai/package.nix.
    (python3.withPackages (ps: with ps; [ pillow pytesseract ]))
    tesseract
    # Editor
    # vscodium — gerenciado por home-manager (vscode-roo.nix)
  ];

  # (08/11, dono pediu) Mullvad VPN — daemon systemd (mullvad-daemon) + GUI
  # via package pkgs.mullvad-vpn (CLI+GUI). Não conflita com Proton/Tailscale
  # (interfaces dedicadas). `enableEarlyBootBlocking` fica de fora (conflito
  # com a config de rede não-Mullvad, e o dono não pediu lockdown pré-boot).
  # (11/11, FIX REBUILD) O módulo do Mullvad define
  # networking.firewall.checkReversePath = "loose" SEM mkDefault, o que colidia
  # com o `false` exigido pelo Proton VPN (seção 5): erro "conflicting
  # definition values" e rebuild abortado. Resolvido com lib.mkForce false lá
  # embaixo (false é superset de "loose": Mullvad, Proton e Tailscale seguem OK).
  services.mullvad-vpn = {
    enable = true;
    package = pkgs.mullvad-vpn;
    enableExcludeWrapper = true;
  };

  # (09/11, dono pediu) Beszel agent — monitora a máquina no hub do
  # internal.spiritvale.info. KEY/TOKEN em /etc/beszel-agent.env (chmod 600,
  # fora do git); HUB_URL não é segredo. Agent dials OUT (websocket), sem
  # porta de entrada. NVIDIA detection é via `services.xserver.videoDrivers`
  # (já declarado abaixo).
  services.beszel.agent = {
    enable = true;
    environment = {
      HUB_URL = "https://beszel.internal.spiritvale.info";
    };
    environmentFile = "/etc/beszel-agent.env";
  };

  # (10/09, dono pediu) ProtonVPN não abria: org.freedesktop.secrets sem
  # dono (gnome-keyring ausente da config). NixOS module traz: pacote no
  # systemPackages, D-Bus activation (org.freedesktop.secrets), PAM login
  # (destrava no login), wrapper cap_ipc_lock.
  services.gnome.gnome-keyring.enable = true;

  # Habilita o gerenciamento de volumes e montagem de mídia
  services.gvfs.enable = true;
  services.udisks2.enable = true;
  services.upower.enable = true; # Battery detection for waybar

  # envfs (FUSE /bin via PATH): shebangs hardcoded #!/bin/bash passam a
  # resolver (aprovado pelo dono 18/09 — réplicas TB/Ubuntu fiéis; sem
  # isso, ./script.sh com #!/bin/bash dá ENOENT fantasma no NixOS).
  services.envfs.enable = true;

  services.cloudflare-warp.enable = false;

  security.rtkit.enable = true;
  services.pipewire = {
    enable = true;
    alsa.enable = true;
    alsa.support32Bit = true;
    pulse.enable = true;
  };

  # Suporte a NTFS (essencial para ler/escrever em partições do Windows)
  boot.supportedFilesystems = ["ntfs"];

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
    # Resume pós-suspend no Wayland (sem isso: tela preta ao abrir o lid).
    # Ativa os units nvidia-suspend/hibernate/resume.
    powerManagement.enable = true;
  };
  services.xserver.videoDrivers = ["nvidia"];

  hardware.graphics = {
    enable = true;
    enable32Bit = true;
    extraPackages = with pkgs; [intel-media-driver];
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
    "pcie_aspm=force" # Reduz calor da dGPU em idle (~40% economia PCIe)
    "nvme_load=1" # Carrega o NVMe precocemente no initrd
    "preempt=full" # Preempção total do kernel Zen
    # Performance tweaks para llama.cpp / inferência:
    # NOTA: intel_idle.max_cstate=1 removido — aumenta calor sem benefício significativo
    # Se observar freezes, considerar adicionar de volta
    "nvme_core.io_timeout=10" # Timeout I/O NVMe mais agressivo
    # Fan control para Acer Nitro V15 — habilita acer_wmi fan sysfs:
    "acer_wmi.predator_v4=1" # Exibe /sys/class/hwmon/hwmonX/pwm* para controle de ventoinha
  ];

  # =========================================================================
  # 2. SERVIÇOS JARVIS & IA (Host)
  # =========================================================================
  # Master toggle: services.jarvis.enable = true (já definido acima)
  # Quando desabilitado, NENHUM serviço Jarvis inicia.
  services.llama-cpp-server.enable = true;
  # (03/11) SEM override de defaultModel: a fonte única é models.nix
  # (routing.default = 4B-MTP+LoRA :8092; o grupo que sobe no boot é
  # routing.bootModel.host = bonsai → grupo prism :8080). O override antigo
  # ("bonsai") reintroduzia o bonsai como default do APP — o dono pediu
  # "tira o bonsai de default" (26/10).
  services.llama-cpp-embeddings.enable = true;
  services.llama-cpp-rerank.enable = true;
  # (03/11) ASR da voz duplex. Sem ele o whisper-server morre no boot com
  # CUDA OOM (VRAM disputada com o 4B-MTP) e o duplex fica SURDO —
  # sintoma "falo com ele e nada". Medido: GPU 198-341 ms/segmento.
  services.whisper-server.enable = true;
  # services.qdrant.enable é definido por qdrant.nix (condicional a jarvis.enable)
  services.jarvis-vault.enable = false;
  services.jarvis-webui.enable = true;
  services.jarvis-webui-frontend.enable = true;
  # Nightwatch: manutenção autônoma limitada e reportada (opt-in explícito).
  # Roda pouco, em janela sem colisão, com relatório (Telegram/logs/progress.jsonl)
  # para saber o que melhorou de fato.
  services.jarvis.nightwatch = {
    enable = true;
    onCalendar = "*-*-* 03:30:00";
    tasks = 3;
    projects = [ "nixos-ai" ];
    extraArgs = [ "--report-telegram" ];
  };
  services.jarvis-idle.enable = true;
  services.jarvis-watchdog.enable = true;
  services.jarvis-heal.enable = true;
  services.jarvis-telegram.enable = true;
  # Espelho systemd do /etc/litellm.env (03/11): o systemd recusa `export KEY=`
  # e LOGA o valor da chave no journal (206 linhas/dia com sk-* e nvapi-*).
  services.jarvis-keys-env.enable = true;
  services.jarvis-gaming.enable = true;

  # Moondream2 local para tagging de sprites. NAO sobe no boot (VRAM 6 GB =
  # 1 LLM por vez): `systemctl start vision-moondream` quando precisar.
  # Conflita com llama-cpp-upstream e faz o swap sozinho via vram-guard.
  services.vision-moondream.enable = true;
  services.litellm.enable = false;
  programs.freebuff.enable = true;
  programs.jarvis-scripts.enable = false;

  # environment.etc."litellm.env" removed — litellm service disabled (services.litellm.enable = false)
  # API keys live in /etc/litellm.env managed manually with chmod 644

  environment.etc."nanorc".text = ''
    set tabsize 2
    set tabstospaces
  '';

  # =========================================================================
  # 3. KERNEL, PERFORMANCE E ZRAM
  # =========================================================================
  # boot.loader: definido em boot.nix (systemd-boot + EFI)
  # boot.kernelPackages: definido em kernel.nix (linuxPackages_zen)
  # zramSwap: definido em zram.nix (zstd, 50%, priority 999)

  services.thermald.enable = true;
  services.llama-fan-control.enable = true;
  powerManagement.cpuFreqGovernor = "performance";

  boot.kernel.sysctl = {
    "vm.swappiness" = 10;
    "kernel.sched_child_runs_first" = 1; # Processos filhos rodam mais rápido (inferência)
    "net.core.default_qdisc" = "fq_codel";
    "net.ipv4.tcp_congestion_control" = "bbr";
    "net.ipv4.tcp_low_latency" = 1; # Baixa latência de rede
    "net.core.netdev_max_backlog" = 16384; # Expande fila contra gargalo da Claro
    "net.ipv4.tcp_fastopen" = 3; # Acelera conexões HTTP das tools web
  };

  # I/O scheduler para NVMe: 'none' é melhor que 'kyber' para devices non-rotational
  services.udev.extraRules = ''
    ACTION=="add|change", KERNEL=="nvme[0-9]*n[0-9]*", ATTR{queue/rotational}=="0", ATTR{queue/scheduler}="none"
  '';

  # (03/11) agents-keepawake usa `systemd-inhibit --what=sleep:idle` e falhava
  # a cada boot com "Access denied as the requested operation requires
  # interactive authentication": o user manager sobe o serviço antes de haver
  # sessão logind, então o polkit não reconhece o subject. Regra pontual para
  # a conta do dono (só as duas ações de inibição, nada além disso).
  security.polkit.extraConfig = ''
    polkit.addRule(function(action, subject) {
      if ((action.id == "org.freedesktop.login1.inhibit-block-idle" ||
           action.id == "org.freedesktop.login1.inhibit-block-sleep") &&
          subject.user == "nixos") {
        return polkit.Result.YES;
      }
    });
  '';

  # Regras de tmpfiles: limpeza e suporte a No CoW (+C) para Btrfs
  # NOTA: /var/lib/qdrant e /var/lib/jarvis/models já são criados por
  # qdrant.nix e jarvis-env.nix respectivamente (condicionais a jarvis.enable)
  systemd.tmpfiles.rules = [
    "d /var/tmp 1777 root root 14d"
    # Modelos/artefatos de IA em nvme1 (rápido). Dados migrados de ~/models.
    "d /var/lib/ai 0755 nixos users -"
    "d /var/lib/ai/models 0755 nixos users -"
  ];

  # =========================================================================
  # 4. SESSÃO, LOGIN E INTERFACE (Greetd + Hyprland)
  # =========================================================================
  # tuigreet: TUI simples que roda direto no TTY (sem compositor)
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
  # (11/11, dono: "internet horrivelmente lenta, celular mais rapido na mesma rede")
  # Medido: PC no wifi 2.4GHz ch11 com -75 dBm; power save ON dormia o chip entre
  # pacotes (9 Mbps no download de 10MB). Powersave off dobra o throughput (19 Mbps)
  # e o ASPM disable e o fix documentado (Arch Wiki) da latencia alta do mt7921e.
  # O outro fator medido foi o tunel Mullvad assumindo a rota default (wg0-mullvad):
  # o servico fica INATIVO por padrao e so uma janela que precise dele deve ligar.
  networking.networkmanager.wifi.powersave = false;
  boot.extraModprobeConfig = "options mt7921e disable_aspm=1";
  time.timeZone = lib.mkForce "America/Sao_Paulo";
  i18n.defaultLocale = "pt_BR.UTF-8";
  # DNS (11/11, dono: 9.9.9.9 primario, 1.1.1.1 secundario, resto livre).
  # Medido nesta rede: Quad9 17-18 ms, Cloudflare 20 ms, Google 27-34 ms, e o
  # 192.168.1.1 do roteador da TIMEOUT em DNS (era o 1o do resolv.conf e cada
  # nome pagava 3 timeouts de 5 s: getent github.com levava 15,1 s).
  # dns = "none": o NetworkManager para de reescrever o resolv.conf, entao a
  # lista abaixo e a unica fonte (o DNS do DHCP/roteador nao entra mais).
  # Cascata: 127.0.0.1/::1 = blocky (DoH) e 9.9.9.9/1.1.1.1/8.8.8.8 = fallback
  # em texto claro so se o proxy local morrer. glibc usa os 3 primeiros.
  networking.networkmanager.dns = "none";
  networking.nameservers = ["127.0.0.1" "::1" "9.9.9.9" "1.1.1.1" "8.8.8.8"];
  # openresolv descarta os nameservers nao-locais quando ve um resolver local
  # (resolv_conf_local_only=YES por padrao). Sem NO, o fallback 9.9.9.9/1.1.1.1
  # nunca chega ao /etc/resolv.conf e um blocky morto deixa o PC sem DNS.
  networking.resolvconf.extraConfig = "resolv_conf_local_only=NO";

  # DNS over HTTPS (11/11, dono pediu): toda consulta sai por HTTPS na 443,
  # tanto IPv4 quanto IPv6. O blocky escuta so no loopback (sem resolver
  # aberto) e usa parallel_best entre Quad9/Cloudflare/Google: manda para 2 e
  # fica com a resposta mais rapida, entao um provedor fora do ar nao derruba
  # a resolucao. bootstrapDns mapeia os hostnames DoH para IPs estaticos: nao
  # existe consulta em texto claro nem na inicializacao.
  services.blocky = {
    enable = true;
    settings = {
      ports.dns = ["127.0.0.1:53" "[::1]:53"];
      # (11/11) v4, NAO dual. Medido com o Mullvad conectado: o tunel nao tem
      # IPv6 (`v6 gw: None`), entao `dual` tentava IPv6 primeiro e cada nome
      # NAO cacheado custava 3,1-3,25 s (o `timeout: 3s` abaixo) antes de cair
      # para IPv4. Sem VPN: 3-5 ms. `v4` elimina a classe inteira de stall.
      connectIPVersion = "v4";
      upstreams = {
        init.strategy = "fast";
        strategy = "parallel_best";
        timeout = "3s";
        groups.default = [
          "https://dns.quad9.net/dns-query"
          "https://cloudflare-dns.com/dns-query"
          "https://dns.google/dns-query"
        ];
      };
      bootstrapDns = [
        {
          upstream = "https://dns.quad9.net/dns-query";
          ips = ["9.9.9.9" "149.112.112.112" "2620:fe::fe" "2620:fe::9"];
        }
        {
          upstream = "https://cloudflare-dns.com/dns-query";
          ips = ["1.1.1.1" "1.0.0.1" "2606:4700:4700::1111" "2606:4700:4700::1001"];
        }
        {
          upstream = "https://dns.google/dns-query";
          ips = ["8.8.8.8" "8.8.4.4" "2001:4860:4860::8888" "2001:4860:4860::8844"];
        }
      ];
      caching = {
        maxTime = "1h";
        prefetching = true;
      };
      queryLog.type = "none";
      log.level = "info";
    };
  };
  networking.firewall.allowedTCPPorts = [22 8080 8081 4000 5353 8099 47984 47989 47990 48010 9090 5173 8090 8091]; # 8099 = karaok cast (letra+som p/ TV); 47984-48010 = Sunshine/Moonlight
  networking.firewall.allowedUDPPorts = [47998 47999 48000 48002 48010]; # Sunshine/Moonlight stream

  # (26/10, dono pediu) PROTON VPN — checkReversePath = false é REQUERIDO
  # pelo Proton VPN no NixOS (sem isso o routing falha). ATENÇÃO: Tailscale
  # também usa WireGuard — sem conflito (interfaces separadas), mas as duas
  # VPNs podem competir por rotas se ambas ativas.
  # (11/11, FIX REBUILD) mkForce: o módulo services.mullvad-vpn (08/11) define
  # "loose" sem prioridade, o que gera conflito de definições. Tailscale usa
  # mkDefault (não conflita). Com mkForce o valor efetivo continua `false`,
  # como o Proton exige.
  networking.firewall.checkReversePath = lib.mkForce false;

  # (11/11) MULLVAD x TAILSCALE — coexistem, medido e implementado.
  # Sem isto, com o app do Mullvad conectado o tailnet inteiro morre: ele
  # instala a regra `not from all fwmark 0x6d6f6c65 lookup 1836018789` e manda
  # 100.64.0.0/10 para dentro do tunel, onde nao existe rota. O firewall dele
  # tambem e default-deny e a lista de "LAN" cobre RFC1918 + fc00::/7, mas NAO
  # o CGNAT do Tailscale.
  # A chave sao os DOIS marks: o `ct mark` e o que a firewall do Mullvad
  # consulta (so `meta mark` nao basta, foi medido: rota certa, ping 100% de
  # perda); o `meta mark` e o que faz a regra de rota dele pular o pacote.
  # Depois disso o fluxo cai na regra 5270 do Tailscale (`lookup 52`) e sai
  # por tailscale0. Medido com o Mullvad em br-for-wg-002: ping 0% de perda,
  # conexao direta, 136 ms (contra 60 ms sem VPN, o custo do relay).
  # NAO excluir o tailscaled do tunel (`mullvad split-tunnel add`): medido,
  # quebra (100% de perda e `tailscale ping` em timeout).
  # Referencias: theorangeone.net/posts/tailscale-mullvad, Mullvad issue #5921.
  #
  # Vai como unit propria e nao como `networking.nftables.tables`: aquela opcao
  # so e aplicada com `networking.nftables.enable = true`, e este host usa o
  # firewall em iptables-nft (`iptables v1.8.13 (nf_tables)`). A tabela
  # `inet mullvad_tailscale` convive com as tabelas `ip filter`/`ip mangle` do
  # iptables-nft; o kernel percorre as duas. Prioridade 0 roda DEPOIS do mangle
  # do iptables (-150), entao o mark aplicado aqui e o que vale.
  systemd.services.mullvad-tailscale-bypass = {
    description = "Marks Tailscale CGNAT traffic so the Mullvad tunnel does not swallow it";
    wantedBy = ["multi-user.target"];
    after = ["firewall.service" "mullvad-daemon.service"];
    serviceConfig = {
      Type = "oneshot";
      RemainAfterExit = true;
      ExecStart = "${pkgs.nftables}/bin/nft -f ${pkgs.writeText "mullvad-tailscale.nft" ''
        table inet mullvad_tailscale {
          chain output {
            type route hook output priority 0; policy accept;
            ip daddr 100.64.0.0/10 ct mark set 0x00000f41 meta mark set 0x6d6f6c65;
            ip6 daddr fd7a:115c:a1e0::/48 ct mark set 0x00000f41 meta mark set 0x6d6f6c65;
          }
        }
      ''}";
      ExecStop = "${pkgs.nftables}/bin/nft delete table inet mullvad_tailscale";
    };
  };

  # (11/11) blocky + tunel do Mullvad: o pool HTTP/2 do blocky nao sobrevive a
  # recriacao da wg0-mullvad. O socket fica preso ao IP de origem antigo
  # (10.168.67.216) e toda resolucao NAO cacheada passa a custar o timeout de
  # 3 s do grupo de upstreams, ate o processo morrer. Medido 11/11: 3123, 3186,
  # 3113 e 3135 ms com o tunel recem-reconectado; `systemctl restart blocky`
  # devolve 118, 113, 127 e 154 ms na hora. O blocky isolado em /tmp, mesma
  # config, responde em 109-1677 ms: nao e config, e estado de conexao.
  # O tunel renegocia sozinho (10 "Resetting firewall policy" em 70 min,
  # medido), e cada renegociacao derruba o pool outra vez. Por isso o vigia:
  # reinicia o blocky a cada transicao da interface, com cooldown de 15 s para
  # nao virar tempestade quando o Mullvad reconecta em sequencia.
  # NAO e `PartOf`/`BindsTo` na interface: isso pararia o DNS quando o dono
  # desliga o VPN (o app e manual, pedido dele).
  systemd.services.blocky-tunnel-watch = {
    description = "Restarts blocky when wg0-mullvad appears or disappears";
    wantedBy = ["multi-user.target"];
    after = ["mullvad-daemon.service" "blocky.service"];
    serviceConfig = {
      Type = "simple";
      Restart = "always";
      RestartSec = 5;
      ExecStart = "${pkgs.writeShellScript "blocky-tunnel-watch" ''
        export PATH=${config.systemd.package}/bin:${pkgs.iproute2}/bin:${pkgs.coreutils}/bin
        cooldown=0
        ${pkgs.iproute2}/bin/ip monitor link | while IFS= read -r line; do
          case "$line" in
            *wg0-mullvad*)
              now=$(${pkgs.coreutils}/bin/date +%s)
              if [ "$now" -ge "$cooldown" ]; then
                cooldown=$((now + 15))
                sleep 4
                ${config.systemd.package}/bin/systemctl restart blocky.service
                echo "wg0-mullvad changed; blocky restarted"
              fi
              ;;
          esac
        done
      ''}";
    };
  };

  # opencode serve — controle da AGENTE pelo celular, sem TTY (2026-10-02,
  # pedido do dono). Aberta SÓ no tailscale0, nunca na LAN: o tailnet já é
  # autenticado por dispositivo, então o celular (motorola-edge) entra sem
  # expor o agente a vizinhos. O servidor EXIGE senha
  # (OPENCODE_SERVER_PASSWORD) — sem ela ele sobe "unsecured" e dá acesso às
  # chaves de API da máquina a qualquer um que alcance a porta.
  # Uso: celular abre http://100.121.100.103:4599 ; o TUI vira cliente dele
  # com `opencode attach http://127.0.0.1:4599` (assim os dois veem a MESMA
  # sessão, com busy-state coordenado).
  networking.firewall.interfaces.tailscale0 = {
    allowedTCPPorts = [4599 5173 8090 8091];
  };

  # opencode serve com nome curto (2026-10-02). O MagicDNS do Tailscale só
  # devolve IPv6 para `nitro-v15`, e o servidor escuta só o IPv4 100.121.100.103
  # — então o nome não resolvia para o lado certo. `/etc/hosts` não serve
  # (é symlink pro nix store, read-only), então vai por extraHosts.
  # O IP do Tailscale é estável por node; só muda se refizer o login do tailnet.
  # ATENÇÃO AO TIPO: networking.extraHosts é uma STRING (linhas "IP host"),
  # não um attrset — passar attrset dá "A definition for option
  # `networking.extraHosts' is not of type `strings concatenated with \n`".
  networking.extraHosts = ''
    100.121.100.103 oc nitro-v15
    # celular no mesmo tailnet (Android via Termux/Moonlight). O MagicDNS JÁ
    # resolve isto para IPv4 (`getent hosts motorola-edge`), então esta linha é
    # conveniência/pin, não necessidade. CUIDADO: IP do Tailscale vale até o nó
    # refazer o login do tailnet — se `motorola-edge` parar de resolver, cheque
    # `tailscale status | grep motorola` e ajuste aqui.
    100.104.175.123 motorola-edge
  '';

  services.openssh = {
    enable = true;
    settings.PermitRootLogin = "prohibit-password"; # Segurança: login root só por chave SSH
  };

  # Tailscale — VPN mesh p/ acesso remoto (SSH Termux + Moonlight no 4G).
  # Após rebuild: `sudo tailscale up` (login 1x) → celular no mesmo tailnet
  # (app Android) → ssh nixos@<ip-100.x> / Moonlight pelo IP tailnet.
  services.tailscale = {
    enable = true;
    openFirewall = true;
  };

  # nscd/nsncd DESABILITADO (12/10, decisão delegada pelo dono: "vc decide").
  # Evidência: nsncd 1.5.3 sai com código 0 ~50ms–3s após o primeiro tráfego
  # NSS real (reproduzido fora do systemd: `getent hosts` e
  # `getent group netdev` matam o daemon; 5s idle sobrevive) → Restart=always
  # reacende 5× em 10s → start-limit-hit → nss-lookup.target dead em TODO
  # boot (11/10 e 12/10). nsncd aqui é proxy SEM cache (zero benefício) e o
  # fallback direto do glibc já atende tudo (getent/docker/login OK com ele
  # morto desde o boot; `.local` via glibc já não resolve hoje — sem regressão).
  # `system.nssModules = []` é exigido pelo assert do nixpkgs ao desligar o
  # nscd. Contra-indicação (módulo NSS `systemd` p/ DynamicUser): aceita —
  # só units-template inativas usam DynamicUser. Reverter: apagar as 2 linhas.
  services.nscd.enable = false;
  system.nssModules = lib.mkForce [];

  users.users.${user} = {
    isNormalUser = true;
    extraGroups = ["wheel" "video" "audio" "networkmanager" "qdrant" "input" "uinput" "docker"];
  };

  security.sudo.extraRules = [
    {
      users = [user];
      commands = [
        {
          command = "ALL";
          options = ["NOPASSWD"];
        }
      ];
    }
  ];

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
    experimental-features = ["nix-command" "flakes"];
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
    trusted-users = ["root" user];
    keep-outputs = true;
    keep-derivations = true;
  };

  # Stylix injeta um overlay (nixos-icons) no escopo do home-manager, o que
  # dispara o warning do HM (useGlobalPkgs + nixpkgs.overlays será erro no
  # futuro). Mesmo padrão já aplicado em hosts/nixos-lab/configuration.nix.
  home-manager.users.${user}.nixpkgs.overlays = lib.mkForce null;

  # =========================================================================
  # 7. SISTEMA
  # =========================================================================
  system.stateVersion = stateVersion;
}
