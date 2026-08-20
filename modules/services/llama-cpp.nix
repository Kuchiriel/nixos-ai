{ config, pkgs, lib, ... }:

with lib;

let
  profileName = config.services.llama-cpp-server.profile;
  # Perfil de execução — única fonte de verdade: modules/ai/models.nix.
  # Centraliza arquivo do modelo, threads, ctx, ubatch, GPU layers, KV cache,
  # MoE flags e scheduler por cenário (vm = lab CPU, host = bare metal GPU).
  prof = pkgs.aiModels.profiles.${profileName};
  # Instância local de pkgs permitindo pacotes unfree especificamente para o CUDA
  cudaPkgs = import pkgs.path {
    system = pkgs.system;
    config.allowUnfree = true;
  };

  # Compila o llama-cpp com suporte a CUDA forçado
  llamaCppPkg = cudaPkgs.llama-cpp.override { cudaSupport = true; };
in
{
  options.services = {
    llama-cpp-server = {
      enable = mkEnableOption "Llama.cpp Main Server";
      port = mkOption { type = types.port; default = 8080; };
      profile = mkOption {
        type = types.enum [ "vm" "host" ];
        # Água: o perfil segue o switch central services.jarvis.environment
        # (declarado no host). O lab declara "vm"; o host físico "host".
        default = if config.services.jarvis.environment == "host"
                  then "host" else "vm";
        description = ''
          Cenário de execução do servidor de chat. Define modelo, threads,
          contexto, batch, GPU layers, KV-cache, flags MoE e scheduler —
          tudo declarado em modules/ai/models.nix (profiles). Default segue
          services.jarvis.environment; pode ser sobrescrito por host.
        '';
      };
      extraFlags = mkOption { type = types.listOf types.str; default = [ "--jinja" ]; };
    };
    llama-cpp-embeddings = {
      enable = mkEnableOption "Llama.cpp Embeddings Server";
      port = mkOption { type = types.port; default = 8081; };
    };
    llama-cpp-rerank = {
      enable = mkEnableOption "Llama.cpp Rerank Server";
      port = mkOption { type = types.port; default = 8082; };
    };
  };

  config = mkIf (config.services.llama-cpp-server.enable || config.services.llama-cpp-embeddings.enable || config.services.llama-cpp-rerank.enable) {

    # --- 1. SERVIDOR PRINCIPAL (LLM / CHAT) ---
    # Tudo vem do perfil em models.nix — nada de download imperativo nem
    # parâmetros hardcoded aqui. O modelo vive no store (fetchurl, hash
    # verificado): o sistema nasce com o modelo certo para o cenário.
    systemd.services.llama-cpp-server = mkIf config.services.llama-cpp-server.enable {
      description = "Llama.cpp Main Server (${profileName}: ${prof.model})";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      wantedBy = [ "multi-user.target" ];

      script = ''
        exec ${pkgs.llama-cpp}/bin/llama-server \
          -m "${pkgs.aiModels.${prof.model}}" \
          ${optionalString (prof ? mmproj) ''--mmproj "${pkgs.aiModels.${prof.mmproj}}" ''} \
          --host 0.0.0.0 --port ${toString config.services.llama-cpp-server.port} \
          -c ${toString prof.ctxSize} -t ${toString prof.threads} -b ${toString prof.batchSize} -ub ${toString prof.ubatch} -ngl ${toString prof.gpuLayers} \
          ${prof.kvCache} ${prof.moeFlags} ${prof.extraFlags or ""} ${escapeShellArgs config.services.llama-cpp-server.extraFlags}
      '';

      serviceConfig = {
        User = prof.user;
        Restart = "on-failure";
      } // optionalAttrs (prof.scheduler != null) {
        # Host: prioridade de tempo real para o servidor de LLM (kernel).
        # Exige privilégio — por isso o perfil host roda como root.
        CPUSchedulingPolicy = prof.scheduler.policy;
        CPUSchedulingPriority = prof.scheduler.priority;
      };
    };

    # --- 2. SERVIDOR DE EMBEDDINGS (RAG) ---
    # --- 2. SERVIDOR DE EMBEDDINGS (RAG) ---
    # Nomic-embed é leve (<500MB) e BENEFICIA da GPU (indexação instantânea).
    # Com o LLM usando ~2.5GB de VRAM, sobra espaço.
    systemd.services.llama-cpp-embeddings = mkIf config.services.llama-cpp-embeddings.enable {
      description = "Llama.cpp Embeddings Server";
      wantedBy = [ "multi-user.target" ];
      script = ''
        exec ${pkgs.llama-cpp}/bin/llama-server \
          -m "${pkgs.aiModels.embed}" \
          --host 0.0.0.0 --port ${toString config.services.llama-cpp-embeddings.port} \
          --embeddings --pooling mean -c 4096 -t 4 -b 4096 -ub 4096
      '';
      serviceConfig.User = "nixos";
    };

    # --- 3. SERVIDOR DE RERANK (SOTA RAG) ---
    # Reranker é leve, roda bem em CPU.
    systemd.services.llama-cpp-rerank = mkIf config.services.llama-cpp-rerank.enable {
      description = "Llama.cpp Rerank Server";
      wantedBy = [ "multi-user.target" ];
      environment.CUDA_VISIBLE_DEVICES = "";  # CPU-only para preservar VRAM
      script = ''
        exec ${pkgs.llama-cpp}/bin/llama-server \
          -m "${pkgs.aiModels.reranker}" \
          --host 0.0.0.0 --port ${toString config.services.llama-cpp-rerank.port} \
          --rerank -t 4 -c 8192 -b 4096 -ub 4096
      '';
      serviceConfig.User = "nixos";
    };
  };
}
