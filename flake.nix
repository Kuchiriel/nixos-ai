{
  description = "My system configuration";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-26.05";
    nixpkgs-unstable.url = "github:nixos/nixpkgs/nixos-unstable";

    opencode-flake.url = "github:aodhanhayter/opencode-flake";

    # m3ta-nixpkgs: submodule com pacotes sidecar, stt-ptt, talk etc.
    # git+file: acessa o submodule como repositório Git independente
    m3ta-nixpkgs = {
      url = "git+file:///home/nixos/projects/nixpkgs";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    # m3ta AGENTS repo: agentes canônicos para coding agents (opencode, pi, claude-code)
    agents = {
      url = "git+https://code.m3ta.dev/m3tam3re/AGENTS";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    home-manager = {
      url = "github:nix-community/home-manager/release-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
    };

    stylix = {
      url = "github:danth/stylix/release-26.05";
      inputs.nixpkgs.follows = "nixpkgs";
      # Fix upstream: o stylix 26.05 pinava um base16.nix sem a cor
      # `bright-yellow` (issue nix-community/stylix#1635), quebrando a
      # avaliação dos targets starship/alacritty com qualquer scheme.
      inputs.base16.url = "github:SenchoPens/base16.nix";
    };

    disko = {
      url = "github:nix-community/disko/latest";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = { self, nixpkgs, nixpkgs-unstable, home-manager, stylix, disko, m3ta-nixpkgs, ... }@inputs: let
    system = "x86_64-linux";
    user = "nixos";

    # Modelos de IA baixados declarativamente (store imutável — o host nasce com tudo)
    aiModels = nixpkgs.legacyPackages.${system}.callPackage ./modules/ai/models.nix { };

    # Geração atual dos índices de busca do search.nixos.org (descoberta via API
    # custa ~20s por processo — o cache pré-computado elimina as probes).
    # Conferir quando atualizar o pin do nixpkgs: `curl -s .../backend/latest-XX-nixos-unstable/_count`.
    nixosIndexGeneration = 45;

    # Overlay combinado: AI (llama-cpp, mcp-nixos-fast, jarvis, aiModels)
    # + m3ta packages (sidecar, stt-ptt, talk)
    #
    # O overlay m3ta-packages é importado DENTRO do aiOverlay para garantir
    # que as dependências (opencode, td, tmux, whisper-cpp etc.) sejam
    # resolvidas corretamente via `final.callPackage`.
    m3taPackagesOverlay = import ./overlays/m3ta-packages.nix { inherit inputs; };

    aiOverlay = final: prev: {
      # llama.cpp vem do unstable (24.11/26.05 pinned ficam desatualizados)
      llama-cpp = (import nixpkgs-unstable {
        system = prev.stdenv.hostPlatform.system;
 config.allowUnfree = true;
      }).llama-cpp.override {
        cudaSupport = true;
      };
      #llama-cpp = nixpkgs-unstable.legacyPackages.${prev.stdenv.hostPlatform.system}.llama-cpp;
      #llama-cpp = inputs.nixpkgs-unstable.legacyPackages.${system}.llama-cpp;
      # mcp-nixos com cache de canais pré-computado (store) + FALLBACK atualizado:
      # a descoberta de canais faz 20 probes HTTP sequenciais por processo novo
      # (~20s na primeira consulta); o cache declarativo zera esse custo.
      mcp-nixos-fast = prev.mcp-nixos.overridePythonAttrs (old: {
        patches = (old.patches or [ ]) ++ [ ./modules/ai/patches/mcp-nixos-channel-cache.patch ];
        postInstall = (old.postInstall or "") + ''
          cache="$out/share/mcp-nixos/channels.json"
          mkdir -p "$(dirname "$cache")"
          cat > "$cache" <<'EOF'
          {
            "available": {
              "latest-${toString nixosIndexGeneration}-nixos-unstable": "disponível",
              "latest-${toString nixosIndexGeneration}-nixos-25.11": "disponível",
              "latest-${toString nixosIndexGeneration}-nixos-25.05": "disponível"
            },
            "resolved": {
              "unstable": "latest-${toString nixosIndexGeneration}-nixos-unstable",
              "stable": "latest-${toString nixosIndexGeneration}-nixos-25.11",
              "25.05": "latest-${toString nixosIndexGeneration}-nixos-25.05",
              "25.11": "latest-${toString nixosIndexGeneration}-nixos-25.11",
              "26.05": "latest-${toString nixosIndexGeneration}-nixos-26.05",
              "beta": "latest-${toString nixosIndexGeneration}-nixos-25.11"
            }
          }
          EOF
        '';
      });

      # Pacote Python do JARVIS (com voz: STT faster-whisper + TTS Kokoro).
      # Usar withVoice como default para que 'jarvis voice' funcione no wakeword.
      jarvis = (prev.callPackage ./modules/ai/package.nix { mcpNixos = final.mcp-nixos-fast; }).withVoice;
      # Jarvis com voz (STT + TTS) — mais pesado (torch/ctranslate2)
      jarvis-voice = (prev.callPackage ./modules/ai/package.nix { mcpNixos = final.mcp-nixos-fast; }).withVoice;
      # Modelos declarativos (openwakeword, kokoro, whisper)
      inherit aiModels;

      # ── Pacotes m3ta-nixpkgs (sidecar, stt-ptt, talk) ─────────────
      # Importados via overlay separado para manter o código organizado.
      # As dependências são resolvidas via `final.callPackage`.
    } // (m3taPackagesOverlay final prev);

    hosts = [
      {
        hostname = "nixos-lab";
        # stateVersion reflete a versão de instalação inicial (24.11) e não é
        # alterado em upgrades — controla defaults comportamentais do módulo.
        stateVersion = "24.11";
      }
      {
        hostname = "nitro-v15";
        stateVersion = "24.11"; # ou a versão que utilizou na instalação inicial
      }
    ];

    makeSystem = { hostname, stateVersion }: nixpkgs.lib.nixosSystem {
      inherit system;
      specialArgs = {
        inherit inputs stateVersion hostname user;
      };

      modules = [
        # Passa o pkgs estendido (overlay + allowUnfree) direto via nixpkgs.pkgs.
        # Evita `nixpkgs.overlays`/`nixpkgs.config` em conjunto com
        # `home-manager.useGlobalPkgs` (deprecated — warning de avaliação).
        {
          nixpkgs.pkgs = import nixpkgs {
            inherit system;
            config = { allowUnfree = true; };
            overlays = [ aiOverlay ];
          };
        }

        # Disko — partições declarativas (só afeta hosts que importam disko.nix)
        disko.nixosModules.disko

        ./hosts/${hostname}/configuration.nix
        stylix.nixosModules.stylix

        # Função de módulo: recebe o config NixOS para repassar o switch
        # central services.jarvis.environment ao home-manager (água).
        ({ config, ... }: {
          imports = [ home-manager.nixosModules.home-manager ];
          home-manager.useGlobalPkgs = true;
          home-manager.useUserPackages = true;
          home-manager.extraSpecialArgs = {
            inherit user;
            inherit inputs;
            homeStateVersion = stateVersion;
            # Água: o home-manager bebe do switch central de ambiente
            # (services.jarvis.environment) — waybar/mpvpaper/hyprland
            # decidem seus perfis aqui, sem hardcode por host.
            jarvisEnvironment = config.services.jarvis.environment;
          };
          home-manager.users.${user} = {
            imports = [
              ./home-manager/home.nix
              # stylix 26.05: o output `homeManagerModules` foi renomeado p/ `homeModules`
              stylix.homeModules.stylix
            ];
          };
        })
      ];
    };

  in {
    nixosConfigurations = nixpkgs.lib.foldl' (configs: host:
      configs // {
        "${host.hostname}" = makeSystem {
          inherit (host) hostname stateVersion;
        };
      }) {} hosts;

   # Permite `nix build .#jarvis` / `nix run .#jarvis`
   # e `nix build .#sidecar` / `nix build .#stt-ptt` / `nix build .#talk`
    packages.${system} = {
      jarvis = (nixpkgs.legacyPackages.${system}.extend aiOverlay).jarvis;
      jarvis-voice = (nixpkgs.legacyPackages.${system}.extend aiOverlay).jarvis-voice;
      # m3ta-nixpkgs packages
      sidecar = (nixpkgs.legacyPackages.${system}.extend aiOverlay).sidecar;
      stt-ptt = (nixpkgs.legacyPackages.${system}.extend aiOverlay).stt-ptt;
      talk = (nixpkgs.legacyPackages.${system}.extend aiOverlay).talk;
    };

    # Ambiente de desenvolvimento interativo (`nix develop`)
    devShells.${system}.default = let
      pkgs = import nixpkgs {
        inherit system;
        config = { allowUnfree = true; };
        overlays = [ aiOverlay ];
      };
    in pkgs.mkShell {
#       inputsFrom = [ pkgs.jarvis ];
      packages = [
        pkgs.python313Packages.pytest
        pkgs.python313Packages.hypothesis
      ];
      shellHook = ''
        export PYTHONPATH="''${FLAKE_ROOT:-$(git rev-parse --show-toplevel)}/modules/ai/jarvis/src:$PYTHONPATH"
        export FLAKE_ROOT="''${FLAKE_ROOT:-$(git rev-parse --show-toplevel)}"
      '';
    };
  };
}
