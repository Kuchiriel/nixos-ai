{ config, pkgs, lib, ... }:

with lib;

{
  options.services.llama-cpp-server = {
    enable = mkEnableOption "Llama.cpp Server";
    port = mkOption { type = types.port; default = 8080; };
    extraFlags = mkOption { 
      type = types.listOf types.str; 
      default = [ "--jinja" ]; 
      description = "Flags adicionais para o llama-server.";
    };
  };

  config = mkIf config.services.llama-cpp-server.enable {
    systemd.services.llama-cpp-server = {
      description = "Llama.cpp High-Performance LLM Server (Auto-Adaptive)";
      after = [ "network-online.target" ];
      wants = [ "network-online.target" ];
      wantedBy = [ "multi-user.target" ];

      script = ''
        if ${pkgs.systemd}/bin/systemd-detect-virt --quiet --vm; then
            MODEL_FILE="qwen2.5-coder-7b-instruct-q4_k_m.gguf"
            MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf"
            THREADS=4
            CTX_SIZE=16384
            UBATCH=512
            GPU_LAYERS=0
            EXTRA_FLAGS="-ctk f16 -ctv f16"
        else
            MODEL_FILE="qwen2.5-coder-32b-instruct-q4_k_m.gguf"
            MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-Coder-32B-Instruct-GGUF/resolve/main/qwen2.5-coder-32b-instruct-q4_k_m.gguf"
            THREADS=7
            CTX_SIZE=32768
            UBATCH=1024
            GPU_LAYERS=16
            EXTRA_FLAGS="-fa -ctk q8_0 -ctv q4_0"
        fi

        MODEL_DIR="$HOME/models"
        mkdir -p "$MODEL_DIR"

        if [ ! -f "$MODEL_DIR/$MODEL_FILE" ]; then
          ${pkgs.aria2}/bin/aria2c -c -x 4 -s 4 --dir="$MODEL_DIR" --out="$MODEL_FILE" "$MODEL_URL"
        fi

        exec ${pkgs.llama-cpp}/bin/llama-server \
          -m "$MODEL_DIR/$MODEL_FILE" \
          --host 0.0.0.0 \
          --port ${toString config.services.llama-cpp-server.port} \
          -c "$CTX_SIZE" \
          -t "$THREADS" \
          -ub "$UBATCH" \
          -ngl "$GPU_LAYERS" \
          $EXTRA_FLAGS \
          ${escapeShellArgs config.services.llama-cpp-server.extraFlags}
      '';

      serviceConfig = {
        Restart = "on-failure";
        RestartSec = "10s";
      };
    };
  };
}
