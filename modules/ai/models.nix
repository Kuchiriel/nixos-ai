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
# Perfis por caso de uso:
#   - roo-dev: Contexto grande para coding (32K tokens, parallel=2)
#   - chat: Throughput máximo para conversas (16K tokens, parallel=1)
#   - jarvis: Baixa latência para voz (8K tokens, parallel=1)
#   - benchmark: Settings reprodutíveis para medições

let
  mkModel = {
    url,
    sha256,
  }:
    fetchurl {inherit url sha256;};

  # ── VRAM Budget Calculator ──
  # RTX 4050 Laptop: 6144 MB VRAM total
  # Model Q4_K_M: ~2400 MB
  # Safety margin: 500 MB
  # KV cache per token: ~64 bytes (q4_0 quantization)
  totalVram = 6144; # MB
  modelSize = 2400; # MB
  safetyMargin = 500; # MB
  availableForKvAndExperts = totalVram - modelSize - safetyMargin; # 3244 MB

  # Calculate safe KV cache size based on context
  kvBytesPerToken = 64; # bytes per token (q4_0)
  calculateKvSize = ctxSize: (ctxSize * kvBytesPerToken) / 1024; # KB

  # Calculate experts that can fit on GPU
  expertSize = 100; # MB per expert layer
  maxExpertsOnGpu = availableForKvAndExperts / expertSize; # ~32 experts

  # Base profile for host models
  hostBase = {
    model = "llm-host";
    mmproj = "llm-host-mmproj";
    gpuLayers = 45; # Max layers on GPU for RTX 4050
    kvCache = "-fa on -ctk q4_0 -ctv q4_0";
    # User for the llama-server process. "nixos" is sufficient when:
    #   - /dev/nvidia* is accessible via the "video" group
    #   - Nix store paths are readable (they are world-readable by default)
    #   - Model files are in /nix/store (not a custom path requiring root)
    # Use "root" only if a specific profile needs direct hardware access
    # that the nixos user cannot obtain via groups.
    user = "nixos";
    scheduler = null;
  };
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
    # Vozes por idioma (lang_code Kokoro → voice file)
    voices = {
      # American English (lang_code='a')
      af_heart = fetchurl {
        url = "https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/voices/af_heart.pt";
        sha256 = "1zxl5h82lf0jggbd0fi56dvsyq2vyyc1vlcwhkyrpcgsiydp1d8a";
      };
      # Brazilian Portuguese (lang_code='p')
      pf_dora = fetchurl {
        url = "https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/voices/pf_dora.pt";
        sha256 = "sha256-B+T/mHxdWow5le/RXMTw23xMFeiBsZjYq39n7PUfXrc=";
      };
      pm_alex = fetchurl {
        url = "https://huggingface.co/hexgrad/Kokoro-82M/resolve/main/voices/pm_alex.pt";
        sha256 = "sha256-zwuoxXPCSA/FQSNoOjXPHirhMEKORB65H5FJvbGIpSY=";
      };
    };
    # Legacy compat: voice = af_heart (for old code that reads kokoro.voice)
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
    # ── VM Profile ──
    # Para lab/VM com CPU only. Qwen3-4B com contexto grande.
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

    # ── Roo Dev Profile ──
    # Contexto grande (32K) para coding com tool calling.
    # Parallel=2 para múltiplas ferramentas simultâneas.
    # Prioriza qualidade sobre velocidade.
    # VRAM budget: 6141 MB total - 2400 MB (model) - 500 MB (safety) = 3241 MB
    # Mas: experts precisam de VRAM também! ncmoe=36 mantém ALL experts na CPU
    # (36 experts × ~100MB = 3600 MB se fossem na GPU — impossível)
    roo-dev = hostBase // {
      threads = 12;
      ctxSize = 32768;
      batchSize = 1024;
      ubatch = 1024;
      # Mantém ncmoe=36 (todos experts na CPU) — RTX 4050 não tem VRAM suficiente
      # para experts na GPU E contexto grande E modelo dense layers
      # Benchmark: ncmoe=35 -ngl 45 -t 8 = 32.5 tok/s (2026-08-26)
      moeFlags = "--n-cpu-moe 35";
      extraArgs = [
        "--no-mmproj-offload"
        "--image-min-tokens"
        "1024"
        "--parallel"
        "2"
        "--jinja"
      ];
    };

    # ── Chat Profile ──
    chat = hostBase // {
      threads = 8;
      ctxSize = 8192;
      batchSize = 512;
      ubatch = 512;
      moeFlags = "--n-cpu-moe 35";
      extraArgs = [
        "--no-mmproj-offload"
        "--parallel"
        "1"
        "--jinja"
      ];
    };

    # ── Jarvis Profile ──
    jarvis = hostBase // {
      threads = 8;
      ctxSize = 4096;
      batchSize = 512;
      ubatch = 512;
      moeFlags = "--n-cpu-moe 35";
      extraArgs = [
        "--no-mmproj-offload"
        "--parallel"
        "1"
        "--jinja"
      ];
    };

    # ── Benchmark Profile ──
    # Settings reprodutíveis para medições.
    # Sem otimizações dinâmicas, tudo hardcoded.
    # Usado para comparar performance entre versões.
    # VRAM budget: 6141 MB total - 2400 MB (model) - 500 MB (safety) = 3241 MB
    # Mantém ncmoe=36 para estabilidade — experts na CPU
    benchmark = hostBase // {
      threads = 8;
      ctxSize = 2048; # Pequeno para benchmarks rápidos
      batchSize = 512;
      ubatch = 512;
      # Mantém ncmoe=36 — experts na CPU para não estourar VRAM
      moeFlags = "--n-cpu-moe 35";
      extraArgs = [
        "--no-mmproj-offload"
        "--image-min-tokens"
        "1024"
        "--parallel"
        "1"
        "--no-warmup"
        "--jinja"
      ];
    };

    # ── Legacy Profiles (mantidos para compatibilidade) ──

    # host: Profile original para o servidor principal
    host = hostBase // {
      threads = 12;
      ctxSize = 32768;
      batchSize = 1024;
      ubatch = 1024;
      moeFlags = "--n-cpu-moe 36 --split-mode layer --poll 50 --poll-batch 50";
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
    };

    # host-ncmoe35: Variante mais rápida com mais experts na GPU
    host-ncmoe35 = hostBase // {
      threads = 8;
      ctxSize = 32768;
      batchSize = 512;
      ubatch = 512;
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
    };

    # host-ehs: Expert Hot Store (fork wackmall)
    host-ehs = hostBase // {
      threads = 8;
      ctxSize = 8192;
      batchSize = 512;
      ubatch = 512;
      moeFlags = "-ehs 25 --split-mode layer";
      extraArgs = [
        "--parallel"
        "1"
        "--jinja"
      ];
      user = "nixos";
      wrapper = "llama-wackmall-wrapper";
    };

    # host-ehs-optimized: Combina EHS com otimizações
    host-ehs-optimized = hostBase // {
      threads = 12;
      ctxSize = 16384;
      batchSize = 1024;
      ubatch = 1024;
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
      wrapper = "llama-wackmall-wrapper";
    };

    # ── Fast Profile ──
    # Otimizado para agent loop / baixa latência.
    # Contexto pequeno (8K) libera VRAM para mais experts na GPU.
    # VRAM budget: 6141 MB - 2400 MB (model) - 500 MB (safety) = 3244 MB
    # KV cache 8K * parallel=1 * q4_0 ≈ 512 MB
    # Experts cabem: (3244 - 512) / 100 ≈ 27 experts na GPU
    # Resultado: ~3x mais rápido que roo-dev para tarefas simples
    # ── Fast Profile ──
    # REPLICANDO EXATAMENTE o benchmark que deu 32.5 tok/s:
    # --n-cpu-moe 35 -ngl 45 -t 8 -c 4096 -fa on -ctk q4_0 -ctv q4_0
    # Sem split-mode, poll, kv-unified, ctx-checkpoints, keep, prio, parallel
    fast = hostBase // {
      gpuLayers = 45;
      threads = 8;
      ctxSize = 4096;
      batchSize = 512;
      ubatch = 512;
      moeFlags = "--n-cpu-moe 35 --split-mode layer";
      extraArgs = [
        "--parallel"
        "1"
        "--jinja"
        "--no-warmup"
      ];
      user = "nixos";
    };
  };
}
