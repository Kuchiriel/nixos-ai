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
  hostBase = {    model = "llm-host";
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
in rec {
  # =========================================================================
  # 1. ARQUIVOS DE MODELO
  # =========================================================================

  # --- LLM — Lab (VM, CPU) ---
  # Qwen3-4B: tool calling nativo via chat template (--jinja), 2.5GB.
  llm-vm = mkModel {
    url = "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf";
    sha256 = "sha256-dIX+bxGvKUM7xRyrWACVIfIFhA9bSuOjL6f5LoU0/fU=";
  };

  # --- Candidatos fast avaliados 2026-09-08 (arquivos verificados) ---
  # Gemma 3 4B Q4_K_M: melhor chat/coding textual 4B + único multimodal
  # pequeno (visão). SEM tool-calling nativo neste server path: 0/35
  # free, 35/35 constrained — só serve sob strict_tools. (A/B n=5.)
  llm-gemma-4b = mkModel {
    url = "https://huggingface.co/unsloth/gemma-3-4b-it-GGUF/resolve/main/gemma-3-4b-it-Q4_K_M.gguf";
    sha256 = "sha256-BKQ6IujSAD3tpazCYvaOwQBfp2xzWpliqMdwQqdKfRk=";
  };

  # Phi-4-mini Q4_K_M: chat correto, postura de recusa p/ tools (0/35
  # free, 30/35 constrained). Não recomendado p/ agent (ver relatório).
  llm-phi-4-mini = mkModel {
    url = "https://huggingface.co/unsloth/Phi-4-mini-instruct-GGUF/resolve/main/Phi-4-mini-instruct-Q4_K_M.gguf";
    sha256 = "sha256-iMACKZFAg80RKFOquE7VG4e99rnOQvUy2MhcfGOxcwo=";
  };

  # --- xLAM-2-8B Q4_K_M (Salesforce, executor especialista) ---
  # Action model BFCL-SOTA (~4.9GB). MEDIDO 2026-09-09 (GPU, prism):
  # A/B 0/0/35 (free/sys/constrained) — SEM template nativo no GGUF
  # (server: "Unable to generate parser", 400 em tools param) → opera
  # SÓ via strict/constrained; emite arrays (calls paralelas!) e chains
  # corretas; chat puro incapaz (sempre aciona). Licença CC-BY-NC-4.0
  # (não-comercial — difere do resto MIT/Apache; notar no uso).
  # Adotado como executor strict (Qwen segue fast geral).
  llm-xlam-8b = mkModel {
    url = "https://huggingface.co/Salesforce/Llama-xLAM-2-8b-fc-r-gguf/resolve/main/Llama-xLAM-2-8B-fc-r-Q4_K_M.gguf";
    sha256 = "sha256-6xC0DTbIDoGmb4BGSisAn0gcTMWxkm7TZpMjn6Yt1+k=";
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

  # ══════════════════════════════════════════════════════════════════
  # Qwen3.6-35B-A3B-UNCENSORED (HauhauCS Aggressive) — variantes de quant
  # ══════════════════════════════════════════════════════════════════
  # Base: Qwen/Qwen3.6-35B-A3B · 35B total / ~3B ativos · 256 experts,
  # 8 roteados/token · atencao hibrida (linear 3:1) · 40 camadas · 262K
  # nativo · multimodal (texto/imagem/video) · thinking por padrao.
  #
  # RODAR EXATAMENTE COMO O Qwen3-30B-A3B (fonte: docs/models/BINARIES.md
  # — binario errado = veredito invalido):
  #   binario = ik_llama.cpp (unico com --n-cpu-moe; prism = ternario,
  #            upstream = sem offload de MoE). Tier endpoint 8084.
  #   perfil  = chat/jarvis (hostBase + moeFlags "--n-cpu-moe 35 --mlock")
#   --mlock (25/09): trava os 20GB de pesos do MoE na RAM. Alvo do resultado
#   BIMODAL medido (40 t/s ou 15 t/s, 2,7x, sem ser config): a suspeita e
#   paginacao do mmap — 20GB de pesos contra 32GB de RAM com zram de 15,5GB.
#   Com mlock o kernel nao pode despejar as paginas do modelo no zram nem
#   reler do disco, que e o mecanismo que faria o mesmo config cair 2,7x.
#   Degradacao graciosa: se nao houver memoria para travar, o llama.cpp avisa
#   e segue (nao aborta), entao o risco e baixo e o upside e o maior da lista.
  #   flags   = -ngl 45 (attn+dense na GPU, experts na CPU), -t 6,
  #             -c >= 4096, -fa on, -ctk/-ctv q4_0, -b/-ub 512,
  #             --parallel 1, --jinja
  #   thinking: authors recomendam ON (geral temp 1.0/top_p .95/top_k 20/
  #     presence_penalty 1.5; coding temp 0.6/presence 0). O JARVIS desliga
  #     thinking por padrao (H3: 3x turnos sem ganho no bonsai) — para este
  #     tier o DONO decide: JARVIS_LLM_DISABLE_THINKING=0.
  #   contexto: authors pedem >=128K p/ preservar thinking. Na 6GB com
  #     experts na CPU e inviavel agora (KV+RAM); validado com 4k-8k.
  #
  # EVIDENCIA (RTX 4050 6GB, ik build 4854/b166e269, 2-3 reps):
  #   - Qwen3.6-35B-A3B-UD-Q4_K_M (mesmo porte, base): 35,5 t/s
  #     (-ngl 45 --n-cpu-moe 35 -t 6) — ver sweep 25/09: -t 6 = so P-cores
  #   - mesmo com --n-cpu-moe 36 (todos experts CPU): 19,25 t/s → 35 vence
  #   - ik vs upstream no mesmo modelo: 36 vs 32 t/s (+11%) → ik e o binario
  #   - wackmall EHS 18 t/s · prism no MoE 2-3 t/s (PROIBIDO)
  #   - Qwen3-30B-A3B-Q4_K_M ja roda a 30+ t/s neste mesmo perfil
  # ! RAM (25/09, incidente): este MoE segura ~18GB de RAM (experts CPU).
  #   Com router+embeddings+rerank+sessao, 32GB estouram (28/31, 0 livre) e
  #   o SO congela. Rodar com esses servicos PARADOS + ulimit, ou nao rodar.
  #   O guard de VRAM do `jarvis space serve` existe exatamente por isso.
  # ──────────────────────────────────────────────────────────────────

  # Família completa do autor (sha256 oficial via API HF; o sha local do
  # Q4_K_M em ~/models confere com o oficial — download íntegro):
  llm-uncensored-35b = mkModel {
    # Q4_K_M.gguf · 21.2GB  # baixado 25/09 em ~/models
    url = "https://huggingface.co/HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive/resolve/main/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf";
    sha256 = "sha256-u+9Yw3zoiCC+nZi2Q38c9LrIkMlHvVX8e2jiIJhXQjE=";
  };

  llm-uncensored-35b-kp = mkModel {
    # Q4_K_P.gguf · 23.4GB  # K_P = imatrix por modelo (+1-2 niveis de quant)
    url = "https://huggingface.co/HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive/resolve/main/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_P.gguf";
    sha256 = "sha256-jTRKQzbY6n2gy/wSeS0UceVovnq+iTDFImBpi/0B1zE=";
  };

  llm-uncensored-35b-kp-q3 = mkModel {
    # Q3_K_P.gguf · 19.0GB  # MENOR que o K_M: menos RAM — alvo p/ 6GB VRAM + 32GB RAM
    url = "https://huggingface.co/HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive/resolve/main/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q3_K_P.gguf";
    sha256 = "sha256-GFCPN/x3h/Jg33rBo5NLFd2UltBQstS4ZCQbSTWI/pU=";
  };

  llm-uncensored-35b-kp-q2 = mkModel {
    # Q2_K_P.gguf · 15.0GB  # o menor da familia K_P (15GB)
    url = "https://huggingface.co/HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive/resolve/main/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q2_K_P.gguf";
    sha256 = "sha256-WpfzjbD/tFW7y6enx7joLR5CdA3dMIk6wa1Xot9elKQ=";
  };

  llm-uncensored-35b-mmproj = mkModel {
    # mmproj-f16.gguf · 0.9GB  # visao/video: exige o projector ao lado do GGUF
    url = "https://huggingface.co/HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive/resolve/main/mmproj-Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-f16.gguf";
    sha256 = "sha256-yOcCNEqB+MImqRSqmA7W4fYEvOk3Tx/tjmXIlpCK9BQ=";
  };

  # --- LLM Bonsai — Host (bare metal), motor ternário ---
  # Ternary-Bonsai-8B Q2_0_g64 (Qwen3-8B denso ternário {-1,0,+1}, 2.15GiB).
  # Servidor atual: fork PrismML. VERIFICADO 2026-09-08: upstream b10809
  # também serve Q2_0 (chat ok em CPU) — o "trava no load" era de builds
  # antigos. Prism mantido pelo desempenho (kernels ternários CUDA,
  # medido TG 71-76 t/s) — trocar p/ upstream exige remediar GPU antes.
  # Medido 2026-09-05 (b10660, RTX 4050): PP512 1956, TG128 76.7. b10735 (24/09):
  # TG 72.6-72.7 (=par), PP512 1776 (ruído térmico), MAS lê layouts novos
  # (27B, PQ2_0/PTQ) que o b10660 NÃO abre — wrapper/roteador apontam p/ b10735.
  llm-bonsai = mkModel {
    url = "https://huggingface.co/prism-ml/Ternary-Bonsai-8B-gguf/resolve/main/Ternary-Bonsai-8B-Q2_0_g64.gguf";
    sha256 = "sha256-4XspjYTueHl5Fq5cLsyCEUacxlzM/jCAzZqbtQP7xV4=";
  };

  # BENCH SPEC-DECODE 24/09 (llama-server :8095, prompt código, n=128, 3 reps,
  # draft=Qwen3-0.6B-Q8_0, ngram-mod-n-max 16): bonsai baseline 72.0-72.3 t/s
  # · +draft 71.9-72.2 t/s · +ngram 71.8-72.3 t/s → GANHO ZERO no bonsai:
  # kernels ternários prism já saturam; spec-decode só paga em dense-Q4
  # LENTO (~12 t/s — régua do vídeo DFlash/GTX1060). NÃO ativar no bonsai.
  # BENCH 2 24/09: Qwen3-4B-Q4_K_M (~/models, PRISM) baseline 60.3-60.7 t/s
  # · +draft 60.1-60.6 · +ngram 59.5-60.2 → GANHO ZERO TAMBÉM. VEREDITO
  # GERAL p/ RTX 4050 6GB: spec-decode NÃO APLICÁVEL — qualquer modelo que
  # cabe inteiro já roda >=60 t/s (sem headroom); MoE+spec = piora (DFlash).
  # LINHA ENCERRADA — não refazer sem hardware novo. Flags ficam p/ referência:
  # --spec-draft-model F [-ctkd q4_0 -ctvd q4_0] / --spec-ngram-mod-n-max 16.
  llm-draft-qwen05 = mkModel {
    url = "https://huggingface.co/Qwen/Qwen3-0.6B-GGUF/resolve/main/Qwen3-0.6B-Q8_0.gguf";
    sha256 = "sha256-lGXmOiKt1TVNm7S5npARcEPHEkAHZkkHJZvRbQQ7sDE=";
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
  # Snapshot completo (4 arquivos): linkado p/ o cache HF em
  # home-manager/modules/services/jarvis-wakeword.nix (modelsLink).
  # Fonte de verdade dos 4 hashes — nada de wget imperativo.
  whisper-small = {
    model = fetchurl {
      url = "https://huggingface.co/Systran/faster-whisper-small/resolve/main/model.bin";
      sha256 = "0wfnf10y3g779xxsjkdji7xij92xwxrw5r13c20p523da0hmjc1y";
    };
    config = fetchurl {
      url = "https://huggingface.co/Systran/faster-whisper-small/resolve/main/config.json";
      sha256 = "0a5q7ww1805lwg6dja8jxkz031zxxm0an7n0s93sx9s0g6n9cm5m";
    };
    vocabulary = fetchurl {
      url = "https://huggingface.co/Systran/faster-whisper-small/resolve/main/vocabulary.txt";
      sha256 = "04rr8lg4mqsiz4kwyd5vqkdqdyck14ki4aflz2rjf404qphkzkil";
    };
    tokenizer = fetchurl {
      url = "https://huggingface.co/Systran/faster-whisper-small/resolve/main/tokenizer.json";
      sha256 = "1ayhdz5sczyll3s0vcrsa6cjr88664m79zbr5h44bc4v3qcn6yzv";
    };
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
      # Benchmark: ncmoe=35 -ngl 45 -t 8 = 32.5 tok/s (2026-08-26). -t 6 escolhido 25/09:
#   o i7-13620H e HIBRIDO (6P+4E=10 fisicos) e o lscpu reporta '8', escondendo a
#   assimetria. Medido no denso (gemma-3-4b CPU-only): -t6=16,4 | -t8=14,1 |
#   -t10=10,4 | -t12=7,9 t/s. E-cores e HT competem e custam ~14%.
#   No MoE -t6 vs -t8 dao o mesmo TG (14,8 vs 15,0) — bandwidth-bound.
      moeFlags = "--n-cpu-moe 35";
      extraArgs = [
        "--no-mmproj-offload"
        "--image-min-tokens"
        "1024"
        "--parallel"
        "2"
        "--jinja"
        "--mlock"
      ];
    };

    # ── Chat Profile ──
    chat = hostBase // {
      threads = 6;
      ctxSize = 8192;
      batchSize = 512;
      ubatch = 512;
      moeFlags = "--n-cpu-moe 35";
      extraArgs = [
        "--no-mmproj-offload"
        "--parallel"
        "1"
        "--jinja"
        "--mlock"
      ];
    };

    # ── Jarvis Profile ──
    jarvis = hostBase // {
      threads = 6;
      ctxSize = 4096;
      batchSize = 512;
      ubatch = 512;
      moeFlags = "--n-cpu-moe 35";
      extraArgs = [
        "--no-mmproj-offload"
        "--parallel"
        "1"
        "--jinja"
        "--mlock"
      ];
    };

    # ── Benchmark Profile ──
    # Settings reprodutíveis para medições.
    # Sem otimizações dinâmicas, tudo hardcoded.
    # Usado para comparar performance entre versões.
    # VRAM budget: 6141 MB total - 2400 MB (model) - 500 MB (safety) = 3241 MB
    # Mantém ncmoe=36 para estabilidade — experts na CPU
    benchmark = hostBase // {
      threads = 6;
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
        "--mlock"
      ];
    };

    # ── Bonsai Profile ──
    # Motor neural ternário (Qwen3-8B denso Q2_0 g64) via fork PrismML.
    # Medido 2026-09-05 (prism llama-bench, RTX 4050 6GB): PP512 1956 t/s, TG128 76.7 t/s.
    # Denso = full offload, sem MoE flags. 36 layers, 8 KV heads, head_dim 128:
    # KV q4_0 ≈ 37KB/tok → 32K ctx ≈ 1.2GB; pesos 2.15GB; total ≈ 3.4GB < 6GB.
    # Limitação conhecida: sem mmproj (text-only; observe_screen inoperante).
    bonsai = {
      model = "llm-bonsai";
      mmproj = null;
      gpuLayers = 99; # todas as 36 layers na GPU (denso, sem experts)
      kvCache = "-fa on -ctk q4_0 -ctv q4_0";
      threads = 6;
      ctxSize = 49152;
      batchSize = 2048;
      ubatch = 512;
      moeFlags = "";
      wrapper = "llama-prism-wrapper";
      extraArgs = [
        "--parallel"
        "1"
        "--jinja"
        "--no-warmup"
      ];
      user = "nixos";
      scheduler = null;
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
      threads = 6;
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
      threads = 6;
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
    #
    # VRAM: 45 GPU layers causa OOM durante inferência no RTX 4050 6GB.
    # O modelo carrega mas crasha após o primeiro request.
    # 25 layers roda estável (13.8 tok/s).
    # Para testar um valor maior sem risco de regressão, incremente
    # gradualmente (30, 35, 40) e valide com uma query real antes de
    # fazer nixos-rebuild switch.
    fast = hostBase // {
      gpuLayers = 25;
      threads = 6;
      ctxSize = 4096;
      batchSize = 512;
      ubatch = 512;
      mmproj = null; # Disable vision model — saves 861MB VRAM + prevents crash
      moeFlags = "--n-cpu-moe 35";
      extraArgs = [
        "--parallel"
        "1"
        "--jinja"
        "--mlock"
        "--no-warmup"
      ];
      user = "nixos";
    };

    # ── Qwen Fast Profile (host, GPU) ──
    # Qwen3-4B denso para o tier `jarvis-fast` do router: tool calling
    # nativo, ~2.5GB, full offload (28 layers densas, sem MoE flags).
    # KV q4_0 16K ≈ 1GB; total ≈ 3.5GB < 6GB com folga p/ Bonsai→fast
    # convivência transitória durante o switch do router (max 1 residente,
    # mas o unload/load transiente pode sobrepor brevemente).
    qwen-fast = {
      model = "llm-vm";
      mmproj = null;
      gpuLayers = 99; # todas as layers densas na GPU (ngl alto = "todas")
      kvCache = "-fa on -ctk q4_0 -ctv q4_0";
      threads = 6;
      ctxSize = 16384;
      batchSize = 1024;
      ubatch = 512;
      moeFlags = "";
      extraArgs = [
        "--parallel"
        "1"
        "--jinja"
        "--no-warmup"
      ];
      user = "nixos";
      scheduler = null;
    };
  };

  # ── Raw Profiles (uncensored, A/B 24-25/09: sem refusal bobo em gates;
  #  aligned desvia com tools/genérico/negação, uncensored passa direto) ──
  # Arquivos em ~/models (impuro, fora do store — precedente: wrappers
  # prism/ik). modelFile absoluto; mkPresetSection usa o literal.
  # Alvo de hot-swap (idle reload): /model jarvis-raw*.
  extraProfiles = {
    raw-fast = profiles.qwen-fast // {
      modelFile = "/home/nixos/models/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf";
    };
    raw-strong = profiles.chat // {
      modelFile = "/home/nixos/models/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf";
    };
  };

  # =========================================================================
  # 3. ROUTING — metadata declarativa p/ o router nativo do llama-server
  #    + registry JSON consumido pelo Python (model_registry.py).
  #    ÚNICA FONTE: este bloco referencia `profiles` e arquivos acima —
  #    nada de dict Python espelhando estes dados.
  # =========================================================================
  routing = {
    version = 1;
    # Default EFETIVO hoje (bonsai serve :8080): preservado — §21, produto
    # decide eventual troca p/ jarvis-fast.
    default = "bonsai";
    # Residência simultânea máxima (VRAM 6GB: 1 modelo por vez).
    maxResident = 1;
    # Binário CORRETO por modelo (docs/models/BINARIES.md — D2/D5: binário
    # errado invalida o veredito). O router NÃO escolhe binário por request:
    # llama-cpp.nix gera UM serviço por grupo (porta = endpoints.${binary}).
    endpoints = { prism = 8080; upstream = 8083; ik = 8084; };
    models = {
      bonsai = {
        profile = "bonsai";
        ctx = 49152;
        tier = "speed";
        capabilities = ["general" "coding" "tools" "pt"];
        params_b = 8;
        vram_mb = 2400;
        # Prism fork exigido (Q2_0 g64 fora do upstream).
        needsWrapper = "llama-prism-wrapper";
        binary = "prism";
        endpoint = 8080;
        serve = { host = true; vm = true; };
      };
      jarvis-fast = {
        profile = "qwen-fast";
        ctx = 49152;
        profileVm = "vm";
        tier = "fast";
        capabilities = ["general" "coding" "tools" "pt"];
        params_b = 4;
        vram_mb = 2600;
        needsWrapper = null;
        binary = "upstream";
        endpoint = 8083;
        serve = { host = true; vm = true; };
      };
      jarvis-strong = {
        profile = "chat";
        ctx = 32768;
        tier = "reasoning";
        capabilities = ["general" "coding" "tools" "reasoning" "analysis" "vision" "pt"];
        params_b = 35;
        vram_mb = 4600;
        needsWrapper = null;
        binary = "ik";
        endpoint = 8084;
        serve = { host = true; vm = false; };
        # Herdado do profile chat: mmproj na CPU (861MB VRAM) + visão dinâmica.
        iniExtra = ["no-mmproj-offload = true" "image-min-tokens = 1024"];
      };
      # Hot-swap raw (uncensored, A/B 24-25/09): sem refusal em gates.
      # /model jarvis-raw* ou capability "uncensored" no select_model.
      jarvis-raw = {
        profile = "raw-fast";
        ctx = 16384;
        tier = "fast";
        capabilities = ["general" "coding" "tools" "pt" "uncensored"];
        params_b = 4;
        vram_mb = 2700;
        needsWrapper = null;
        binary = "upstream";
        endpoint = 8083;
        serve = { host = true; vm = false; };
      };
      jarvis-raw-strong = {
        profile = "raw-strong";
        ctx = 8192;
        tier = "reasoning";
        capabilities = ["general" "coding" "tools" "reasoning" "analysis" "pt" "uncensored"];
        params_b = 35;
        vram_mb = 4600;
        needsWrapper = null;
        binary = "ik";
        endpoint = 8084;
        serve = { host = true; vm = false; };
        iniExtra = ["no-mmproj-offload = true" "image-min-tokens = 1024"];
      };
    };
  };

  # JSON derivado (builtins.toJSON puro — sem derivação): llama-cpp.nix
  # gera o preset INI e /etc/jarvis/model-registry.json daqui.
  registryJson = builtins.toJSON routing;
}
