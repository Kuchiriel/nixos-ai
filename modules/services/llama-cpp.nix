{ config, pkgs, lib, ... }:

with lib;

let
  # Detecção automática nativa pelo NixOS (abrangendo Hyper-V, KVM, QEMU, VirtualBox, VMware)
  isVM = 
    let
      vendorPath = /sys/class/dmi/id/sys_vendor;
      productPath = /sys/class/dmi/id/product_name;
      readSafe = path: if builtins.pathExists path then builtins.readFile path else "";
      vendor = lib.toLower (readSafe vendorPath);
      product = lib.toLower (readSafe productPath);
    in
      lib.hasInfix "qemu" vendor || 
      lib.hasInfix "kvm" vendor || 
      lib.hasInfix "virtualbox" vendor || 
      lib.hasInfix "vmware" vendor ||
      lib.hasInfix "microsoft" vendor ||
      lib.hasInfix "hyper-v" vendor ||
      lib.hasInfix "qemu" product ||
      lib.hasInfix "kvm" product ||
      lib.hasInfix "virtual machine" product;

  # Parâmetros adaptativos baseados na detecção automática
  gpuLayers = if isVM then 0 else 16;
  threadsCount = if isVM then 4 else 7;
  ubatchSize = if isVM then 512 else 1024;
  defaultContextSize = if isVM then 16384 else 32768;

  # Mapeamento do diretório e modelos por ambiente detectado
  modelDir = "${config.users.users.nixos.home}/models";

  modelFileName = if isVM
    then "qwen2.5-coder-7b-instruct-q4_k_m.gguf"
    else "qwen2.5-coder-32b-instruct-q4_k_m.gguf";

  modelFile = "${modelDir}/${modelFileName}";

  modelUrl = if isVM
    then "https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf"
    else "https://huggingface.co/Qwen/Qwen2.5-Coder-32B-Instruct-GGUF/resolve/main/qwen2.5-coder-32b-instruct-q4_k_m.gguf";

  # Flags otimizadas em formato de string multilinha bash
  extraLlamaFlags = if isVM then ''
    -ctk f16 \
    -ctv f16
  '' else ''
    -fa \
    -ctk q8_0 \
    -ctv q4_0
  '';
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
      default = defaultContextSize;
      description = "Tamanho do contexto (tokens).";
    };

    ubatch = mkOption {
      type = types.int;
      default = ubatchSize;
      description = "Physical batch size para processamento do prompt.";
    };
  };

  config = mkIf config.services.llama-cpp-server.enable {
    systemd.services.llama-cpp-server = {
      description = "Llama.cpp High-Performance LLM Server";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      wantedBy = [ "multi-user.target" ];

      script = ''
        mkdir -p ${modelDir}

        if [ ! -f "${config.services.llama-cpp-server.modelPath}" ] || [ -f "${config.services.llama-cpp-server.modelPath}.aria2" ]; then
          echo "[LLAMA-SERVER] Baixando/Retomando modelo (${modelFileName})..."
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

        echo "[LLAMA-SERVER] Iniciando llama-server com modelo ${modelFileName}..."
        exec ${pkgs.llama-cpp}/bin/llama-server \
          -m "${config.services.llama-cpp-server.modelPath}" \
          --host 0.0.0.0 \
          --port ${toString config.services.llama-cpp-server.port} \
          -c ${toString config.services.llama-cpp-server.contextSize} \
          -t ${toString config.services.llama-cpp-server.threads} \
          -ub ${toString config.services.llama-cpp-server.ubatch} \
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
