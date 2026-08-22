{ fetchurl, lib }:

# Modelos de IA baixados declarativamente via fetchurl.
#
# Por quê: o legado baixava modelos imperativamente (pip/site-packages, URLs
# soltas em runtime) — no host NixOS isso quebraria (ex: wakeword apontava para
# ~/.local/lib/python3.14 que não existe no Nix). Com fetchurl, os modelos
# vivem no store imutável e o sistema nasce com tudo — download apenas no
# build, com hash verificado. Nada de runtime imperativo.
#
# ═══════════════════════════════════════════════════════════════════════
# ESTE ARQUIVO É A ÚNICA FONTE DE VERDADE DA INTELIGÊNCIA DO SISTEMA:
#   1. os ARQUIVOS de modelo (fetchurl, hash verificado) e
#   2. os PERFIS de execução (`profiles`) — o módulo services/llama-cpp.nix
#      apenas consome `pkgs.aiModels.profiles.<cenário>`; nenhum parâmetro
#      (arquivo, threads, ctx, ubatch, GPU layers, KV cache, scheduler) é
#      duplicado ou hardcoded fora daqui.
# ═══════════════════════════════════════════════════════════════════════
#
# Cenários:
#   - vm  (Lab, CPU): Qwen3-4B (2.5GB) — SLM com tool calling nativo via
#     --jinja, rápido o bastante para o agente no lab (substitui o Qwen2.5-7B,
#     que tinha bugs de tool_call com gramática).
#   - host (Bare metal — Acer Nitro V15, RTX 4050 6GB / 32GB RAM):
#     Qwen3.6-35B-A3B (MoE 35B total / 3B ativos + vision encoder) em
#     GGUF UD-Q4_K_M (~20.6GiB) com expert offloading: atenção na GPU,
#     experts roteados na RAM (32GB), VRAM de 6GB preservada.
#
# ─── COMO TROCAR UM MODELO (100% declarativo, sem resíduo) ──────────────
# 1. Edite a URL + sha256 do modelo aqui (hash do arquivo — obter sem baixar:
#    `nix hash to-sri --type sha256 <sha256 do arquivo>` ou o LFS oid do HF).
# 2. `./rebuild.sh` — o modelo novo entra no store; o serviço aponta para ele.
# 3. O modelo ANTIGO vira lixo de store: `nh clean` (timer semanal já ativo)
#    ou `nix-collect-garbage -d` remove — nada de arquivo solto em /home.
#    O modelo do host (22GB) só é baixado quando um host com profile "host"
#    referencia esta derivação (fetchurl é lazy).
#
# Fontes:
#   - Qwen3-4B: Qwen/Qwen3-4B-GGUF (oficial)
#   - Qwen3.6-35B-A3B + mmproj (vision): unsloth/Qwen3.6-35B-A3B-GGUF
#     (o repo oficial Qwen/Qwen3.6-35B-A3B-GGUF é gated/auth)
#   - nomic-embed-text-v2-moe: nomic-ai/nomic-embed-text-v2-moe-GGUF
#   - bge-reranker-v2-m3: gpustack/bge-reranker-v2-m3-GGUF
#   - openwakeword: releases oficiais GitHub v0.5.1 (onnx)
#   - Kokoro-82M: hexgrad/Kokoro-82M (Apache-2.0) — formato TORCH do nixpkgs
#   - faster-whisper: Systran/faster-whisper-small (CTranslate2)

let
  mkModel = { url, sha256 }: fetchurl { inherit url sha256; };
in
{
  # =========================================================================
  # 1. ARQUIVOS DE MODELO
  # =========================================================================

  # --- LLM — Lab (VM, CPU) ---
  # Qwen3-4B: tool calling nativo via chat template (--jinja), 2.5GB.
  # Escolhido por pesquisa (maio/2026): melhor custo/benefício de SLM para
  # tool calling em CPU — supera o Qwen2.5-7B que o lab usava (bug de
  # tool_call vazado como texto puro com gramática Hermes).
  llm-vm = mkModel {
    url = "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf";
    sha256 = "sha256-dIX+bxGvKUM7xRyrWACVIfIFhA9bSuOjL6f5LoU0/fU=";
  };

  # --- LLM — Host (bare metal) ---
  # Qwen3.6-35B-A3B: MoE (35B total, 3B ativos por token) com vision encoder
  # integrado, treinado para agentic coding / tool use (2026). GGUF UD-Q4_K_M
  # do unsloth (~20.6GiB) — cabe nos 32GB de RAM do Nitro V15.
  llm-host = mkModel {
    url = "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf";
    sha256 = "sha256-rA4sEYngVfqjbv82FYDnnFvW+Odr/7TOVH8WfVPjGmE=";
  };

  # --- Projetor de visão (multimodal) do Qwen3.6-35B-A3B ---
  # Usado com --mmproj no host para capacidade de imagem/visão.
  llm-host-mmproj = mkModel {
    url = "https://huggingface.co/unsloth/Qwen3.6-35B-A3B-GGUF/resolve/main/mmproj-BF16.gguf";
    sha256 = "sha256-NW36oxETdqT3Fl4y6HSXEzeNFwCzfPUuDFDZ8jMiM00=";
  };

  # --- Embeddings (RAG) — nomic-embed-text-v2-moe Q8_0 (512MB) ---
  # Antes baixado imperativamente para /home/nixos/models — agora no store.
  embed = mkModel {
    url = "https://huggingface.co/nomic-ai/nomic-embed-text-v2-moe-GGUF/resolve/main/nomic-embed-text-v2-moe.Q8_0.gguf";
    sha256 = "sha256-Buen5ZSiaYVSPBg4OrpKrTn+bhTwj/xqtbVU4czcPP8=";
  };

  # --- bge-reranker-v2-m3 (Fase 10 — reranker cross-encoder, multi-língua) ---
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

  # --- Kokoro-82M (TTS, formato torch do nixpkgs) ---
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
  # Consumido por modules/services/llama-cpp.nix via
  # `pkgs.aiModels.profiles.${config.services.llama-cpp-server.profile}`.
  #
  # Valores calibrados por pesquisa (2026):
  #   - host: guia de offloading MoE do llama.cpp (DocShotgun) + artigos
  #     "Qwen3.6-35B-A3B em 6GB VRAM" (RTX 4050): atenção na GPU, experts
  #     roteados na RAM via --n-cpu-moe, KV-cache q8_0, -fa on (flash
  #     attention), -ngl conservador (ajustável 14→18 no host real).
  #   - vm: CPU puro (gpuLayers=0), KV f16 (sem GPU não compensa q8), 4
  #     threads (VM compartilhada com o host Hyper-V).
  profiles = {
    vm = {
      model = "llm-vm";
      threads = 4;
      ctxSize = 131072;
      batchSize = 512;
      ubatch = 512;
      gpuLayers = 0;                    # CPU puro no lab
      kvCache = "-fa on -ctk f16 -ctv f16";
      moeFlags = "";
      user = "nixos";
      scheduler = null;                 # CFS (default) — VM compartilhada
    };    # Host: RTX 4050 6GB + 32GB RAM, Qwen3.6-35B-A3B MoE + vision
    # VRAM budget (6GB total):
    #   weights:  10 × 0.237GB = 2.37GB (attn+4experts/camada)
    #   KV q8_0:  16K ctx     = 0.62GB
    #   overhead: base(0.5) + mmproj(0.8) + cuda_compute(~1.0) = 2.30GB
    #   TOTAL:    5.30GB (0.70GB margem de segurança)
    # 6 routed experts → RAM (120GB/s DDR5), 2 routed + 2 shared → GPU (260GB/s)
    # Forecast: ~25-30 t/s (bandwidth-bound, MoE esparsa top-k=2)
    # Host: RTX 4050 6GB + 32GB RAM, Qwen3.6-35B-A3B MoE + vision
    #
    # VRAM budget (6GB total, mmproj na CPU via --no-mmproj-offload):
    #   attention 50 layers: ~3600 MiB (todas na GPU)
    #   KV q4_0 128K:        ~500 MiB
    #   CUDA overhead:       ~200 MiB
    #   TOTAL:               ~4300 MiB (1800 MiB margem)
    #   mmproj BF16:         861 MiB na CPU (usa RAM, não VRAM)
    #
    # Experts (20GB GGUF) ficam na RAM (32GB DDR5 ~120GB/s)
    # CPU lê experts sob demanda quando router seleciona top-k
    # Forecast: ~32 t/s decode, ~367 t/s prefill, 0.7% drift

    host = {
        model = "llm-host";
        mmproj = "llm-host-mmproj";  # vision encoder (BF16, 861MB) — roda em CPU via --no-mmproj-offload
        threads = 12;              # testando: 16 threads no i7-13620H (20 available)
        
        # 128K contexto para suportar Aider/Freebuff com projetos grandes.
        # KV cache q4_0 mantém VRAM dentro do budget (~2.5GB para 128K).
        ctxSize = 65536;
        batchSize = 2048;        
        ubatch = 2048;
        gpuLayers = 54;            # OTIMIZADO: 50 layers na GPU, mmproj na CPU = 32t/s estável + 27GB RAM livre
       
        kvCache = "-fa on -ctk q4_0 -ctv q4_0";         

        # Sintaxe estrita e padrão para a execução de MoE do Qwen
        moeFlags = "--n-cpu-moe 50 --split-mode layer --poll 50 --poll-batch 50";

        # Flags do llama.cpp 10273 (ver docs/architecture/llama-cpp-tuning.md)
        extraArgs = [
            "--no-mmproj-offload"             # CRÍTICO: mmproj na CPU, libera 900MiB VRAM para attention
            "--image-min-tokens" "1024" 
            "--kv-unified"                    # KV cache unificado (economiza VRAM)
            "--ctx-checkpoints" "2"          # Checkpoints de contexto para Aider/Freebuff
            "--keep" "1024"
            "--no-warmup"                    # Sem warmup: +2% prefill e decode
            "--prio" "2"                     # Prioridade high para decode
            "--prio-batch" "3"               # Real-time priority para batch/prefull
       ];

        user = "root";
        scheduler = null;  # CFS default (_FIFO removido: causava overhead)_
    };

  };
}
