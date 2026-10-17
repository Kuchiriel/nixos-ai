# VOZ FULL-DUPLEX JARVIS — mapa da missão (17/10, direto do dono)

> Meta: modo voz do JARVIS com wakeword "hey jarvis" (single-shot),
> "hey jarvis acordar/dormir" (escuta contínua), conversa fluida
> full-duplex, tool calling forte. Pesquisa ANTES de implementar
> (âncora de pesquisa do dono). **Regra de ouro (dono): "antes de
> condenar 'não cabe', TESTAR".**

## Veredito de arquitetura (pesquisa 17/10)

**Rota vencedora: CASCADE + MICRO-TURNS** (DuplexCascade / LoRA codacus)
— NÃO speech-native (Moshi/Qwen-Omni):

- Cascade mantém o cérebro 35B → **tool calling, RAG, evals "de graça"**
  (o vídeo de arquitetura: cascade = "the production default"). O JARVIS
  SEM ferramentas não é JARVIS.
- Speech-native: Moshi 7B é EN-only, sem tool calling; Qwen3-Omni 30B =
  60GB bf16, "a 12GB card can't hold it" (transcript). O blog do 600M
  Moshi: o canal de áudio NÃO converge, o garble mora nos codebooks
  finos — projeto do autor PAUSADO. Speech-native = caminho morto p/ 6GB.
- Full-duplex NO cascade via **protocolo micro-turn**: tick 0.6s, ASR
  streaming alimenta "heard:" fragments, o LLM responde ≤3 palavras ou
  `<listen>` (protocolo byte-a-byte no card do LoRA + em
  ~/Books/papers/duplexcascade-2603.09180.md).

## PROVADO HOJE (testes reais, não pressuposição)

1. **35B + LoRA funciona na nossa stack** (ik_llama.cpp build local,
   `build/bin/llama-server`): suporta `--lora` GGUF (50 tensores, 14.6MB),
   qwen35moe carrega, `/completion` com `n_probs` ok (formato ik:
   `probs:[{tok_str,prob}]`, sem ids → adaptador
   /tmp/opencode/microturn-test/microturn_client_ik.py tokenize o ban).
2. **LATÊNCIA RESOLVIDA (binário ik atualizado 17/10 + quant UD canônico)**:
   merge origin/main (02/10→17/10: traz `Implement moe cache`, fixes de
   prompt-cache resume p/ SWA, `--prefetch-experts`, string-ban p/
   recorrentes) + rebuild → **mediana 496ms/tick, 15/18 dentro do budget
   600ms** (antes: 1880ms). Os 2 outliers = re-prefill completo pós
   invalidação SWA ("forcing full prompt re-processing... likely due to
   SWA", issue conhecida ggml-org/llama.cpp#13194). **DUPLEX CABE NA 6GB
   HOJE.** Rebuild exigiu `-mavx2 -mfma -mf16c` explícitos: o wrapper cc
   do NixOS bloqueia -march=native (NIX_ENFORCE_NO_NATIVE) e os helpers
   SIMD novos do ik têm bug: o galho SSE2 do ladder ISA não define
   `ggml_vec_simd_sigmoid_f32` (upstream bug p/ builds sem AVX2).
3. **BUG CRÍTICO DESCOBERTO: o ik NÃO APLICA o LoRA** (no-op silencioso).
   Com vs sem `--lora`: outputs e P(listen) IDÊNTICOS (1.00 em tudo,
   nunca fala — sintoma exato de base-model "over-listening" que o card
   descreve). Causa: mismatch de nomes — o LoRA mira
   `blk.36.attn_qkv/attn_gate/ffn_*_shexp` (naming stock); o qwen35moe do
   ik nomeia diferente → tensores carregam ("loaded 50 tensors") mas o
   match na aplicação falha em silêncio. **A vitória de latência do ik
   é do BASE model** — o comportamento duplex (falar na hora certa)
   precisa de binário que aplique: stock llama.cpp (build-stock em
   andamento, v0.7.0 tem qwen35moe ✓) ou fix no ik (reportar upstream).
4. **`--n-cpu-moe` NÃO põe experts na GPU**: buffer "CUDA_Host" de
   18.9GB = experts PINNED em RAM (não em VRAM) — por isso 40/44/48
   mudaram nada nos números. O ik decide sozinho; a única coisa na GPU
   = atenção+shared (~1.3GB) + compute (~0.5GB). O ganho real de
   latência veio dos fixes de cache, não de placement.
5. **GPU bloqueada durante sessões**: router bonsai residente (0 MiB
   livre; build CUDA reserva 887MB de buffer compute mesmo com -ngl 0 →
   work-around de teste: `CUDA_VISIBLE_DEVICES=""`). Janela AFK com
   router parado FUNCIONOU (dono autorizou 17/10, ~2h de testes).
6. **★ PROVA FINAL (17/10 ~17:50): stock llama.cpp v0.7.0 + UD-Q4_K_M +
   LoRA = DUPLEX COMPLETO NA 6GB, DENTRO DO BUDGET**. Com o binário stock
   (build-stock/, sm_89-only, CUDA include-path do cuda-merged-12.9,
   flags -mavx2 -mfma -mf16c) o LoRA APLICA de verdade: o modelo escuta
   o chatter (P 0.94→0.57), sente a urgência e **INTERROMPE na hora
   exata** ("Stop! Do not / mix those two together. That creates / a
   deadly gas. / Please stop.") e volta a `<listen>` — comportamento
   canônico do card. **18 ticks em 10.4s = ~576ms/tick, dentro do
   budget 600ms** (-ngl 99 --n-cpu-moe 44, atenção na GPU, experts
   pinned na RAM). O cliente é o canônico (stock usa top_logprobs
   nativo; adaptador ik só p/ o fork).
   - Lições do build stock: `-DCMAKE_CUDA_ARCHITECTURES=89` = 14× mais
     rápido p/ compilar; portas: 8093 livre, 8094 = docker-proxy canary
     (usar 8095+); `setsid` no launch senão o fim do tool-call mata o
     ninja (lição dupla, 2 builds perdidos).

## Design do pipeline (alvo)

```
mic 24kHz ──▶ wakeword daemon (calibrar c/ voz do dono; "raramente dispara")
   │ "hey jarvis <cmd>"  ──▶ single-shot: stt (whisper) → rota normal 8080
   │ "hey jarvis acordar" ──▶ DUPLEX ON:
   ▼
ASR streaming por tick (0.6s fragments, sem VAD)   ← PENDÊNCIA: escolher
   │                                               (kyutai DSM-ASR p/ PT? ver abaixo)
   ▼
llama-server 35B+LoRA (tier "jarvis-duplex", porta própria)
   protocolo micro-turn (SYSTEM byte-a-byte, `<listen>`/`<no voice>`,
   regra speak-or-listen: P(`<`)≥0.3 = escuta; senão BAN com logit_bias)
   ▼
fragments ≤3 palavras ──▶ TTS streaming (kokoro/edge; truques do
   vídeo xbedfuqYQYA: fila de 2 sentenças, sintetiza enquanto toca)
   ▼
TOOL CALLS: fragmento com intenção → **Cactus Needle 3 = System-1**
   (grammar-constrained JSON em ms na CPU; 29–121M params; já clonado
   em ~/projects/cactus-needle, pesos needle3.cact JÁ EM CACHE
   ~/.cache/cactus-needle/v3 — falta só whistle.cact p/ STT e o venv)
   → confiança alta = executa direto (bridge JARVIS MCP);
   confiança baixa = escala pro 35B (System-2) decidir.
```

- DuplexCascade paper: sweep de tick → pico acurácia 1.2s, latência
  monotônica; 0.6s = trade-off escolhido. Bench: Full-Duplex-Bench 0.858
  ( > Gemini Live 0.778).
- ik tem `--lora-init-without-apply` + `POST /lora-adapters` → **o server
  duplex pode ligar/desligar o adapter EM RUNTIME** (candidato a evoluir
  o router: tier "jarvis-duplex" = 35B com LoRA hot-toggle).
- ASR/PT: Whistle (CN) NÃO tem PT (en de fr es it nl pl). Kyutai DSM-ASR
  (moshi-server, msgpack WS, chunks 80ms) — verificar suporte PT;
  fallback: whisper streaming chunked (o que a casa já tem).

## Pendências (ordem)

1. ~~Janela GPU~~ FEITO 17/10: duplex completo comprovado (ver item 6).
2. ~~Baixar UD-Q4_K_M canônico~~ FEITO (21.1GB em ~/models): é o quant
   GABARITO — usar este no modo duplex.
3. **IK upstream bug a reportar**: --lora no-op silencioso com qwen35moe
   (mismatch de nomes: LoRA mira attn_qkv/attn_gate/shexp; carrega 50
   tensores, aplica 0). Enquanto isso: modo duplex = llama.cpp stock
   (build-stock/). O ik continua o binário do ROUTER normal.
4. Transcript do vídeo-chave (shJLycXjhVY — 429 do YT; insistir) — o dono
   diz que explica o ganho em longas sessões (cache append-only já
   entendido; pode haver mais).
5. Wakeword: calibrar "hey jarvis" com a voz do dono (ww_scorer.py;
   histórico: VAD ok, modelo raramente dispara). Modos single-shot vs
   acordar/dormir no daemon.
6. ASR streaming PT por tick — decidir (kyutai DSM-ASR vs whisper-chunked;
   Whistle/CN não tem PT).
7. **Nosso LoRA** (o dono: "tem que por um lora pra ficar bom"): dataset
   micro-turn com tool calls JARVIS + PT-BR (semeado do dataset/ do
   codacus + gerar com o 35B), treino pequeno (card: rank 32, camadas
   36–39, 3h em 2×3060; escalar via kaggle-escalate se preciso). Treinar
   sobre o UD-Q4_K_M (o gabarito comprovado).
8. Harness de eval (o dono: "melhoradas no harness"): bateria do vídeo
   de arquitetura — P99 latência, interrupções/backchannel (FDBench-3
   style), TimeSpeak/CueSpeak, guardas de inteligência (IFEval) +
   regressão: o demo dos chemicals como smoke-test permanente.

## Fontes (indexadas)

- ~/Books/papers/duplexcascade-2603.09180.md (paper destilado 17/10)
- ~/Books/papers/arxiv-2609.31948-duplex-mpe.md (benchmark multi-party)
- Card do LoRA: HF codacus/Qwen3.6-35B-A3B-MicroTurn-Duplex-LoRA
  (protocolo byte-a-byte + regra do ban + dataset/)
- LoRA baixado: ~/models/loras/microturn-duplex/ (gguf 14.6MB + client ref)
- Transcripts Codacus: ~/Books/codacus-transcripts/ (arquitetura de voz,
  whisper→moshi, GPT-Live; FINDINGS.md)
- "RWM"/"moshi rwm 7b": NÃO EXISTE publicamente (HF global, blog Kyutai,
  GitHub org, transcripts — zero hits). Perguntar ao dono onde viu.
