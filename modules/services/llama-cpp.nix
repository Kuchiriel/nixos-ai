{ config, pkgs, lib, ... }:

with lib;

let
  cfg = config.services.llama-cpp-server;

  # Detecta se está rodando em VM ou Bare Metal
  isVM = config.mySystem.isVM or false;

  # Parâmetros adaptativos de Hardware (VM vs Host)
  gpuLayers = if isVM then 0 else 16;
  threadsCount = if isVM then 4 else 7;
  ubatchSize = if isVM then 512 else 1024;

  # Otimizações de KV Cache e FlashAttention dependentes do hardware
  extraLlamaFlags = if isVM then ''
    -ctk f16 \
    -ctv f16
  '' else ''
    -fa \
    -ctk q8_0 \
    -ctv q4_0
  '';

  # Definição do modelo Qwen2.5-Coder-32B-Instruct
  modelDir = "/home/nixos/models";
  modelFileName = "qwen2.5-coder-32b-instruct-q4_k_m.gguf";
  modelFile = "${modelDir}/${modelFileName}";
  modelUrl = "https://huggingface.co/Qwen/Qwen2.5-Coder-32B-Instruct-GGUF/resolve/main/qwen2.5-coder-32b-instruct-q4_k_m.gguf";
in
{
  options.services.llama-cpp-server = {
    enable = mkEnableOption "Llama.cpp Server";

    modelPath = mkOption {
      type = types.str;
      default = modelFile;
      description = "Caminho completo para o arquivo de modelo GGUF.";
    };

    port = mkOption {
      type = types.port;
      default = 8080;
      description = "Porta HTTP do servidor llama.cpp.";
    };

    threads = mkOption {
      type = types.int;
      default = threadsCount;
      description = "Quantidade de threads de CPU.";
    };

    contextSize = mkOption {
      type = types.int;
      default = 32768;
      description = "Tamanho do contexto (tokens).";
    };

    ubatch = mkOption {
      type = types.int;
      default = ubatchSize;
      description = "Physical batch size para processamento do prompt.";
    };
  };

  config = mkIf cfg.enable {
    systemd.services.llama-cpp-server = {
      description = "Llama.cpp High-Performance LLM Server";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      wantedBy = [ "multi-user.target" ];

      script = ''
        mkdir -p ${modelDir}

        # Download/Resumo via aria2c
        if [ ! -f "${cfg.modelPath}" ] || [ -f "${cfg.modelPath}.aria2" ]; then
          echo "[LLAMA-SERVER] Baixando/Retomando Qwen2.5-Coder-32B..."
          ${pkgs.aria2}/bin/aria2c \
            -c \
            -x 4 \
            -s 4 \
            --summary-interval=5 \
            --dir="${modelDir}" \
            --out="${modelFileName}" \
            "${modelUrl}" || {
            echo "[LLAMA-SERVER] Erro durante o download do modelo via aria2c."
            exit 1;
          }
        fi

        echo "[LLAMA-SERVER] Iniciando llama-server..."
        exec ${pkgs.llama-cpp}/bin/llama-server \
          -m "${cfg.modelPath}" \
          --host 0.0.0.0 \
          --port ${toString cfg.port} \
          -c ${toString cfg.contextSize} \
          -t ${toString cfg.threads} \
          -ub ${toString cfg.ubatch} \
          -ngl ${toString gpuLayers} \
          ${extraLlamaFlags}
      '';

      serviceConfig = {
        User = "nixos";
        Group = "users";
        Restart = "on-failure";
        RestartSec = "10s";
      };
    };
  };
}
