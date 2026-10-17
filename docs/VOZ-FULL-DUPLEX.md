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
2. **Protocolo 18/18 ticks correto no quant HauhauCS-Aggressive**:
   `P(listen)` 0.98–1.00 durante todo o chatter. MAS o modelo **nunca
   interrompeu** (no demo canônico ele deve falar "Do not mix those
   chemicals..." no silêncio) → o lado speak do LoRA degradou nesse quant
   — teste limpo pede o quant de treino: `unsloth/Qwen3.6-35B-A3B-UD-Q4_K_M`
   (o card: "other quantisations are untested").
3. **Latência CPU-only: mediana 63.8s/tick** (mmap preguiçoso, 6 threads,
   GPU invisível) → **0/18 dentro do budget 600ms**. CPU puro = morto
   p/ tempo real. GPU é obrigatória p/ o tick (o vídeo do codacus: 230ms
   mediana no 3060 12GB com `--n-cpu-moe 24`; nosso alvo 6GB = mais
   experts na RAM, medir).
4. **GPU bloqueada hoje p/ teste**: router bonsai residente (0 MiB livre;
   o ik pediu 887MB de buffer compute e falhou `cudaMalloc OOM` mesmo
   com -ngl 0 — o build CUDA sempre reserva buffer; work-around do teste
   foi `CUDA_VISIBLE_DEVICES=""`). **O teste decisivo (GPU) precisa de
   janela com o router PARADO** (regra: nunca restartar llama-server em
   sessão ativa → combinar janela AFK com o dono).

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

1. **Janela GPU** (router parado, dono AFK): teste 35B+LoRA na 6GB —
   `-ngl <coucou> --n-cpu-moe <24+>` medir ms/tick. Veredito real.
2. Baixar `unsloth/Qwen3.6-35B-A3B-UD-Q4_K_M.gguf` (~20GB) e re-testar
   o demo (interrupção fala?) — se o Aggressive degradou, o canônico é o
   gabarito. (download pesado: regras de recurso!)
3. Transcript do vídeo-chave (shJLycXjhVY — 429 do YT; insistir) — o dono
   diz que explica o ganho em longas sessões (cache de prompt append-only
   já entendido; pode haver mais).
4. Wakeword: calibrar "hey jarvis" com a voz do dono (ww_scorer.py;
   histórico: VAD ok, modelo raramente dispara). Modos single-shot vs
   acordar/dormir no daemon.
5. ASR streaming PT por tick — decidir (kyutai vs whisper-chunked).
6. **Nosso LoRA** (o dono: "tem que por um lora pra ficar bom"): dataset
   micro-turn com tool calls JARVIS + PT-BR (semeado do dataset/ do
   codacus + gerar com o 35B), treino pequeno (o card: rank 32, só
   camadas 36–39, 3h em 2×3060 → kita tem 6GB 1×; escalar via
   kaggle-escalate skill se preciso).
7. Harness de eval (o dono: "melhoradas no harness"): bateria do vídeo
   de arquitetura — P99 latência, interrupções/backchannel (FDBench-3
   style), TimeSpeak/CueSpeak, guardas de inteligência (IFEval).

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
