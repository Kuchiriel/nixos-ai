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
            # -fa habilitado tambem aqui: flash-attention nao piora tool
            # calling e mantem o comportamento consistente entre os dois
            # perfis (VM x bare-metal), o que facilita debugar diferencas
            # de comportamento do parser Hermes 2 Pro entre 7B e 32B.
            EXTRA_FLAGS="-fa -ctk f16 -ctv f16"
        else
            MODEL_FILE="qwen2.5-coder-32b-instruct-q4_k_m.gguf"
            MODEL_URL="https://huggingface.co/Qwen/Qwen2.5-Coder-32B-Instruct-GGUF/resolve/main/qwen2.5-coder-32b-instruct-q4_k_m.gguf"
            THREADS=7
            CTX_SIZE=32768
            UBATCH=1024
            GPU_LAYERS=16
            # ATENCAO: a doc oficial do llama.cpp alerta que quantizacoes
            # extremas de KV (ex: -ctv q4_0) degradam substancialmente a
            # confiabilidade de tool calling. Subimos o V-cache de q4_0
            # para q8_0 -- custa mais VRAM/RAM, mas e exatamente o
            # parametro mais provavel de estar contribuindo pro Qwen
            # 32B "vazar" tool_call como texto em vez de JSON estruturado.
            EXTRA_FLAGS="-fa -ctk q8_0 -ctv q8_0"
        fi

        # Caminho absoluto garantido para o usuário nixos
        MODEL_DIR="/home/nixos/models"
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

      # Diagnostico automatico: registra no journal qual chat format
      # (Hermes 2 Pro / Generic / etc) o llama.cpp detectou pro modelo
      # que acabou de subir. Se aparecer "Generic" em vez de "Hermes 2
      # Pro" para um Qwen2.5-Coder, o template jinja embutido no GGUF
      # nao esta sendo reconhecido -- sinal para usar --chat-template-file.
      postStart = ''
        for i in $(seq 1 30); do
          if ${pkgs.curl}/bin/curl -sf "http://127.0.0.1:${toString config.services.llama-cpp-server.port}/health" >/dev/null 2>&1; then
            break
          fi
          sleep 2
        done
        FORMAT=$(${pkgs.curl}/bin/curl -sf "http://127.0.0.1:${toString config.services.llama-cpp-server.port}/props" \
          | ${pkgs.jq}/bin/jq -r '.chat_template_tool_use // .chat_template // "unknown"' 2>/dev/null | head -c 60)
        echo "llama-cpp-server: props chat template prefix = $FORMAT" | ${pkgs.systemd}/bin/systemd-cat -t llama-cpp-diagnostic
      '';

      serviceConfig = {
        User = "nixos";
        Group = "users";
        WorkingDirectory = "/home/nixos";
        Environment = "HOME=/home/nixos";
        Restart = "on-failure";
        RestartSec = "10s";
      };
    };
  };
}

