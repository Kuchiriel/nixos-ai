# MATRIZ DE MODELOS — quem faz o quê (15/11, medido + pesquisa)

> Base: o que a casa **MEDIU** (VRAM, porta, 500, timeout, latência) + o que a
> **pesquisa** diz (benchmarks públicos, nov/2026) + a receita do transcript
> (Codacus): *"A 4B planner with one expert handles **short jobs with a clear
> answer**. For **long jobs**, run the biggest single model your card can hold.
> And **give your team search** because facts don't fit in a small model."*

## A regra-mãe (do transcript, medida lá)

1. **O planejador é o elo fraco** — e ele precisa de **habilidade geral**
   primeiro: *"a model needs a certain level of general ability first; after
   that, specializing starts to make sense"*. Medido lá: 35B planner + T-Max
   passou **2 de 4** checks; o melhor setup 4B passou **<1**.
2. **Job curto e com resposta verificável → especialista pequeno.**
   **Job longo/multi-etapa → o maior modelo que a placa aguenta.**
3. **Peso-editing não resolve hábito espalhado**: o autor patchou o modelo
   (26% → 17% de tocar produção) e no teste real (job inteiro, 5×) deu
   **0 passes vs 1** do não-patcheado. → **consertar o plano, não o neurônio.**
4. **Dá search ao time** (fatos não cabem em modelo pequeno) → RAG + corpus
   offline no prompt do especialista.

## LOCAIS (o que a casa tem em disco)

| modelo | arquivo | VRAM | ctx | medido HOJE aqui | prós (pesquisa) | contras (pesquisa + casa) | **PAPEL** |
|---|---|---|---|---|---|---|---|
| **Qwen3.5-4B-MTP** (jarvis-mtp-lora) | 2,79 GB | **3.874 MiB** | 12.288 | ✅ responde (3 s); MTP = multi-token prediction (draft); é o `default` do registry | tool-calling decente (TIR-Bench 18-45); MTP dá +16-23% tok/s; **PT-BR** (caps do registry) | ctx curto (12k); Reddit: *"operationally unusable"* p/ tarefa pesada; **derruba o patcher** em 4k tokens | **executor local de job curto** (default da frota) |
| **Ternary-Bonsai-8B** (bonsai, :8080) | 2,49 GB (Q2_0_g64) | 2,3 GB p/ carregar | 49.152 | ⚠️ **500** com o MTP residente (VRAM: 102 MiB livres); ✅ funciona **depois do swap** | capacidade por byte (2,13 bits/peso); general knowledge 100% no set deles; coding 92,9-100% | **15 tok/s vs 36,7 do Qwen3.5-4B** (2,4× mais lento); multi-step fraco (55,9-71,4%); BFCL 73,9 vs 81 do Qwen3 8B; Reddit: *"muito mais burro que o Gemma-4-E2B"*; **em PT-BR erra muito** (dono, medido) e o legado deu **8 FAIL/10** | **só como baseline de comparação** (não para produção) |
| **DeepSeek-R1-Distill-Qwen-7B** | 4,68 GB | 4,7 GB | 16k (jarvis-fast :8083) | não medido hoje | bom equilíbrio; cabe folgado | não é o melhor 7B do mercado (o DeepSeek V4.1 Flash é outro) | reserva p/ quando o MTP cair |
| **gemma-3-4b-it** | 2,49 GB | 2,5 GB | 256k | não medido | **multimodal pequeno** (visão); único 4B com visão | sem tool-calling nativo no path llama.cpp (0/35 free, 35/35 constrained) | **guarda de tela/visão** (se robotizar) |
| **Phi-4-mini** | 2,49 GB | 2,5 GB | — | não medido | barato, bom follow |_velho_ | — |
| **Qwen3-4B** | 2,50 GB | 2,5 GB | 32k | não medido | o 4B "pode rivalizar o Qwen2.5-72B" (Qwen3 blog) | inferior ao 3.5 | — |
| **Qwen3.5-4B-Uncensored-HauhauCS** | 2,71 GB | 2,7 GB | — | não medido | **baixa recusa** (redteam precisa) | sem MTP | **redteam/guard de recusa** |
| **Qwen3.6-35B-A3B-Uncensored** | 21,2 GB | ⚠️ não cabe (6 GB) | 262k (API) | ❌ 35B local não cabe; via API 0,011/0,101 $/M | MoE 35B, **35 B ativos**, $0,011/M (o mais barato da lista API) | local = RAM/offload (lento) | **planejador via API** (o melhor custo-benefício do catálogo) |
| **Nemotron-Labs-Dory1.0-4B** | 3,67 GB | 3,7 GB | — | não medido | — | — | reserva |
| **whisper large-v3-turbo q5** | — | **934 MiB** | — | ✅ :8097 vivo | STT PT-BR (`-l pt`) | come VRAM sempre (tira 934 MiB dos 6 GB) | **transcrição de áudio** (mover pra CPU liberaria VRAM) |
| **nomic-embed-text-v2-moe** | — | 446 MiB | 4.096 | ✅ :8081 vivo | embeddings | come VRAM | **vetores do RAG** |

## NOVOS (do transcript) — o que cabe nos 6 GB

| modelo | GGUF | tamanho | cabe? | prós | contras | papel |
|---|---|---|---|---|---|---|
| **TMax-4B** (AI2, arXiv 2606.23321) | ✅ registrado no `models.nix` | **2,71 GB** | ✅ | **especialista de terminal**: 27% do terminal-bench (o GPT-5.5 faz 85%); bate o Qwen 9B em uso de terminal | 27% é baixo: sozinho não fecha job longo | **especialista de terminal** (job com resposta verificável: testes) |
| **VibeThinker-1.5B** (WeiboAI) | ✅ registrado | **1,12 GB** | ✅ folgado | matemática; o video mediu o Vibe Thinker acima do Gemini 3 Pro em math | 1,5B: só tarefa curta | **math/checagem numérica** |
| **TeleOCR** (XingChen-AGI) | GGUF existe (`cstr/TeleOCR-GGUF`) | 1,2-1,9 GB | ⚠️ VLM | documento → texto, acima do Gemini 3 Pro (medido no video) | **sem mmproj** → não roda no llama.cpp ainda | **catalogado** (materializar quando houver mmproj) |
| **Carbon-X** (HuggingFaceBio) | ❌ só safetensors | **29,6 GB** | ❌ | DNA a ~1 ponto do GPT-6.1 SOL | não cabe, sem GGUF oficial | **catálogo** |

## API (o que a casa tem no catálogo, medido em `/api/models`)

| modelo | ctx | out | preço (OpenRouter) | medido na pesquisa | prós | contras | **PAPEL** |
|---|---|---|---|---|---|---|---|
| **deepseek-v4.1-flash** | 1.000.000 | 256.000 | — | **73,2%** em coding agentic real (bito), MIT; Terminal-Bench 42,3; $3,28/sessão de 20 turnos | **o melhor custo-benefício para PLANEJAR/EXECUTAR job longo** | não é local (latência) | **planejador de job longo** |
| **minimax-m3.1-flash** (NIM) | 1.048.576 | 65.536 | $0,80/$1,60 (ablit.) | 66,7% coding; **Automation-Bench 62,8** (vence o Opus 5: 50,3); HLE s/ tools 43,4; ~1M ctx | **o melhor em automação/ferramentas**; é o modelo da casa | licença comunitária | **executor de automação + o modelo do dono** |
| **glm-5.3-flash** | 1.000.000 | 131.072 | **$0,2/$0,7** | 66,2% coding; **CyberGym 84,5 (lidera)**; MIT | **o mais barato**; bom em multi-step | 5+ tool calls → Kimi é melhor | **volume/classificação/log** |
| **kimi-k2.6 / K3** | 262k-1M | 65.536 | K3.1 Pro: **222% mais caro** que o Opus | Arena #1 em frontend; melhor em multi-doc | melhor contexto longo p/ documentos | caríssimo; Terminal-Bench só 12,6 | **leitura de documento longo** (se o custo importar menos) |
| **nemotron-3-ultra-550b** | 1.048.576 | 32.768 | $0,50/$2,20 | Coding Index 49,3; Agentic 20,1; 129 tok/s | o **maior capacidade geral** do catálogo | 45× mais caro que o Qwen3.6-35B | **planejador quando o texto é difícil** |
| **nemotron-3.5-lightning-30b** | 1.000.000 | 32.768 | — | tier *fast* | rápido, 1M ctx | qualidade média | **fast tier** (titulo/resumo) |
| **llama-guard-4-12b** / **nemotron-safety-guard-8b** / **nemotron-3.5-content-safety** | 128-163k | 4-8k | — | tier *guard* | **guarda de segurança** (filtro de entrada/saída) | não razonam | **guard** |
| **gpt-oss-120b** (groq/cloudflare) | 131.072 | 8.000 | — | MMLU-Pro 90; GPQA 80,9 | rápido no groq | 8k de output | raciocínio barato |
| **gpt-oss-20b** (groq/nvidia) | 131.072 | 4-8k | — | tier *fast* | rápido | qualidade menor | tier fast |
| **muse-glimmer-30b** | 131.072 | 131.072 | — | out enorme | output gigante | — | geração longa |
| **nemotron-3-nano-omni-30b** | 256.000 | 65.536 | — | multimodal + reasoning | visão + texto | — | visão que raciocina |
| **gemma-4-31b** / **diffusiongemma-26b** | 250-256k | 16k | — | multimodal | visão | — | visão |

## A REGRA DE DECISÃO (o que o código deve fazer)

```
job curto (1-3 passos, resposta verificável)?
   -> local: Qwen3.5-4B-MTP (se a VRAM estiver livre)  |  TMax-4B se o job e terminal
job longo/multi-etapa?
   -> API: deepseek-v4.1-flash (planejar/executar)  |  minimax-m3.1-flash (automacao)
   -> se o plano exigir >capacidade: nemotron-3-ultra
volume (classificar/log/resumir em massa)?
   -> glm-5.3-flash ($0,2/M)  |  nemotron-3.5-lightning (tier fast)
documento longo?
   -> kimi-k2.6 (caro, mas contexto)  |  RAG + corpus offline (de graça)
segurança (entrada/saída)?
   -> llama-guard / nemotron-safety-guard
visão?
   -> nemotron-3-nano-omni / gemma-4-31b (API)  |  gemma-3-4b local (sem tool-calling)
```

### E quando a VRAM está ocupada (a receita do transcript aplicada)

1. Se o **local desejado não está residente** e a VRAM está cheia →
   **vai para a API do mesmo tier** (não briga pela VRAM).
2. Se a VRAM está **livre (idle)** → **swap** (`scripts/llama-swap.sh`) e sobe o
   local: `llama-swap.sh --free` (mata o MTP) → o router carrega o pedido →
   `llama-swap.sh --start-mtp` (devolve o MTP com a cmdline medida).
   **Medido**: MTP 3.874 MiB + embeddings 446 + whisper 934 = 5.254 de 6.141 →
   **102 MiB livres** → qualquer 2ª geração não cabe.
3. O **planner sempre forte**: quem planeja tem de ter modelo grande
   (API), mesmo que o executor seja local pequeno.
4. **Search sempre**: o especialista recebe RAG (`jarvis_rag_search`) + corpus
   offline, porque "facts don't fit in a small model".

### E o spawn (o sistema tem de conseguir Spawnar por demanda)

O spawn já existe (`scripts/agent-spawn.py`): classifica a task → persona +
**MBTI** → escolhe modelo por **tier + cooldown** → monta o prompt (agora com
o **PLAYBOOK DO PAPEL** portado do legado) → devolve sessão/modelo/persona.
Falta fechar: **handover** no mesmo formato (quem termina enfileira a próxima
com o pedido original + playbook) — está na fila do port.
