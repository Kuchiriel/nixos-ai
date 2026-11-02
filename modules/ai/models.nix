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

  # --- LoRA MicroTurn-Duplex (codacus, duplas-full-voz, 15MB, rank 32) ---
  # Adapter de timing p/ o modo voz duplex: camadas 36-39 (delta-net +
  # full-attn + shared expert). Treinado contra o UD-Q4_K_M. Uso: lane
  # duplex-35b (directServers) com apply em runtime. Fonte do protocolo:
  # card + docs/VOZ-FULL-DUPLEX.md.
  llm-host-lora = mkModel {
    url = "https://huggingface.co/codacus/Qwen3.6-35B-A3B-MicroTurn-Duplex-LoRA/resolve/main/microturn-duplex-lora.gguf";
    sha256 = "sha256-HTDxOXED3iNhrNtgjjP9mtbqCrN+aGQzw9646TFck3E=";
  };

  # ══════════════════════════════════════════════════════════════════
  # VISÃO — Moondream2 pinado em revision=2024-08-26
  # ══════════════════════════════════════════════════════════════════
  # 1.86B · F16 3.49 GiB · serve por PYTHON (transformers), NAO por
  # llama-server. Medido 08/10 em /home/nixos/projects/canary-official:
  #
  #   - llama-server NÃO serve imagem para este modelo (400 "Failed to
  #     tokenize prompt"): o GGUF local tem chat_template "vicuna" e o
  #     mtmd injeta um media_marker ALEATORIO que o tokenizer do Moondream
  #     nao conhece (llama.cpp #27249 / #21955). O GGUF "certo"
  #     (cjpais/moondream2-llamafile, Q8 1440MB) passa a tokenizar mas o
  #     Q8 esta DEGENERADO neste build ("capital da Franca?" -> "London").
  #   - A revision 2024-08-26 (sha 92d3d73) traz pesos + codigo CASADOS;
  #     pesos de `main` com codigo da 5d6c926 produzem saida corrompida.
  #     O proprio repo avisa: "or alternately pin to revision=2024-08-26".
  #   - transformers==4.45.2 (o 5.x quebra a geracao deste trust_remote_code).
  #   - VRAM 4120 MB em bfloat16 -> NAO divide com jarvis-fast (3.2GB) nos
  #     6GB. NeedsConflicts + ExecStartPre.
  #   - Prompt CURTO e POSITIVO: negative constraints fazem o modelo
  #     colapsar para "Grass" (medido 5/6). Nao anexar o bloco DO NOT:.
  #   - Precisao: acerta MATERIAL/COR das bordas (~60%), erra TODO detalhe
  #     de forma. Complementa a medicao de pixel; nao e autoritativo.
  #     Ver canary-official/dataset/maps/MODELS-VISION.md
  #
  # VAO-VisionProfile: visionEnv com transformers/torch/torchvision/einops.
  vlm-moondream2 = mkModel {
    url = "https://huggingface.co/vikhyatk/moondream2/resolve/92d3d73b6fd61ab84d9fe093a9c7fd8c04bf2c0d/model.safetensors";
    sha256 = "sha256-S/eu2LpDJdI/p800jXlaJ/OycmglNvCKykzdYs3nkpM=";
  };

  # Tokenizer do mesmo par (mesma revision). Sem isto o repo tenta
  # baixar "moondream/starmie-v1" da rede no __init__ e quebra offline.
  vlm-moondream2-tokenizer = mkModel {
    url = "https://huggingface.co/vikhyatk/moondream2/resolve/92d3d73b6fd61ab84d9fe093a9c7fd8c04bf2c0d/tokenizer.json";
    sha256 = "sha256-M32ja+enGm6IqpFIlnp7yHNvS0fH3o4ZupK4noBzTPw=";
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

  llm-uncensored-4b = mkModel {
    # Qwen3.5-4B Q4_K_M.gguf · 2.6GB em ~/models (hash do arquivo local).
    # Server: upstream stock -ngl 99 (GPU-full, exclusivo via Conflicts)
    # porta 8092. Ver directServers abaixo.
    url = "https://huggingface.co/HauhauCS/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive/resolve/main/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf";
    sha256 = "sha256-eeKOys+E51tgVs9AWWNtQ1qp62d5V4D3t9vH0yqWJ0E=";
  };

  llm-uncensored-4b-mtp = mkModel {
    # Qwen3.5-4B-MTP Q4_K_M.gguf · 2.7GB em ~/models (hash do arquivo local).
    # NextN REAL (blk.32.nextn.*): +24% TG medido 03/10. É o que roda na 8092.
    url = "https://huggingface.co/localweights/Qwen3.5-4B-MTP-Q4_K_M-GGUF/resolve/main/Qwen3.5-4B-MTP-Q4_K_M.gguf";
    sha256 = "sha256-FEPeY6VQp70YkFWJ3Ov6XDB9qLLvhtuFinaR+5o8Fcw=";
  };

  # ── Registro completo ~/models (auditoria GGUF 03/10) ──
  # URLs verificadas via API HF (sibling exato); hashes do arquivo local.
  llm-deepseek-7b = mkModel {
    # DeepSeek-R1-Distill-Qwen-7B · 4.68GB · reasoning model (NÃO desliga thinking!)
    url = "https://huggingface.co/bartowski/DeepSeek-R1-Distill-Qwen-7B-GGUF/resolve/main/DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf";
    sha256 = "sha256-cx7OjQbcftpvZXKZf+ue4SWNsHhIJ+ZCkJ2bVlZBk3s=";
  };

  llm-qwen30b-moe = mkModel {
    # Qwen3-30B-A3B MoE · 18.56GB · 48 layers (ik + --n-cpu-moe, como o 35B)
    url = "https://huggingface.co/Qwen/Qwen3-30B-A3B-GGUF/resolve/main/Qwen3-30B-A3B-Q4_K_M.gguf";
    sha256 = "sha256-DQA/ZmL67nhu1do+MbKcl43lrl0nXIeUxgan88AaqPU=";
  };

  llm-qwen3-4b = mkModel {
    # Qwen3-4B alinhado · 2.5GB · nativo 40960 (maior que o preset 16384!)
    # Servido hoje via preset router 8083; directServers dá unit própria.
    url = "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/Qwen3-4B-Q4_K_M.gguf";
    sha256 = "sha256-dIX+bxGvKUM7xRyrWACVIfIFhA9bSuOjL6f5LoU0/fU=";
  };

  llm-uncensored-35b-q4kp = mkModel {
    # Q4_K_P.gguf · 23.42GB · SPARE (K_M é o titular; mesmas dims/flags)
    url = "https://huggingface.co/HauhauCS/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive/resolve/main/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_P.gguf";
    sha256 = "sha256-jTRKQzbY6n2gy/wSeS0UceVovnq+iTDFImBpi/0B1zE=";
  };

  # xLAM + Phi: JÁ REGISTRADOS acima (llm-xlam-8b, llm-phi-4-mini) —
  # hashes locais 03/10 conferem byte a byte (Salesforce/unsloth íntegros).

  # ── DIRECT SERVERS (um serviço systemd por modelo) ──
  # Lido pelo gerador em modules/services/llama-uncensored.nix
  # (systemd.services gerados, Conflicts calculado = um LLM grande por
  # vez na VRAM 6GB). Flags vindas da auditoria GGUF (scripts/gguf_audit.py).
  # wanted = partida no boot (só o primário; resto é systemctl start manual).
  directServers = {
    uncensored-35b = {
      port = 8084; binary = "ik";
      modelFile = "/home/nixos/models/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf";
      # (26/10, dono: "contexto estoura na 1a mensagem") 8192→32768:
      # jarvis MCP tools ~3-5k tokens + system prompt ~2k = ~7k antes
      # de QUALQUER conversa. 8k não sobrava nada. Com fa=true e
      # ctk=q4_0 o KV escala eficientemente (~200MB @32k).
      threads = 6; ctxSize = 32768; batchSize = 512; ubatch = 512;
      gpuLayers = 45; moeFlags = "--n-cpu-moe 35";
      fa = true; ctk = "q4_0"; ctv = "q4_0";
      extraArgs = [ "--parallel" "1" "--jinja" "--mlock" "--reasoning" "off" ];
      memHigh = "21G"; memMax = "23G"; limitMemlock = true;
      wanted = false;  # default agora é o 4B-MTP (04/10, pedido do dono)
      # opencode provider (gerado em home.nix via mapAttrs):
      # id = modelFile (o server anuncia o path, sem --alias).
      opencode = { key = "local-uncensored"; name = "Qwen MoE 35B Uncensored Local"; context = 32768; output = 4096; };
    };
    # DUPLEX VOICE LANE (17/10, dono: modo voz full-duplex; ver
    # docs/VOZ-FULL-DUPLEX.md): 35B UD + MicroTurn-Duplex LoRA
    # (codacus) aplicável EM RUNTIME (--lora-init-without-apply +
    # POST /lora-adapters): "acordar" = apply, "dormir" = unapply —
    # o mesmo server serve TEXTO puro (LoRA desligado) e VOZ duplex.
    # Binário "stock" = llama.cpp v0.7.0 build local (build-stock/):
    # o nixpkgs b9190 tem qwen35moe (25/ago), mas o LoRA-apply do IK
    # é no-op (mismatch de nomes, 17/10) — o stock é o gabarito
    # comprovado (576ms/tick mediana no demo, interrupção correta).
    # Prova: /tmp/opencode/microturn-test/demo-stock.log.
    duplex-35b = {
      port = 8085; binary = "stock";
      # (17/10, escolha do dono) o QUANT UNCENSORED dele: A/B justo provou
      # que o LoRA APLICA no stock e interrompe ("Stop! Don't mix them",
      # P 0.29→fala, 526ms/tick — demo-ab-uncensored.log). O UD-Q4_K_M
      # (quant de treino do card) fica de gabarito: é mais insistente
      # (4 fragmentos vs 1) — troca = uma linha aqui.
      modelFile = "/home/nixos/models/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf";
      threads = 6; ctxSize = 8192; batchSize = 512; ubatch = 512;
      gpuLayers = 99; moeFlags = "--n-cpu-moe 44";
      # LoRA + flash-attn são incompatíveis (log do server) → fa off.
      fa = false; ctk = "f16"; ctv = "f16";
      extraArgs = [
        "--lora" "/home/nixos/models/loras/microturn-duplex/microturn-duplex-lora.gguf"
        "--lora-init-without-apply"
        "--reasoning" "off"
        "--alias" "jarvis-duplex"
        "--jinja"
      ];
      memHigh = "20G"; memMax = "24G"; limitMemlock = true;
      wanted = false;  # lane de voz: sobe no "hey jarvis acordar" (ou manual)
    };
    uncensored-4b = {
      # (19/10) binary stock (v0.7.0-dev build local): o upstream nixpkgs
      # 0.5.0 NÃO tem --lora nem /lora-adapters. O LoRA micro-turn
      # (classificador RESPOND/WAIT/SILENCE/BARGE) exige o stock.
      # (24/10, incidente 04:03) mínimo de VRAM LIVRE p/ o vram-guard:
      # modelo 2.7G + KV ~0.75G (20k ×2 MTP) + buffers ~0.6G.
      # (26/10 09:45, OOM MEDIIDO) 32768 FALHOU na 6GB com whisper
      # co-residente: KV f16 @32k (~600MB) ×2 (MTP draft context!) +
      # buffer fa=false (~1GB @32k) + modelo 2.7G = ~4.9G; com
      # whisper(0.9)+embed(0.2)+desktop = 6.3G > 6.1G → "failed to
      # allocate buffer for kv cache".
      # (26/10 10:15, HB decisão dados OC) 20k+MTP: KV 375MB×2=750MB +
      # buffer 625MB + modelo 2.7G = ~4.1G; com whisper+embed = ~5.2G;
      # margem ~900MB. MANTÉM o +24% TG do MTP. Para opencode 32k:
      # remover --spec-type draft-mtp (perde TG) OU slimming MCP tools.
      # GUARD FUTURO (lição OOM): vramMin DEVE contar MTP×2 no KV.
      vramMinMiB = 4200;  # 20k real: modelo+KV+buffer ~4.1G
      port = 8092; binary = "stock";
      # (26/10) ALIAS — id estável anunciado em /v1/models. Medido: com
      # --alias o data[].id vira o alias (sem ele = path do gguf). O
      # registry Python compara o id do modelo com o id ATIVO do server
      # (ensure_model → active_model) p/ provar identidade: com path
      # grudado no registry isso quebrava. Alias = contrato limpo.
      alias = "jarvis-mtp-lora";
      # ARQUIVO MTP (não o base!): NextN real, +24% TG. Rebuild sem isto
      # voltaria a 8092 sem speculative decoding (regressão silenciosa).
      modelFile = "/home/nixos/models/Qwen3.5-4B-MTP-Q4_K_M.gguf";
      # KV f16 híbrido (8/32 layers) ≈ 750MB @20k ×2 MTP.
      threads = 6; ctxSize = 20480; batchSize = 256; ubatch = 256;
      gpuLayers = 99; moeFlags = "";
      # (19/10) LoRA+flash-attn incompatíveis (log do server, ver
      # duplex-35b) → fa off. KV quantizado (q4_0) EXIGE fa → KV f16.
      fa = false; ctk = "f16"; ctv = "f16";
      # LoRA init sem aplicar: o cliente liga/desliga via /lora-adapters
      # SÓ nos requests do classificador (chat com tools fica limpo).
      extraArgs = [ "--parallel" "1" "--jinja" "--reasoning" "off" "--spec-type" "draft-mtp"
                    "--lora" "/home/nixos/models/loras/microturn-4b/microturn-4b-lora.gguf"
                    "--lora-init-without-apply" ];
      memHigh = "4G"; memMax = "5G"; limitMemlock = false;
      # (26/10, dono: "tira o bonsai de default e coloca o qwen mtp que tem
      # o lora pra subir com o lora") → este é o DEFAULT do sistema agora.
      # wanted=true = sobe no boot COM o LoRA registrado (medido ao vivo:
      # LoRA ON 4/4 classes corretas; LoRA OFF = base entra em "Thinking
      # Pro" e NÃO classifica nada — o classificador é o LoRA, não o base).
      # Consequência VRAM: 4.1G resident → o bonsai do router :8080 não
      # carrega junto (o default não passa mais pelo router).
      wanted = true;
      # opencode provider (gerado em home.nix via mapAttrs):
      # id = alias (o server anuncia o alias; home.nix usa svc.alias).
      opencode = { key = "local-uncensored-4b"; name = "Qwen 4B Uncensored MTP Local"; context = 20480; output = 4096; };
    };
    deepseek-7b = {
      port = 8085; binary = "upstream";
      modelFile = "/home/nixos/models/DeepSeek-R1-Distill-Qwen-7B-Q4_K_M.gguf";
      threads = 6; ctxSize = 16384; batchSize = 512; ubatch = 512;
      gpuLayers = 99; moeFlags = "";
      fa = true; ctk = "q4_0"; ctv = "q4_0";
      # SEM --reasoning off: R1 é reasoning model, pensar é o propósito.
      # Papel candidato: architect (traces de raciocínio) — NÃO medido ainda.
      extraArgs = [ "--parallel" "1" "--jinja" ];
      memHigh = "5G"; memMax = "7G"; limitMemlock = false;
      wanted = false;
      # opencode provider (gerado em home.nix via mapAttrs):
      # id = modelFile (o server anuncia o path, sem --alias).
      opencode = { key = "local-deepseek-7b"; name = "DeepSeek R1 7B Local (reasoning!)"; context = 16384; output = 8192; };
    };
    xlam-8b = {
      port = 8089; binary = "upstream";
      modelFile = "/home/nixos/models/Llama-xLAM-2-8B-fc-r-Q4_K_M.gguf";
      threads = 6; ctxSize = 8192; batchSize = 512; ubatch = 512;
      gpuLayers = 99; moeFlags = "";
      fa = true; ctk = "q4_0"; ctv = "q4_0";
      # Tool-calling ONLY: excelente em function-call, MUDO em chat
      # (não serve p/ prosa). Papel: executor backend, nunca conversar.
      extraArgs = [ "--parallel" "1" "--jinja" ];
      memHigh = "5G"; memMax = "7G"; limitMemlock = false;
      wanted = false;
    };
    phi-mini = {
      port = 8086; binary = "upstream";
      modelFile = "/home/nixos/models/Phi-4-mini-instruct-Q4_K_M.gguf";
      threads = 6; ctxSize = 32768; batchSize = 512; ubatch = 512;
      gpuLayers = 99; moeFlags = "";
      fa = true; ctk = "q4_0"; ctv = "q4_0";
      extraArgs = [ "--parallel" "1" "--jinja" ];
      memHigh = "4G"; memMax = "6G"; limitMemlock = false;
      wanted = false;
      # opencode provider (gerado em home.nix via mapAttrs):
      # id = modelFile (o server anuncia o path, sem --alias).
      opencode = { key = "local-phi-mini"; name = "Phi-4-mini Local"; context = 32768; output = 4096; };
    };
    gemma-4b = {
      port = 8087; binary = "upstream";
      modelFile = "/home/nixos/models/gemma-3-4b-it-Q4_K_M.gguf";
      # (19/10) fa off: com fa ON o prefill do gemma-3 (sliding window)
      # degrada p/ ~17ms/tok uniforme (59 t/s no PROMPT = decodificação
      # sequencial; medido: 3.4s p/ 200 tok). Sem fa: prefill batch
      # normal — gemma era 0.29s/item no benchmark i18n (canary).
      # ctx 8192 (era 32768): buffer não-FA escala com n_ctx; 8192 cabe
      # folgado (uso real: prompts de tradução <200 tok).
      # KV f16 (era q4_0): V cache quantizado EXIGE flash-attn (log do
      # server) — com fa off tem que ser f16.
      threads = 6; ctxSize = 8192; batchSize = 256; ubatch = 256;
      gpuLayers = 99; moeFlags = "";
      fa = false; ctk = "f16"; ctv = "f16";
      # Papel candidato: prosa/chat geral — NÃO medido ainda (bench cobre
      # bonsai+qwen; gemma entra na próxima rodada).
      extraArgs = [ "--parallel" "1" "--jinja" ];
      memHigh = "4G"; memMax = "6G"; limitMemlock = false;
      wanted = false;
      # opencode provider (gerado em home.nix via mapAttrs):
      # id = modelFile (o server anuncia o path, sem --alias).
      opencode = { key = "local-gemma-4b"; name = "Gemma-3 4B Local"; context = 32768; output = 4096; };
    };
    qwen30b-moe = {
      port = 8091; binary = "ik";
      modelFile = "/home/nixos/models/Qwen3-30B-A3B-Q4_K_M.gguf";
      # ctx 8192: classe MoE estourou compute buffers em 32k no irmão 35B
      # (medido 2x 03/10); 30B não testado → valor seguro, não especulativo.
      threads = 6; ctxSize = 8192; batchSize = 512; ubatch = 512;
      gpuLayers = 45; moeFlags = "--n-cpu-moe 35";
      fa = true; ctk = "q4_0"; ctv = "q4_0";
      extraArgs = [ "--parallel" "1" "--jinja" "--mlock" "--reasoning" "off" ];
      memHigh = "21G"; memMax = "23G"; limitMemlock = true;
      wanted = false;
    };
    uncensored-35b-q4kp = {
      port = 8093; binary = "ik";
      modelFile = "/home/nixos/models/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_P.gguf";
      threads = 6; ctxSize = 8192; batchSize = 512; ubatch = 512;
      gpuLayers = 45; moeFlags = "--n-cpu-moe 35";
      fa = true; ctk = "q4_0"; ctv = "q4_0";
      extraArgs = [ "--parallel" "1" "--jinja" "--mlock" "--reasoning" "off" ];
      memHigh = "22G"; memMax = "25G"; limitMemlock = true;
      wanted = false;
    };
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
  # ANTI-APAGAR (docs/models/MODEL-SAFETY.md): este fetch é content-addressed
  # (sha256) — o store pode ser GC'd e volta com rebuild; NUNCA `rm` pesos
  # sem checar inventário + lsof + dono. Recomendado Prism seria o Q2_0 g128
  # (2.18GB, lossless p/ ternário) — trocar de arquivo muda baseline (decisão dono).
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

  # --- Flux.1-schnell (geração de imagem) — stack stable-diffusion.cpp ---
  # DiT Q2_K (3.8GB, cabe na VRAM 6GB) + clip_l + t5xxl + VAE bf16.
  # Runtime: ~/projects/stable-diffusion.cpp/build-cuda/bin/sd-cli
  #   (build SD_CUDA sm_89, 04/10 — build-vk APOSENTADO: ggml-vulkan deu
  #   device-lost + 3 hard-freezes 03/10; CUDA estável).
  # Receita que funciona: auto-fit PURO + --max-vram CUDA0=5 (256px ~21s).
  # NUNCA --backend/--params-backend manuais (jogam p/ CPU em silêncio, 6min).
  # T5: fp16 p/ CPU (fp8 SEGFAULT em CPU — sem kernels fp8);
  #     fp8 p/ GPU (CUDA/Vulkan têm kernels fp8, metade da RAM).
  # VRAM 6GB: auto-fit coloca DiT na GPU, T5 fica em RAM.
  img-flux-schnell-q2 = mkModel {
    url = "https://huggingface.co/city96/FLUX.1-schnell-gguf/resolve/main/flux1-schnell-Q2_K.gguf";
    sha256 = "sha256-o4UBHKt0h9WgR4VEblm0Bf+2QvDehntMjzp6Cgd1mbA=";
  };

  img-clip-l = mkModel {
    url = "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/clip_l.safetensors";
    sha256 = "sha256-ZgxvWxq66dxJisLSHhNH0qvbDPbAwMhXbNeWSR2abN0=";
  };

  img-t5xxl-fp16 = mkModel {
    url = "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp16.safetensors";
    sha256 = "sha256-bkgLCfrgSactKoxfvMuNPpL+vrIzu+nf5yVpWKkWdjU=";
  };

  img-t5xxl-fp8 = mkModel {
    url = "https://huggingface.co/comfyanonymous/flux_text_encoders/resolve/main/t5xxl_fp8_e4m3fn.safetensors";
    sha256 = "sha256-fTMNpIFhV1QNa7eDi/Y6DwL1c/xIyk2N40uwy/1RTwk=";
  };

  img-flux-vae-bf16 = mkModel {
    url = "https://huggingface.co/Kijai/flux-fp8/resolve/main/flux-vae-bf16.safetensors";
    sha256 = "sha256-DAyKxJhQ1r0XQQfUABaF9PbIdnaKHITd51HyrtafRs4=";
  };

  # --- SigLIP base patch16-224 (match visual p/ reskin: sprite vanilla x donor) ---
  # Uso: transformers (karaok venv) — AutoModel + AutoImageProcessor, embed 224px,
  # cosine match. CPU ok (203M fp32). Registro estilo whisper (multi-file).
  img-siglip-base = {
    model = fetchurl {
      url = "https://huggingface.co/google/siglip-base-patch16-224/resolve/main/model.safetensors";
      sha256 = "158bpxkgwq813af6ncl1dwgjx41kynnc9bmjqxi6np85idimp39j";
    };
    config = fetchurl {
      url = "https://huggingface.co/google/siglip-base-patch16-224/resolve/main/config.json";
      sha256 = "1z4nr310bz3l3xbrf9ba0f3vbib1jqxk01129gfbfy15q42hfg3s";
    };
    preprocessor = fetchurl {
      url = "https://huggingface.co/google/siglip-base-patch16-224/resolve/main/preprocessor_config.json";
      sha256 = "0p2yaz0ybaa1c1p9cqyk61yja8qzk0z3r9z94x56fn7zs22kpj6g";
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
      # ctxSize 8192 VALIDADO 03/10 (não subir!): KV do MoE é minúsculo
      # (~11KB/tok), mas os compute buffers do -c 32768 estouraram a VRAM
      # compartilhada (6GB com 8083+nomic) — load falhou 2x. 8k é o teto
      # operacional colocalizado. Auditoria completa em /tmp/opencode/gguf_audit.json.
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
    # Auditoria GGUF 03/10 (/tmp/opencode/gguf_audit.json): arquivo local
    # tem 36 layers, 8 KV heads, head_dim 80 → KV real 25.9KB/tok
    # (16k = 0.42GB, não 1GB). Nativo 40960: 32768 caberia solo, mas
    # 16384 está CORRETO p/ deploy colocalizado (divide 6GB com MoE+nomic).
    # Não subir sem redesenhar o budget compartilhado.
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
    # (26/10) O DEFAULT do sistema: Qwen3.5-4B-MTP + LoRA micro-turn.
    # Espelha o directServer `uncensored-4b` (:8092, binário stock) — o
    # LoRA SÓ funciona no stock (o ik carrega e não aplica: mismatch de
    # nomes). MTP = NextN real (+24% TG medido). fa off (LoRA × fa são
    # incompatíveis) → KV f16.
    mtp-lora = profiles.qwen-fast // {
      modelFile = "/home/nixos/models/Qwen3.5-4B-MTP-Q4_K_M.gguf";
      kvCache = "-fa off -ctk f16 -ctv f16";
      ctxSize = 20480;
      batchSize = 256;
      ubatch = 256;
      # (26/10) O alias aqui espelha `directServers.uncensored-4b.alias`
      # (fonte única = o campo `alias`; o gerador da unit injeta a flag).
      extraArgs = [
        "--parallel" "1"
        "--jinja"
        "--reasoning" "off"
        "--spec-type" "draft-mtp"
        "--lora" "/home/nixos/models/loras/microturn-4b/microturn-4b-lora.gguf"
        "--lora-init-without-apply"
        "--alias" "jarvis-mtp-lora"
      ];
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
    # (26/10, dono) DEFAULT = Qwen3.5-4B-MTP **COM O LoRA** (:8092).
    # Antes: bonsai (prism :8080) — EN-only, sem PT, e o classificador de
    # turno do duplex (RESPOND/WAIT/SILENCE/BARGE) é o LoRA. Medido ao
    # vivo: LoRA ON 4/4 classes; LoRA OFF = base "Thinking Pro", não
    # classifica. Serve = false: o servidor é o DIRECT (:8092, stock) —
    # gerar um grupo de preset aqui duplicaria a unit na mesma porta.
    default = "jarvis-mtp-lora";
    # SAMPLING — ÚNICA FONTE dos defaults de geração por modelo. O Python
    # (model_registry.sampling_for → llm._resolve_temperature) lê daqui via
    # registryJson; NADA de temperature hardcoded no .py. Ordem de vitória:
    # explicit (caller) > JARVIS_LLM_TEMPERATURE > sampling.temperature.
    # Harness/agente passa explicit 0.0 p/ tools — determinismo preservado.
    # Fontes vendor (25/09/2026):
    # - Prism 1-bit 8B card: temp 0.5 (range 0.5-0.7), top_k 20, top_p 0.9.
    # - Prism ternary-27B card (thinking): temp 0.7, top_p 0.95, top_k 20.
    # - Qwen3 base: thinking 0.6/0.95/20/0; non-thinking 0.7/0.8/20/0.
    # - Qwen3.5/3.6: thinking-geral 1.0/0.95/20/0/presence 1.5; thinking-code
    #   0.6/presence 0.0; instruct-geral 0.7/0.8/20/0/presence 1.5.
    # Residência simultânea máxima (VRAM 6GB: 1 modelo por vez).
    maxResident = 1;
    # Binário CORRETO por modelo (docs/models/BINARIES.md — D2/D5: binário
    # errado invalida o veredito). O router NÃO escolhe binário por request:
    # llama-cpp.nix gera UM serviço por grupo (porta = endpoints.${binary}).
    endpoints = { prism = 8080; upstream = 8083; ik = 8084; };
    models = {
      # (26/10) DEFAULT do sistema — Qwen3.5-4B-MTP + LoRA micro-turn,
      # servido pelo directServer :8092 (binário stock). PT-BR de verdade
      # (o bonsai é EN-only) e é o único que tem o classificador de turno.
      # serve={false} → não gera grupo de preset (o service é o direct).
      jarvis-mtp-lora = {
        profile = "mtp-lora";
        model = "mtp-lora";
        ctx = 20480;
        tier = "fast";
        capabilities = ["general" "coding" "tools" "pt" "uncensored" "lora"];
        guidance = "DEFAULT: PT-BR + classificador de turno (LoRA RESPOND/WAIT/SILENCE/BARGE); 70t/s com MTP (+24%)";
        params_b = 4;
        vram_mb = 4474;
        needsWrapper = null;
        binary = "stock";
        endpoint = 8092;
        serve = { host = false; vm = false; };
        # Qwen3.5 instruct-geral (vendor; mesmo do jarvis-fast).
        sampling = { temperature = 0.7; top_p = 0.8; top_k = 20; min_p = 0.0;
                     presence_penalty = 1.5; repetition_penalty = 1.0; };
      };
      bonsai = {
        profile = "bonsai";
        ctx = 49152;
        tier = "speed";
        capabilities = ["general" "coding" "tools" "en"];
        # GUIDANCE p/ IAs (lido via registryJson.raw — select_model NÃO lê,
        # então isto NÃO muda roteamento; muda a ESCOLHA de quem lê):
        # bench 07/10 (temp 0.0): TTFT 0.033s, 72/73 t/s; PT-BR dif 6/10
        # (falhas: ecoa imperativo curto em EN, perde acento, troca nome
        # próprio, erra sequência); logic 3/4, code 4/4. SEM "pt" (dono
        # 07/10: ruim em PT, é EN). PT-BR → tier fast. Ver
        # docs/benchmarks/BENCHMARK-MATRIX.md linha "Tier speed".
        guidance = "speed/code/EN first; NEVER PT-BR (no pt capability); PT-BR goes to fast tier";
        params_b = 8;
        vram_mb = 2400;
        # Prism fork exigido (Q2_0 g64 fora do upstream).
        needsWrapper = "llama-prism-wrapper";
        binary = "prism";
        endpoint = 8080;
        serve = { host = true; vm = true; };
        # Prism recomenda 0.5 p/ Bonsai (não é regra global — ver Qwen abaixo).
        sampling = { temperature = 0.5; top_p = 0.9; top_k = 20; min_p = 0.0;
                     presence_penalty = 0.0; repetition_penalty = 1.0; };
      };
      jarvis-fast = {
        profile = "qwen-fast";
        ctx = 49152;
        profileVm = "vm";
        tier = "fast";
        capabilities = ["general" "coding" "tools" "pt"];
        guidance = "coder/tool-calling default; PT-BR goes here (bonsai has no pt); bench qwen4bmtp-0710 lands 08/10";
        params_b = 4;
        vram_mb = 2600;
        needsWrapper = null;
        binary = "upstream";
        endpoint = 8083;
        serve = { host = true; vm = true; };
        # Qwen3 non-thinking/instruct-geral (vendor).
        sampling = { temperature = 0.7; top_p = 0.8; top_k = 20; min_p = 0.0;
                     presence_penalty = 1.5; repetition_penalty = 1.0; };
      };
      jarvis-strong = {
        profile = "chat";
        ctx = 32768;
        tier = "reasoning";
        capabilities = ["general" "coding" "tools" "reasoning" "analysis" "vision" "pt"];
        guidance = "last local tier before API cascade; reasoning + vision (mmproj CPU); heavy (RAM experts), use for hard tasks only";
        params_b = 35;
        vram_mb = 4600;
        needsWrapper = null;
        binary = "ik";
        endpoint = 8084;
        serve = { host = true; vm = false; };
        # Herdado do profile chat: mmproj na CPU (861MB VRAM) + visão dinâmica.
        iniExtra = ["no-mmproj-offload = true" "image-min-tokens = 1024"];
        # Qwen3.5 thinking-geral (vendor). Agente usa explicit 0.0 em tools.
        sampling = { temperature = 1.0; top_p = 0.95; top_k = 20; min_p = 0.0;
                     presence_penalty = 1.5; repetition_penalty = 1.0; };
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
        # Qwen3.5 instruct-geral (vendor; mesmo do jarvis-fast).
        sampling = { temperature = 0.7; top_p = 0.8; top_k = 20; min_p = 0.0;
                     presence_penalty = 1.5; repetition_penalty = 1.0; };
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
        # Qwen3.6 thinking-geral (vendor). Agente usa explicit 0.0 em tools.
        sampling = { temperature = 1.0; top_p = 0.95; top_k = 20; min_p = 0.0;
                     presence_penalty = 1.5; repetition_penalty = 1.0; };
      };
    };
  };

  # JSON derivado (builtins.toJSON puro — sem derivação): llama-cpp.nix
  # gera o preset INI e /etc/jarvis/model-registry.json daqui.
  registryJson = builtins.toJSON routing;

  # (26/10) LAYA — decision model (ModernBERT-large 421M, Apache-2.0) p/
  # classificar DIFICULDADE do prompt (simple/moderate/hard) e rotear.
  # FINE-TUNED (Kaggle T4 v7): 95.6% acc, hard 100%, +36.8% vs base.
  # Medido no mesmo conjunto (26/10): ft 5/6 vs base 3/6 — o ft acerta o
  # "hard" que o base degradava p/ "moderate" (justamente o caso que
  # dispara escalonamento p/ 35B/cloud). O base fica em laya-onnx/.
  # O Python lê LAYA_MODEL_DIR (default = este path).
  layaModelDir = "/home/nixos/models/laya-ft";
}
