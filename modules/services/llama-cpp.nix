{ config, pkgs, lib, ... }:

with lib;

{
  options.services.llama-cpp-server = {
    enable = mkEnableOption "Llama.cpp Server";
    port = mkOption { type = types.port; default = 8080; };
  };

  config = mkIf config.services.llama-cpp-server.enable {
    systemd.services.llama-cpp-server = {
      description = "Llama.cpp High-Performance LLM Server (Auto-Adaptive)";
      after = [ "network-online.target" ];
      wantedBy = [ "multi-user.target" ];

      script = ''
        # Runtime detection: Usa systemd-detect-virt para identificar o ambiente
        # Retorna 0 (sucesso) se estiver em uma VM, não-zero caso contrário (bare-metal)
        if ${pkgs.systemd}/bin/systemd-detect-virt --quiet --vm; then
            echo "[LLAMA-SERVER] Ambiete VM detectado (Hyper-V/KVM/QEMU)."
            MODEL_FILE="qwen2.5-coder-7b-instruct-q4_k_m.gguf"
            MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-Coder-7B-Instruct-GGUF/resolve/main/qwen2.5-coder-7b-instruct-q4_k_m.gguf"
            THREADS=4
            CTX_SIZE=16384
            UBATCH=512
            GPU_LAYERS=0
            EXTRA_FLAGS="-ctk f16 -ctv f16"
        else
            echo "[LLAMA-SERVER] Ambiente Bare Metal detectado."
            MODEL_FILE="qwen2.5-coder-32b-instruct-q4_k_m.gguf"
            MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-Coder-32B-Instruct-GGUF/resolve/main/qwen2.5-coder-32b-instruct-q4_k_m.gguf"
            THREADS=7
            CTX_SIZE=32768
            UBATCH=1024
            GPU_LAYERS=16
            EXTRA_FLAGS="-fa -ctk q8_0 -ctv q4_0"
        fi

        MODEL_DIR="${config.users.users.nixos.home}/models"
        mkdir -p "$MODEL_DIR"

        # Download apenas se não existir
        if [ ! -f "$MODEL_DIR/$MODEL_FILE" ]; then
          ${pkgs.aria2}/bin/aria2c -c -x 4 -s 4 --dir="$MODEL_DIR" --out="$MODEL_FILE" "$MODEL_URL"
        fi

        echo "[LLAMA-SERVER] Iniciando com modelo $MODEL_FILE..."
        exec ${pkgs.llama-cpp}/bin/llama-server \
          -m "$MODEL_DIR/$MODEL_FILE" \
          --host 0.0.0.0 \
          --port ${toString config.services.llama-cpp-server.port} \
          -c "$CTX_SIZE" \
          -t "$THREADS" \
          -ub "$UBATCH" \
          -ngl "$GPU_LAYERS" \
          $EXTRA_FLAGS
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
