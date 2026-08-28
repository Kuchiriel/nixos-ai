{
  fetchurl,
}:
# Modelos de IA baixados declarativamente via fetchurl.
#
# ESTE ARQUIVO É A ÚNICA FONTE DE VERDADE DA INTELIGÊNCIA DO SISTEMA:
#   1. os ARQUIVOS de modelo (fetchurl, hash verificado) e
#   2. os PERFIS de execução (`profiles`) — o módulo services/llama-cpp.nix
#      apenas consome `pkgs.aiModels.profiles.<cenário>`.
#
# Cenários:
#   - vm  (Lab, CPU): Qwen3-4B (2.5GB) — SLM com tool calling nativo
#   - host (Bare metal — Acer Nitro V15, RTX 4050 6GB / 32GB RAM):
#     Qwen3.6-35B-A3B (MoE 35B total / 3B ativos + vision encoder)
#
let
  mkModel = {
    url,
    sha256,
  }:
    fetchurl {inherit url sha256;};
in {
  # =========================================================================
  # 1. ARQUIVOS DE MODELO
  # =========================================================================

  # --- LLM — Lab (VM, CPU) ---
  # Qwen3-4B: tool calling nativo via chat template (--jinja), 2.5GB.
  llm-vm = mkModel {
    url = "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf";
    sha256 = "sha256-dIX+bxGvKUM7xRyrWACVIfIFhA9bSuOjL6f5LoU0/fU=";
  };

  # --- LLM — Host (bare metal) ---
  # Qwen3.6-35B-A3B: MoE (35B total, 3B ativos por token) com vision encoder
  llm-host = mkModel {
    url = "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf";
    sha256 = "sha256-rA4sEYngVfqjbv82FYDnnFvW+Odr/7TOVH8WfVPjGmE=";
  };

  # --- Projetor de visão (multimodal) do Qwen3.6-35B-A3B ---
  llm-host-mmproj = mkModel {
    url = "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/mmproj-BF16.gguf";
    sha256 = "sha256-NW36oxETdqT3Fl4y6HSXEzeNFwCzfPUuDFDZ8jMiM00=";
  };

  # --- Embeddings (RAG) — nomic-embed-text-v2-moe Q8_0 (512MB) ---
  embed = mkModel {
    url = "https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe-GGUF/resolve/main/nomic-embed-text-v2-moe.Q8_0.gguf";
    sha256 = "sha256-Buen5ZSiaYVSPBg4OrpKrTn+bhTwj/xqtbVU4czcPP8=";
  };

  # --- bge-reranker-v2-m3 (reranker cross-encoder, multi-língua) ---
  # GGUF Q4_K_M (438MB) para o endpoint /rerank do llama-server.
  reranker = fetchurl {
    url = "https://huggingface.co/gpustack/bge-reranker-v2-m3-GGUF/resolve/main/bge-reranker-v2-m3-Q4_K_M.gguf";
    sha256 = "0wrnic7hzrcnvr2fbdf0yl9sx9i7fk73jhy6dsv4lns5xm2a51p1";
  };

  # --- openwakeword (wakeword) ---
  openwakeword = {
    hey_jarvis = fetchurl {
      url = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/hey_jarvis_v0.1.onnx";
      sha256 = "1jyjw0p72wsa8dcgphqvhrqfw8w15r37wbj7d8pi6nq7c3z3r8cl";
    };
    embedding = fetchurl {
      url = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/embedding_model.onnx";
      sha256 = "07sw0z9ppzvc0lfz6nbb66km0cjl01gbqjg19qfms28x1hln9lbh";
    };
    melspectrogram = fetchurl {
      url = "https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/melspectrogram.onnx";
      sha256 = "0vqpxdjzlyglv775r2gj6v2bllzzc0rv3768l9lm71vvic7hwaxs";
    };
  };

  # --- Kokoro-82M (TTS, formato torch) ---
  kokoro = {
    config = fetchurl {
      url = "https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/config.json";
      sha256 = "0zy18fdnn68mpqis8jdd1mx9s81y8ihf3z847pq2n1rv83i03fss";
    };
    model = fetchurl {
      url = "https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/kokoro-v1_0.pth";
      sha256 = "1r6iibqm6b0zxr3nxzl9zj1h8vi1vkdqiz1fvgrzan0sil8vlva9";
    };
    voice = fetchurl {
      url = "https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/voices/af_heart.pt";
      sha256 = "1zxl5h82lf0jggbd0fi56dvsyq2vyyc1vlcwhkyrpcgsiydp1d8a";
    };
  };

  # --- faster-whisper (STT) — small CTranslate2 (multi-língua, PT-BR) ---
  whisper-small = fetchurl {
    url = "https://huggingface.co/Systran/faster-whisper-small/resolve/main/model.bin";
    sha256 = "0wfnf10y3g779xxsjkdji7xij92xwxrw5r13c20p523da0hmjc1y";
  };

  # =========================================================================
  # 2. PERFIS DE EXECUÇÃO (llama-cpp) — ÚNICA FONTE DE VERDADE
  # =========================================================================
  profiles = {
    vm = {
      model = "llm-vm";
      threads = 4;
      ctxSize = 131072;
      batchSize = 512;
      ubatch = 512;
      gpuLayers = 0;
      kvCache = "-fa on -ctk f16 -ctv f16";
      moeFlags = "";
      user = "nixos";
      scheduler = null;
    };

    host = {
      model = "llm-host";
      mmproj = "llm-host-mmproj";
      threads = 12;
      ctxSize = 196608;
      batchSize = 1024;
      ubatch = 1024;
      gpuLayers = 999; # Tudo na GPU; --cpu-moe move só routed experts pra CPU
      kvCache = "-fa on -ctk q4_0 -ctv q4_0";
      # --cpu-moe: attention + dense FFN ficam na GPU, só routed experts na CPU
      # ANTES: --n-cpu-moe 99 deixava GPU com 0% utilização
      moeFlags = "--cpu-moe --split-mode layer --poll 50 --poll-batch 50";
      extraArgs = [
        "--no-mmproj-offload"
        "--image-min-tokens"
        "1024"
        "--kv-unified"
        "--ctx-checkpoints"
        "2"
        "--keep"
        "1024"
        "--no-warmup"
        "--prio"
        "2"
        "--prio-batch"
        "3"
        "--parallel"
        "2"
        "--cont-batching"
      ];
      user = "root";
      scheduler = null;
    };

    # --- host-ncmoe35: ncmoe=35 é +7.3% vs baseline (32.5 vs 30.3 tok/s) ---
    # Testado 2026-08-26: upstream llama.cpp, ncmoe=35 coloca experts das
    # layers 35-44 na GPU, restante na CPU. Mais VRAM (4933 MiB) mas mais rápido.
    # REQUER upstream llama.cpp (NÃO wackmall). Se wackmall, usar host-ehs.
    host-ncmoe35 = {
      model = "llm-host";
      mmproj = "llm-host-mmproj";
      threads = 8;
      ctxSize = 32768;
      batchSize = 512;
      ubatch = 512;
      gpuLayers = 45;
      kvCache = "-fa on -ctk q4_0 -ctv q4_0";
      moeFlags = "--n-cpu-moe 35 --split-mode layer";
      extraArgs = [
        "--no-mmproj-offload"
        "--image-min-tokens"
        "1024"
        "--parallel"
        "1"
        "--jinja"
        "--no-warmup"
      ];
      user = "nixos";
      scheduler = null;
    };

    # --- host-ehs: Expert Hot Store (fork wackmall, +25.6% compute) ---
    # Requer binario compilado: ~/projects/llama-wackmall/build/bin/llama-server
    # Medido: 60.28 → 48.00 ms/token (+25.6%), GPU util 20.5% → 32.2%
    # NÃO usar --n-cpu-moe com -ehs (auto-ativa --cmoe)
    host-ehs = {
      model = "llm-host";
      mmproj = "llm-host-mmproj";
      threads = 8;
      ctxSize = 8192;
      batchSize = 512;
      ubatch = 512;
      gpuLayers = 45;
      kvCache = "-fa on -ctk q4_0 -ctv q4_0";
      moeFlags = "-ehs 25 --split-mode layer";
      extraArgs = [
        "--parallel"
        "1"
        "--jinja"
      ];
      user = "nixos";
      scheduler = null;
      wrapper = "llama-wackmall-wrapper";
    };

    # --- host-ehs-optimized: melhor dos dois mundos ---
    # Combina EHS-25 (hot experts na GPU) com todas as flags de otimização do host.
    # VRAM budget: 6141 - 2400 (modelo) - 1895 (EHS) = 1846 MB para KV cache.
    # 16384 tokens × 64 KB = 1024 MB — cabe com margem.
    # Se o cooler sustentar clocks altos, este profile deve ser o mais rápido.
    host-ehs-optimized = {
      model = "llm-host";
      mmproj = "llm-host-mmproj";
      threads = 12;
      ctxSize = 16384;
      batchSize = 1024;
      ubatch = 1024;
      gpuLayers = 45;
      kvCache = "-fa on -ctk q4_0 -ctv q4_0";
      moeFlags = "-ehs 25 --split-mode layer --poll 50 --poll-batch 50";
      extraArgs = [
        "--no-mmproj-offload"
        "--image-min-tokens"
        "1024"
        "--kv-unified"
        "--ctx-checkpoints"
        "2"
        "--keep"
        "1024"
        "--no-warmup"
        "--prio"
        "2"
        "--prio-batch"
        "3"
        "--parallel"
        "2"
        "--cont-batching"
        "--jinja"
      ];
      user = "nixos";
      scheduler = null;
      wrapper = "llama-wackmall-wrapper";
    };
  };
}
