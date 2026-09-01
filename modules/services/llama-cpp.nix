{
  config,
  pkgs,
  lib,
  ...
}:
with lib; let
  profileName = config.services.llama-cpp-server.profile;
  # Perfil de execução — única fonte de verdade: modules/ai/models.nix.
  prof = pkgs.aiModels.profiles.${profileName};

  # Compila o llama-cpp com suporte a CUDA forçado.
  # Usa o `pkgs` já recebido pelo módulo (herda allowUnfree + overlay
  # definidos centralmente no flake.nix) — NÃO reimportar pkgs.path aqui.
  llamaCppPkg = pkgs.llama-cpp.override {cudaSupport = true;};

  # Se o profile tem wrapper (ex: host-ehs), usar o script wrapper
  # que aponta pro binario wackmall compilado localmente.
  # O wrapper fica em modules/ai/ (../ai/ relativo a modules/services/).
  llamaBin = if prof ? wrapper && prof.wrapper != null
    then "${../ai}/${prof.wrapper}.sh"
    else "${llamaCppPkg}/bin/llama-server";
in {
  options.services = {
    llama-cpp-server = {
      enable = mkEnableOption "Llama.cpp Main Server";
      port = mkOption {
        type = types.port;
        default = 8080;
      };
      profile = mkOption {
        type = types.enum [
          "vm" "host" "host-ncmoe35" "host-ehs" "host-ehs-optimized"
          "roo-dev" "chat" "jarvis" "benchmark" "fast"
        ];
        default =
          if config.services.jarvis.environment == "host"
          then "host"
          else "vm";
        description = ''
          Cenário de execução do servidor de chat. Define modelo, threads,
          contexto, batch, GPU layers, KV-cache, flags MoE e scheduler —
          tudo declarado em modules/ai/models.nix (profiles). Default segue
          services.jarvis.environment; pode ser sobrescrito por host.

          Perfis disponíveis:
          - vm: Lab/VM com CPU only (Qwen3-4B)
          - host: Servidor principal (Qwen3.6-35B-A3B)
          - host-ncmoe35: Variante mais rápida com mais experts na GPU
          - host-ehs: Expert Hot Store (fork wackmall)
          - host-ehs-optimized: Combina EHS com otimizações
          - roo-dev: Contexto grande para coding (32K, parallel=2)
          - chat: Throughput máximo para conversas (16K, parallel=1)
          - jarvis: Baixa latência para voz (8K, parallel=1)
          - benchmark: Settings reprodutíveis para medições
          - fast: Agent loop / baixa latência (8K, parallel=1, experts na GPU)
        '';
      };
      extraFlags = mkOption {
        type = types.listOf types.str;
        default = ["--jinja"];
      };
      bindAddress = mkOption {
        type = types.str;
        default = "127.0.0.1";
        description = ''
          Address to bind the llama-server HTTP endpoint.
          Default: 127.0.0.1 (loopback only — local inference, not exposed).
          Set to "0.0.0.0" only when remote access is explicitly needed.
        '';
      };
    };
    llama-cpp-embeddings = {
      enable = mkEnableOption "Llama.cpp Embeddings Server";
      port = mkOption {
        type = types.port;
        default = 8081;
      };
    };
    llama-cpp-rerank = {
      enable = mkEnableOption "Llama.cpp Rerank Server";
      port = mkOption {
        type = types.port;
        default = 8082;
      };
    };
  };

  config = mkIf (
    config.services.jarvis.enable
    && (config.services.llama-cpp-server.enable || config.services.llama-cpp-embeddings.enable || config.services.llama-cpp-rerank.enable)
  ) {
    systemd.services = {
      llama-cpp-server = mkIf config.services.llama-cpp-server.enable {
        description = "Llama.cpp Main Server (${profileName}: ${prof.model})";
        after = ["network-online.target" "qdrant.service"];
        wants = ["network-online.target"];
        # PartOf jarvis.target: para junto com o ecossistema
        partOf = ["jarvis.target"];
        wantedBy = ["jarvis.target" "multi-user.target"];

        script = ''
          exec ${llamaBin} \
            -m "${pkgs.aiModels.${prof.model}}" \
            ${optionalString (prof ? mmproj && prof.mmproj != null) ''--mmproj "${pkgs.aiModels.${prof.mmproj}}" ''} \
            --host ${config.services.llama-cpp-server.bindAddress} --port ${toString config.services.llama-cpp-server.port} \
            -c ${toString prof.ctxSize} -t ${toString prof.threads} -b ${toString prof.batchSize} -ub ${toString prof.ubatch} ${optionalString (prof.gpuLayers > 0) "-ngl ${toString prof.gpuLayers}"} \
            ${prof.kvCache} ${prof.moeFlags} \
            ${optionalString (prof ? extraArgs) (escapeShellArgs prof.extraArgs)} \
            ${prof.extraFlags or ""} ${escapeShellArgs config.services.llama-cpp-server.extraFlags}
        '';

        serviceConfig =
          {
            User = prof.user;
            Restart = "on-failure";
          }
          // optionalAttrs (prof.scheduler != null) {
            CPUSchedulingPolicy = prof.scheduler.policy;
            CPUSchedulingPriority = prof.scheduler.priority;
          };
      };

      llama-cpp-embeddings = mkIf config.services.llama-cpp-embeddings.enable {
        description = "Llama.cpp Embeddings Server";
        after = ["network-online.target" "qdrant.service"];
        wants = ["network-online.target"];
        partOf = ["jarvis.target"];
        wantedBy = ["jarvis.target"];
        script = ''
          exec ${pkgs.llama-cpp}/bin/llama-server \
            -m "${pkgs.aiModels.embed}" \
            --host 127.0.0.1 --port ${toString config.services.llama-cpp-embeddings.port} \
            --embeddings --pooling mean -c 4096 -t 2 -b 2048 -ub 1024
        '';
        serviceConfig = {
          User = "nixos";
          # ── Sandboxing ──
          ProtectSystem = "strict";       # /usr e /boot read-only
          PrivateTmp = true;                # /tmp privado
          NoNewPrivileges = true;           # Sem escalada de privilégio
          RestrictSUIDSGID = true;          # Sem arquivos SUID/SGID
          # ── Resource limits ──
          MemoryMax = "512M";               # Max 512MB RAM
          TasksMax = 32;                    # Max 32 tasks
        };
      };

      llama-cpp-rerank = mkIf config.services.llama-cpp-rerank.enable {
        description = "Llama.cpp Rerank Server";
        after = ["network-online.target"];
        wants = ["network-online.target"];
        partOf = ["jarvis.target"];
        wantedBy = ["jarvis.target"];
        environment.CUDA_VISIBLE_DEVICES = "";
        script = ''
          exec ${pkgs.llama-cpp}/bin/llama-server \
            -m "${pkgs.aiModels.reranker}" \
            --host 127.0.0.1 --port ${toString config.services.llama-cpp-rerank.port} \
            --rerank -t 2 -c 8192 -b 512 -ub 512
        '';
        serviceConfig = {
          User = "nixos";
          # ── Sandboxing ──
          ProtectSystem = "strict";       # /usr e /boot read-only
          PrivateTmp = true;                # /tmp privado
          NoNewPrivileges = true;           # Sem escalada de privilégio
          RestrictSUIDSGID = true;          # Sem arquivos SUID/SGID
          # ── Resource limits ──
          MemoryMax = "1G";                 # Max 1GB RAM (model is 438MB)
          TasksMax = 64;                    # Max 64 tasks (threads)
        };
      };
    };
  };
}
