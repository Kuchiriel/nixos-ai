{
  description = "My system configuration";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-26.05";
    nixpkgs-unstable.url = "github:nixos/nixpkgs/nixos-unstable";

    opencode-flake.url = "github:aodhanhayter/opencode-flake";

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

  outputs = {
    nixpkgs,
    nixpkgs-unstable,
    home-manager,
    stylix,
    disko,
    ...
  } @ inputs: let
    system = "x86_64-linux";
    user = "nixos";

    # Modelos de IA baixados declarativamente (store imutável — o host nasce com tudo)
    aiModels = nixpkgs.legacyPackages.${system}.callPackage ./modules/ai/models.nix {};

    # Geração atual dos índices de busca do search.nixos.org (descoberta via API
    # custa ~20s por processo — o cache pré-computado elimina as probes).
    # Conferir quando atualizar o pin do nixpkgs: `curl -s .../backend/latest-XX-nixos-unstable/_count`.
    nixosIndexGeneration = 45;

    aiOverlay = final: prev:
      {
        # llama.cpp vem do unstable (24.11/26.05 pinned ficam desatualizados)
        llama-cpp =
          (import nixpkgs-unstable {
            inherit system;
            config.allowUnfree = true;
          }).llama-cpp.override {
            cudaSupport = true;
          };

        # mcp-nixos com cache de canais pré-computado
        mcp-nixos-fast = if (prev ? mcp-nixos) then 
          prev.mcp-nixos.overridePythonAttrs (old: {
            patches = (old.patches or []) ++ [./modules/ai/patches/mcp-nixos-channel-cache.patch];
            postInstall =
              (old.postInstall or "")
              + ''
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
          })
        else 
          nixpkgs-unstable.legacyPackages.${system}.python3Packages.mcp;

        # Pacote Python do JARVIS
        jarvis = (prev.callPackage ./modules/ai/package.nix {mcpNixos = final.mcp-nixos-fast;}).base;
        jarvis-voice = (prev.callPackage ./modules/ai/package.nix {mcpNixos = final.mcp-nixos-fast;}).withVoice;
        
        # CORREÇÃO: Mapeamento com os novos nomes oficiais do Nixpkgs + instanciando com allowUnfree ativo
        kilo = (import nixpkgs-unstable { inherit system; config.allowUnfree = true; }).kilo;
        antigravity-ide = (import nixpkgs-unstable { inherit system; config.allowUnfree = true; }).antigravity-ide;

        inherit aiModels;
      };


    hosts = [
      {
        hostname = "nixos-lab";
        stateVersion = "24.11";
      }
      {
        hostname = "nitro-v15";
        stateVersion = "24.11";
      }
    ];

    makeSystem = {
      hostname,
      stateVersion,
    }:
      nixpkgs.lib.nixosSystem {
        # Corrigido: Não passamos 'system' aqui na raiz para evitar a quebra do system.build.toplevel no NixOS 26.05/unstable
        specialArgs = {
          inherit inputs stateVersion hostname user;
        };

        modules = [
          # Definição segura da plataforma e injeção de pacotes via nixpkgs.pkgs
          {
            nixpkgs.hostPlatform = system;
            nixpkgs.pkgs = import nixpkgs {
              inherit system;
              config = {allowUnfree = true;};
              overlays = [aiOverlay];
            };
          }

          # Disko — partições declarativas (só afeta hosts que importam disko.nix)
          disko.nixosModules.disko

          ./hosts/${hostname}/configuration.nix
          stylix.nixosModules.stylix

          # Configuração do Home-Manager
          ({config, ...}: {
            imports = [home-manager.nixosModules.home-manager];
            home-manager = {
              useGlobalPkgs = true;
              useUserPackages = true;
              extraSpecialArgs = {
                inherit user inputs;
                homeStateVersion = stateVersion;
                jarvisEnvironment = config.services.jarvis.environment or "production";
                projectLib = import ./lib {
                  inherit (nixpkgs.lib) lib;
                  pkgs = nixpkgs.legacyPackages.${system};
                };
              };
              users.${user} = {
                imports = [
                  ./home-manager/home.nix
                  stylix.homeModules.stylix
                ];
              };
            };
          })
        ];
      };
  in {
    nixosConfigurations = nixpkgs.lib.foldl' (configs: host:
      configs
      // {
        "${host.hostname}" = makeSystem {
          inherit (host) hostname stateVersion;
        };
      }) {}
    hosts;

    # Permite `nix build .#jarvis` / `nix run .#jarvis`
    packages.${system} = let
      pkg = nixpkgs.legacyPackages.${system}.extend aiOverlay;
    in {
      inherit (pkg) jarvis jarvis-voice kilo antigravity-ide;
    };

    # ── lib: fonts, colors, ports (nosso próprio lib/) ──────────────
    lib.nixos-ai = import ./lib {
      inherit (nixpkgs.lib) lib;
      pkgs = nixpkgs.legacyPackages.${system};
    };

    # Ambiente de desenvolvimento interativo (`nix develop`)
    devShells.${system}.default = let
      pkgs = import nixpkgs {
        inherit system;
        config = {allowUnfree = true;};
        overlays = [aiOverlay];
      };
    in
      pkgs.mkShell {
        inputsFrom = [pkgs.jarvis];
        packages = with pkgs; [
          python313Packages.pytest
          python313Packages.hypothesis
          python313Packages.pymupdf  
          python313Packages.ebooklib  
          python313Packages.beautifulsoup4  
          python313Packages.kokoro  
          python313Packages.soundfile  
          
          # CLI de IA adicionados ao ambiente de desenvolvimento interativo
          kilocode-cli
          antigravity

          # Higiene Nix
          statix
          deadnix
          alejandra
        ];
        shellHook = ''
          export PYTHONPATH="''${FLAKE_ROOT:-$(git rev-parse --show-toplevel)}/modules/ai/jarvis/src:$PYTHONPATH"
          export FLAKE_ROOT="''${FLAKE_ROOT:-$(git rev-parse --show-toplevel)}"
        '';
      };
  };
}

