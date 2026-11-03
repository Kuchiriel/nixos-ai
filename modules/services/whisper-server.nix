# ═══ Whisper Server (ASR da voz duplex) ═══
# O duplex (scripts/duplex-voice.py) transcreve via whisper.cpp :8097.
# (03/11) CAUSA-RAIZ do "falo com ele e nada": o whisper-server morria no
# boot com CUDA OOM (ggml_gallocr_reserve_n_impl: failed to allocate CUDA0
# buffer of size 97531392) — sem ele o ASR fica MURO e o duplex responde
# nada. Medido na RTX 4050 (6141 MiB totais):
#   whisper turbo-q5_0 GPU = 573 MB modelo + ~230 MB compute + contexto CUDA
#   → precisa ~900 MiB; o 4B-MTP segura 4582 MiB e o embeddings 446 MiB.
# Com os três de pé sobra < 800 MiB → OOM. ORDEM importa: o whisper SOBE
# ANTES do embeddings (que é pequeno e roda em CPU se faltar VRAM).
# Latência medida (03/11): GPU 198-341 ms/segmento · CPU 10,4 s (inviável).
{config, lib, pkgs, ...}:

let
  cfg = config.services.whisper-server;
  # (03/11) O pkgs.whisper-cpp do nixpkgs sai SÓ CPU (libggml-cpu-*, sem
  # libggml-cuda.so) — o build CUDA que roda hoje (198-341 ms/segmento) é
  # o do repo ~/projects/whisper.cpp (build/ com GGML_CUDA=1), o MESMO
  # binário que scripts/duplex-voice-run.sh já usa. Referência por caminho
  # (o build dir é gitignored); alternativa = empacotar whisper.cpp com
  # CUDA no flake (build pesado de nvcc, ~30 min).
  whisperServer = "/home/nixos/projects/whisper.cpp/build/bin/whisper-server";
  modelPath = "/home/nixos/models/whisper/ggml-large-v3-turbo-q5_0.bin";

  # Espera o whisper ficar HEALTHY (modelo carregado na VRAM) antes de o
  # embeddings subir. Script = binário: o systemd não interpreta shell.
  waitForWhisper = pkgs.writeShellScript "wait-for-whisper.sh" ''
    for _i in $(seq 1 90); do
      if ${pkgs.curl}/bin/curl -sf --max-time 2 http://127.0.0.1:${toString cfg.port}/health >/dev/null 2>&1; then
        exit 0
      fi
      sleep 1
    done
    echo "whisper-server não ficou healthy em 90s; subindo embeddings assim mesmo" >&2
    exit 0
  '';
in {
  options.services.whisper-server = {
    enable = lib.mkEnableOption "Whisper.cpp Server (ASR para a voz duplex)";

    port = lib.mkOption {
      type = lib.types.port;
      default = 8097;
      description = "Porta HTTP do whisper-server (inference endpoint).";
    };

    binary = lib.mkOption {
      type = lib.types.str;
      default = whisperServer;
      description = ''
        Caminho do binário whisper-server COM CUDA. O do nixpkgs é
        CPU-only (10,4 s/segmento — inviável p/ tempo real).
      '';
    };

    model = lib.mkOption {
      type = lib.types.str;
      default = modelPath;
      description = ''
        Caminho do modelo GGML. turbo-q5_0 é o default de produção
        (PT-BR impecável, 234 ms/seg medido, 900 MiB de residência).
      '';
    };

    language = lib.mkOption {
      type = lib.types.str;
      default = "pt";
      description = ''
        Idioma fixo. 'pt' é o default (auto-detect ALUCINA traduções EN
        na voz piper/PT: 'que dia é hoje' → 'I wish that day is today').
        'auto' = multilingue (dono testando EN/JA/ZH).
      '';
    };

    extraArgs = lib.mkOption {
      type = lib.types.listOf lib.types.str;
      default = [];
      description = "Argumentos extras passados ao whisper-server.";
    };
  };

  config = lib.mkIf cfg.enable {
    systemd.services.whisper-server = {
      description = "Whisper.cpp Server — ASR da voz duplex";
      after = ["network-online.target"];
      wants = ["network-online.target"];
      partOf = ["jarvis.target"];
      wantedBy = ["jarvis.target"];

      # (03/11) O whisper PRECISA subir antes do embeddings: ambos disputam
      # a VRAM com o 4B-MTP (4582 MiB). O embeddings é pequeno e tolerante
      # a esperar; o whisper sem VRAM MORRE (CUDA OOM) e leva o ASR junto.
      before = ["llama-cpp-embeddings.service"];

      script = ''
        exec ${cfg.binary} \
          -m "${cfg.model}" \
          -l "${cfg.language}" \
          --port ${toString cfg.port} --host 127.0.0.1 \
          ${lib.concatStringsSep " " cfg.extraArgs}
      '';

      serviceConfig = {
        User = "nixos";
        Restart = "on-failure";
        RestartSec = "5";
        # O modelo fica em /home/nixos/models (fora do store) — ProtectSystem
        # strict deixa /home gravável só se explicitado.
        ProtectSystem = "strict";
        ReadWritePaths = ["/home/nixos/models" "/tmp/opencode"];
        PrivateTmp = false;   # o log do duplex vive em /tmp/opencode
        NoNewPrivileges = true;
        RestrictSUIDSGID = true;
        # CUDA: precisa de /dev/nvidia* e do driver
        DeviceAllow = ["/dev/nvidiactl" "/dev/nvidia0" "/dev/nvidia-uvm"];
        MemoryMax = "4G";
        TasksMax = 64;
      };
    };

    # (03/11) `before=` só ordena o SPAWN do processo, não o carregamento
    # do modelo: sem esta espera o embeddings sobe, toma a VRAM (446 MiB)
    # enquanto o whisper ainda está carregando (900 MiB) e o whisper MORRE
    # de CUDA OOM — o ASR do duplex fica mudo. Aqui o embeddings espera o
    # whisper ficar HEALTHY (modelo carregado) antes de subir.
    #
    # (03/11 18:38) O ExecStartPre PRECISA ser um binário: o systemd não
    # roda shell — um script multi-linha vira 203/EXEC e a unit não sobe.
    systemd.services.llama-cpp-embeddings = {
      after = lib.mkAfter ["whisper-server.service"];
      serviceConfig.ExecStartPre = lib.mkAfter "${waitForWhisper}";
    };
  };
}

