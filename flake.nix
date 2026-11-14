{
  description = "nixos-ai system configuration";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-26.05";
    # Kernel 7.2 + driver NVIDIA 615.71.09 (new_feature): 26.05 pina zen 7.1.8
    # (ok) mas o driver 615 só existe no master do nixpkgs. Fallback enquanto
    # o 26.05 não bumpa — ver overlay aiOverlay abaixo.
    nixpkgs-master.url = "github:nixos/nixpkgs/master";
    nixpkgs-unstable.url = "github:nixos/nixpkgs/nixos-unstable";

    # MetaTrader 5 (EA GOLD FAKEOUT): o wine 11 do 26.05 é detectado pelo
    # anti-debugger do MT5 e aborta installer E terminal (consenso multi-
    # usuário do fórum mql5 503128, jan/2026; WINEDEBUG=-all não resolve).
    # Wine 10.0 = versão que funciona. O winetricks do 26.05 também quebra
    # com builds WoW64 (nixpkgs#338367) — ambos vêm do pin 25.11.
    nixpkgs-wine10.url = "github:nixos/nixpkgs/nixos-25.11";

    opencode-flake.url = "github:dan-online/opencode-nix";

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
      # Fix 2026-09-14: tinted-schemes pinado com drv sumido do store/cache
      # (base16-schemes-0-unstable-2026-01-15.drv is not valid), quebrando
      # a avaliação do nixos-lab. Segue HEAD como os demais inputs.
      inputs.tinted-schemes.url = "github:tinted-theming/schemes";
    };

    disko = {
      url = "github:nix-community/disko/latest";
      inputs.nixpkgs.follows = "nixpkgs";
    };
  };

  outputs = {
    nixpkgs,
    nixpkgs-unstable,
    nixpkgs-master,
    nixpkgs-wine10,
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
        # 03/11: UM pacote só (jarvis, com a voz dentro). O split
        # jarvis/jarvis-voice existia só para não arrastar torch no
        # `base`, mas o `base` não tinha NENHUM consumidor de runtime —
        # todos usam a voz (host, wakeword, MCP, vscode).
        jarvis = (prev.callPackage ./modules/ai/package.nix {mcpNixos = final.mcp-nixos-fast; inherit aiModels;}).jarvis;
        # (30/09) Ambiente de TESTE do nightwatch: as deps REAIS do jarvis +
        # pytest. Sem as deps, os testes do projeto falhavam com
        # "No module named 'requests'" e o harness culpava o modelo.
        # Montado pelo Nix — Python só obedece (JARVIS_TEST_PYTHON).
        jarvis-test-env = final.python3.withPackages (ps:
          [ ps.pytest ps.pytest-timeout ps.hypothesis ]
          ++ (prev.callPackage ./modules/ai/package.nix {mcpNixos = final.mcp-nixos-fast; inherit aiModels;}).pythonDeps);

        # ── NVIDIA no linux-zen 7.2.x (10/10) ───────────────
        # Kernel zen >= 7.2 quebrou o driver 595.71.05 (strncpy removido no
        # kernel + rename drm_atomic_state → commit). Fix comunitário existe
        # (github.com/NVIDIA/open-gpu-kernel-modules#1224), mas o suporte
        # oficial é o driver 615.71.09 (new_feature), bumpado só no master
        # do nixpkgs. Overlay injeta o driver 615 (com kernel zen 7.2.9 do
        # master) sobre o linuxPackages_zen atual.
        # — remove quando o nixos-26.05 bumpar zen 7.2 + driver 615.
        linuxPackages_zen = let
          masterPkgs = import nixpkgs-master {inherit system; config.allowUnfree = true;};
          masterZen = masterPkgs.linuxKernel.packages.linux_zen;
        in
          (prev.linuxPackages_zen.extend (finalPackages: prevPackages: {
            nvidiaPackages = prevPackages.nvidiaPackages // {
              stable = masterZen.nvidiaPackages.new_feature;
              new_feature = masterZen.nvidiaPackages.new_feature;
              production = masterZen.nvidiaPackages.new_feature;
              latest = masterZen.nvidiaPackages.new_feature;
            };
          }));

        # opencode v2.2.6 (linha 2.x: /pair, /web, plugins v2, server API v2) —
        # nixpkgs-unstable travada ainda ships 1.18.34; o upgrade 2.x e' escolha
        # explicita. Binário oficial do opencode.ai (FOD com hash — atualize
        # version+hash JUNTos; a URL e' a mesma 'latest', se o upstream apontar
        # p/ 2.2.7 o build FALHA pelo hash — seguro de proposito).
        opencode-v2 = prev.stdenv.mkDerivation {
          pname = "opencode";
          version = "2.2.6";
          src = prev.fetchurl {
            url = "https://opencode.ai/update/api/latest/cli/opencode/opencode-linux-x64.tar.gz";
            hash = "sha256-CLsh1jJs50DZHM5+voimU2kz9uHjA1O5GgawHyXaMGw=";
          };
          dontConfigure = true;
          dontBuild = true;
          # Bun-compiled com payload JS embutido: o strip -S -p do fixupPad
          # CORROMPE o binário (medido 07/11 — o v2.2.6 "virou" Bun cru).
          dontFixup = true;
          unpackPhase = "tar -xzf $src -C $TMPDIR";
          installPhase = ''
            install -Dm755 "$TMPDIR/opencode" "$out/bin/opencode"
          '';
          meta = {
            description = "opencode — the open source AI coding agent (v2 release line)";
            mainProgram = "opencode";
          };
        };
        # kilo (nome legado p/ HM/scripts) aponta p/ a linha 2.x.
        kilo = final.opencode-v2;

        # Mantém o Antigravity original tratando a licença unfree com o import correto
        antigravity-ide = (import nixpkgs-unstable { inherit system; config.allowUnfree = true; }).antigravity-ide;

        # MT5 sob wine 10 (ver comentário no input nixpkgs-wine10). Sombreia
        # os attrs globais: todo consumer do sistema ganha wine 10/winetricks
        # compatíveis sem tocar no resto do 26.05.
        wineWow64Packages = (import nixpkgs-wine10 {inherit system;}).wineWow64Packages;
        winetricks = (import nixpkgs-wine10 {inherit system;}).winetricks;

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
                  # `inherit (nixpkgs) lib` (NÃO `inherit (nixpkgs.lib) lib`):
                  # o inherit antigo pedia o atributo `lib` DENTRO de
                  # nixpkgs.lib — que não existe no nixpkgs 26.05. Bug
                  # latente: só explodia quando um módulo usava `lib`
                  # de verdade (02/11, lib/opencode-limits.nix).
                  inherit (nixpkgs) lib;
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
      inherit (pkg) jarvis kilo antigravity-ide;
    };

    # ── checks: linting fail-closed (checks/default.nix) ────────────
    # Wired em 2026-09-15 (IMP-009): python-lint (ruff fail-closed).
    # Wired em 2026-10-12 (IMP-020): markdown-lint (fail-closed desde o
    # nascimento — exit code autoritativo) + nix-check (eval com fallback
    # de syntax-parse; o "arriscado em sandbox" foi medido: o fallback
    # cobre o caso de rede negada). MD legado vermelho? O gate fica de
    # pé — conserta-se o MD, não o gate.
    checks.${system} = let
      checkLib = import ./checks {
        pkgs = nixpkgs.legacyPackages.${system};
        lib = nixpkgs.lib;
      };
    in {
      python-lint = checkLib.python-lint;
      markdown-lint = checkLib.markdown-lint;
      nix-check = checkLib.nix-check;
      opencode-headroom = checkLib.opencode-headroom;
      opencode-compaction-model = checkLib.opencode-compaction-model;
    };

    # ── lib: fonts, colors, ports (nosso próprio lib/) ──────────────
    # `lib = nixpkgs.lib` (NÃO `inherit (nixpkgs.lib) lib`): o inherit
    # pedia o atributo `lib` DENTRO de nixpkgs.lib — que não existe no
    # nixpkgs 26.05 (só `nixpkgs.lib.lib`, que nunca foi lá). Bug
    # latente: só explodia quando alguém usava `lib` de verdade
    # (02/11, lib/opencode-limits.nix).
    lib.nixos-ai = import ./lib {
      inherit (nixpkgs) lib;
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
          python313Packages.playwright
          python313Packages.prompt-toolkit
          python313Packages.onnxruntime
          # (09/11, sweep-2026-11) torchaudio: o runtime do speaker-ID
          # (wespeakerruntime, usado por scripts/duplex-asrd.py e
          # scripts/spk-enroll.py) importa torchaudio, e sem ele o modulo
          # nao carrega em NENHUM ambiente da box (o venv lab tem
          # torchaudio sem torch; o nixpkgs tem torch sem torchaudio) =>
          # a matricula do dono nunca rodou e o gate de audio nao
          # identifica o falante. onnxruntime sozinho nao basta.
          python313Packages.torchaudio
          # (09/11, sweep-2026-11) pandas + pyarrow: o harness de voz
          # (scripts/duplex-eval.py --trigger-bench) le os clips do Scicom
          # em parquet; sem eles o bench nem roda (e o venv karaok, que
          # tem os dois, tem o numpy quebrado).
          python313Packages.pandas
          python313Packages.pyarrow
          python313Packages.tokenizers
          playwright-driver  
          
          # Documentos/PDF/OCR (vendas, propostas, guias)
          pandoc
          tesseract
          poppler-utils
          # (14/11, sweep-2026-11) pdfplumber + pytesseract: a skill de PDF
          # do Anthropic (importada, drop-in, o mesmo frontmatter da casa) usa
          # os dois nos scripts dela, e sem eles a skill entrava morta: os
          # scripts de extrair formulario e de OCR nao rodavam. Medido: antes
          # desta linha, `import pdfplumber` falhava no python da casa.
          python313Packages.pdfplumber
          python313Packages.pytesseract
          python313Packages.pypdf
          bind.dnsutils # dig/host/nslookup (DNS: registro.br, SPF/DKIM/DMARC)

          # Nomes corrigidos também no devShell para evitar quebra de variáveis
          kilo
          antigravity-ide

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
