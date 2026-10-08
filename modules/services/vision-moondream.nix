{ config, lib, pkgs, ... }:
let
  cfg = config.services.vision-moondream;
in
{
  options.services.vision-moondream = {
    enable = lib.mkEnableOption "Moondream2 local vision model (tagging de sprites)";

    # ── Modelo ──────────────────────────────────────────────────────────
    # Pesos + tokenizer da MESMA revision (92d3d73 == tag 2024-08-26).
    # Misturar main com 5d6c926 produz saida corrompida — ver comment em
    # modules/ai/models.nix.
    modelFile = lib.mkOption {
      type = lib.types.path;
      default = "${pkgs.aiModels.vlm-moondream2}";
      description = "Pesos (model.safetensors) pinados em 2024-08-26.";
    };

    tokenizerFile = lib.mkOption {
      type = lib.types.path;
      default = "${pkgs.aiModels.vlm-moondream2-tokenizer}";
      description = "tokenizer.json do MESMO par (offline; sem isto o repo baixa starmie-v1).";
    };

    # O repo traz codigo proprio (trust_remote_code). Fora do store, porque
    # sao arquivos .py versionados no HF, nao um derivation.
    codeDir = lib.mkOption {
      type = lib.types.path;
      default = "/home/nixos/models/moondream2-0826";
      description = "Diretorio local com config.json + *.py do par pinado.";
    };

    # Script do servidor: lido do proprio repo e escrito no store, para a
    # unit nao depender de um .py solto versionado.
    serveScript = lib.mkOption {
      type = lib.types.path;
      default = pkgs.writeText "serve_vision.py" (builtins.readFile
        ./vision-moondream/serve_vision.py);
      defaultText = "pkgs.writeText \"serve_vision.py\" <repo>";
      description = "Servidor HTTP de tagging (embedado no store).";
    };

    port = lib.mkOption {
      type = lib.types.port;
      default = 8098;
      description = "Porta da API. 8094 e MyAAC — NAO usar (ver MODELS-VISION.md).";
    };

    user = lib.mkOption {
      type = lib.types.str;
      default = "nixos";
    };

    # ── Runtime ─────────────────────────────────────────────────────────
    # python3 com torch CUDA vem do pip: o torch do nixpkgs e CPU-only
    # (medido: torch.cuda.is_available() == False). einops/torchvision sao
    # exigidos por vision_encoder.py. transformers 4.45.2 — o 5.x quebra a
    # geracao deste trust_remote_code.
    pythonEnv = lib.mkOption {
      type = lib.types.package;
      default = pkgs.python3.withPackages (ps: with ps; [
        transformers
        torch
        torchvision
        einops
        pillow
        accelerate
      ]);
      defaultText = "python3.withPackages [transformers torch torchvision einops pillow accelerate]";
      description = "Ambiente Python do servico. Precisa de torch COM CUDA.";
    };

    extraArgs = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [ ];
    };

    # ── Guarda de VRAM ──────────────────────────────────────────────────
    # VRAM 6 GB = 1 LLM por vez (AGENTS.md). `down` para o servidor de
    # texto antes de a visao subir; `up` devolve. Em binarios, sem quoting
    # inline na unit.
    vramGuardCshIn = lib.mkOption {
      type = lib.types.package;
      default = pkgs.writeShellScriptBin "vram-guard-cshin" ''
        case "''${1:-}" in
          down)
            # best-effort: se ja estiver parado, nao e erro
            systemctl stop llama-cpp-upstream.service || true
            ;;
          up)
            systemctl start llama-cpp-upstream.service || true
            ;;
          *)
            echo "uso: vram-guard-cshin {down|up}" >&2
            exit 2
            ;;
        esac
      '';
      defaultText = "pkgs.writeShellScriptBin \"vram-guard-cshin\"";
      description = "Para/devolve o llama-cpp-upstream conforme a VRAM.";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.vision-moondream = {
      description = "Moondream2 — modelo de visão local (tagging de sprites 32x32)";

      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      # Não sobe no boot: VRAM 6 GB = 1 LLM por vez (AGENTS.md). Sobe sob
      # demanda com `systemctl start vision-moondream`.
      wantedBy = [ ];

      serviceConfig = {
        Type = "exec";
        User = cfg.user;
        Group = cfg.user;
        WorkingDirectory = cfg.codeDir;

        Environment = [
          # Offline puro: sem isto o repo tenta a rede no __init__
          # (401 com HF_TOKEN expirado, ou baixa moondream/starmie-v1).
          "HF_HUB_OFFLINE=1"
          "TRANSFORMERS_VERBOSITY=error"
          "TOKENIZERS_PARALLELISM=false"
          # Fragmentacao: encode_image com crops estoura sem isto.
          "PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True"
          # CUDA visivel para o usuario do servico.
          "LD_LIBRARY_PATH=/run/opengl-driver/lib"
        ];

        # 4120 MB medidos em bfloat16. Limite com folga para os crops.
        MemoryMax = "8G";

        # ── VRAM: um LLM por vez ──
        # 4120 MB (moondream) + 3232 MB (jarvis-fast) estoura os 6 GB.
        # O Conflict + o vram-guard.cshIN travam junto: subir a visao baixa
        # o jarvis-fast, e derrubar a visao devolve o jarvis-fast.
        Conflicts = [ "llama-cpp-upstream.service" ];
        ExecStartPre = "${cfg.vramGuardCshIn}/bin/vram-guard-cshin down";
        ExecStart = "${cfg.pythonEnv}/bin/python ${cfg.serveScript} " +
          (lib.concatStringsSep " " (
            [ "--model-dir" cfg.codeDir "--port" (toString cfg.port) ]
            ++ cfg.extraArgs
          ));

        Restart = "on-failure";
        RestartSec = "10";
        TimeoutStopSec = "30";
        KillSignal = "SIGTERM";

        NoNewPrivileges = true;
        PrivateTmp = true;
        ProtectSystem = "strict";
        # O codigo do modelo e lido de ~/models; o cache de modulos da
        # transformers e escrito em ~/.cache.
        ReadWritePaths = [
          "/home/${cfg.user}/.cache"
          "/home/${cfg.user}/models"
        ];
        ReadOnlyPaths = [ cfg.codeDir ];

        # Devolve o jarvis-fast quando a visao cai.
        ExecStopPost = "${cfg.vramGuardCshIn}/bin/vram-guard-cshin up";
      };
    };

    # Porta fica documentada para o proxy/panel; a visao NAO entra no
    # roteamento de texto (models.nix `routing`) porque e VLM e nao LLM.
    environment.etc."jarvis/vision-moondream.json".text = lib.format ''
      {
        "service": "vision-moondream",
        "port": %d,
        "model": "vikhyatk/moondream2",
        "revision": "92d3d73b6fd61ab84d9fe093a9c7fd8c04bf2c0d",
        "tag": "2024-08-26",
        "vram_mb": 4120,
        "dtype": "bfloat16",
        "transformers": "4.45.2",
        "prompt_policy": "curto e POSITIVO; negative constraints colapsam o modelo",
        "precision": {
          "material_cor": "boa (~60%)",
          "detalhe_de_forma": "ruim (0%)",
          "papel": "complementa a medicao de pixel; nao autoritativo"
        },
        "docs": "canary-official/dataset/maps/MODELS-VISION.md"
      }
    '' cfg.port;
  };
}