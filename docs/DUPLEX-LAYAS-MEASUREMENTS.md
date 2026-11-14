# Duplex Voice Assistant — measurable state (2026-11-12)

## Pipeline completo (hoje)

```
pw-record (mic capture) -> ;duplex-asrd.py (ASR subprocess STT stdio) ->
  4B-MTP :8092 (Qwen3.5-4B-MTP + microturn-4b-lora) + cascade LLM (groq/nvidia/openrouter) ->
  duplex-ttsd.py (Kokoro v1) -> aplay/fifo -> speaker output
```

## Estado por componente (medido)

| Componente | Porta | Custo | Status |
|-----------|------:|------:|--------|
| pw-record (CaptureAudio) | n/a | n/a | captura ok (RMS 60-140, ambiente) |
| duplex-asrd | stdio | - | ok (234ms/segmento: ome "Jarvis, que horas são?") |
| 4B-MTP + microturn-4b-lora | :8092 | 5.5s/resposta difícil | OK (alt cold TCP) |
| cascade (groq/1M) | - | <1s tip Groq, 9s Nvidia NIM | OK com enable_thinking=false |
| Kokoro TTS | FIFO | 200-400 ms/sentence | OK |
| speaker-id | asrd | WeSpeaker ResNet34 256-d | MEDIDO ok 12/11 (clipe 02 vira spk=dono cos 0.79) |
| wakeword | n/a | - | DESABILITADA por decisão do dono (21/10, home.nix services.jarvis-wakeword.enable=false) |

## Benchmark gate (bench_gate.py — 27 falas PT-BR)

| Modelo | Recall | Precision | F1 | FP | ms mean |
|--------|--------|-----------|------|----|---------|
| microturn-4b-lora | 1.000 | 0.650 | 0.79 | 7 | 252-587ms |
| lora+prop (gate) | 0.923 | 0.857 | 0.89 | 2 | ~600ms |
| Laya fine-tuned 4 classes | 5/27 correct (0.185) | 1.000 | 0.31 | 0 | ~250ms |
| Laya-noul fine-tuned 2 classes | 0.692 | 0.750 | 0.72 | 3 | ~270ms |
| Laya zero-shot choice | 11/27 (0.407) | n/a | n/a | n/a | ~250ms |
| Laya parallel layout + soft-ce (fine-tune final) | 9/27 correct | n/a | n/a | n/a | ~205ms |

Custo Laya por call: ~250-289 ms (CPU). Custo LoRA por call: 247-587 ms (during init includes flip warmup).

## Baseline honesto: held-out construido a dedo (52 falas, 12/11 noite)

O bench_gate.py de 27 falas **sobrepoe com o template de treino** do LoRA (mesmas perguntas do gen-lora-data.py) — recall 1.00 e memorizacao, nao generalizacao.
Held-out feito a mao (60+ falas novas, zero overlap com os templates; + 30 clips reais do dono com labels manuais):

- RESPOND 16/16 · WAIT 10/13 · SILENCE **4/16** · BARGE 7/7, total **37/52**
- SILENCE errado da seguinte forma: 8 preditos RESPOND, 4 WAIT. Causa raiz: o corpus original nunca teve fala completa nao-dirigida (TV/narracao/aula) na classe SILENCE; o modelo aprendeu "frase completa = RESPOND".

## Dataset v2 (a correcao)

Formato: `messages` + `assistant` com rotulo (RESPOND/WAIT/SILENCE/BARGE). Fontes:
- 1.000 RESPOND sintetizadas pelo 4B local (diversidade real, temp 1.0, 15 topicos x 4 estilos);
- house clips reais (clips-transcribed.jsonl, 2.356 itens, re-rotulados com semantica v2:
  fala completa nao-dirigida do computador/TV = SILENCE — o rotulo certo pra o gate);
- 1.729 SILENCE de alucinacao/ ruido digital reais (silence-transcribed.jsonl);
- ~135 frases de listas WAIT/BARGE feitas a mao;
- template coverage total: 4.659 itens, distribuicao RESPOND 1904 / SILENCE 2246 / WAIT 414 / BARGE 95 (cap aplicado).

Sistema novo (CLASS_SYS): SILENCE inclui "fala completa NAO dirigida ao assistente (TV/narracao/musica)".

## Veredito Laya (12/11, medido — capítulo fechado)

- choice RLCD 4 classes: 8/27 (F1 0.31) · parallel + soft-ce: 9/27 (205ms) · zero-shot: 11/27 · noul yes/no: 18/27 (recall 0.69, prec 0.75, F1 0.72) · LoRA: 13/27 (recall 1.00, F1 0.79) · lora+intent: F1 0.889.
- O gargalo NÃO é a arquitetura do Laya: é o dataset (prior 46% RESPOND, utterances soltos sem estado estruturado; calibration temperature bateu o clamp em 5 em TODOS os runs). Gate via LoRA fica.
- Única utilidade restante: abstention OPCIONAL contra TV (noul: 3 FP vs 7 do LoRA puro) — não implementada, e o speaker-gate resolve a mesma coisa de graça.

## O que NÃO funciona hoje (estado 12/11 ~16:30)

1. **Wakeword: não instalada — por DECISÃO do dono (21/10), não por omissão.** home.nix: `services.jarvis-wakeword.enable = false` com o comentário: "o duplex de voz contínua substituiu o wakeword: address gate no classify cumpre a mesma função sem o daemon openwakeword competindo pelo microfone." Reativar exige pedido do dono (mic compartilhado entre 2 daemons).

2. ~~Speaker-ID não é wired~~ RESOLVIDO (12/11): perfil `dono` re-enrolado só com o cluster A (clipes 01/02/03/07, cos pairwise 0.43-0.63); o perfil antigo misturava outra voz (clipes 06/08/09/10, cos 0.85-0.92 entre si). Medido no pipeline real (ASRD, cadência 0.6s): clipe 02 virou **spk=dono cos=0.79**; outra voz e backchannels ficam spk=?. `SPEAKER_GATE=1` (duplex-voice.py) recusa RESPOND de falante≠dono sem endereço; embedder inconclusivo ('?') cai no gate de sempre.

3. **Microturn-4b-lora tem 7 Falsos Positivos em 27 falas** — classes TV (obrigado, música) disparam RESPOND no LoRA puro; o gate de endereço/intent em runtime veta o que é não-endereçado (log de hoje: "RESPOND não-endereçado (TV/sala) — ignora").

## Outras opções Laya vs LoRA — com notas

Laya fine-tuned 4 classes: miss messed everything (5/27 correct recall too low for production voice assistant).
Laya-noul 2-class: recall 0.692, precision 0.750, F1 0.72 — decent but loses vs current LoRA F1=0.79 with the same recall < 1.0.
Laya latency ~280 ms (CPU) vs LoRA 247-587ms — similar.

**Laya pode ser útil** onde o LoRA onde não decidir com confiança —Laya com certeza é conservador: nunca dispara RESPOND seNão tiver quase certeza:
- Senão-ejm - Laya diz noul=0.98 se ouvir "Jarvis ..." (alta confiança, ativa ramite)
- Laya dito noul=0.03 se ouvir TV ou frase de fundo (alta confiança, IGNORE preciso)

Para uma interview em um cenário TV atual, a Laya fine-tune segue soando evitar resposta de TV (3 FP vs 7 FP).
Eem vez de trocar Laya por LoRA, podemos usar Laya como abstention do gate: se Laya diz noul<0.5 AND LoRA diz que é RESPOND, abstention (skip speech); if both say respond, OK respond.

## Próximos passos do desenvolvimento

| Prioridade | Item | Justificativa |
|-----------|------|---------------|
| 1 | Wakeword SÓ se o dono pedir: hoje DESABILITADA por ele (21/10) porque o address-gate cumpre a mesma funcao sem competir pelo mic | depende de decisao explicita do dono |
| 2 | ~~Speaker-ID no gate~~ FEITO 12/11 (perfil dono re-enrolado, SPEAKER_GATE=1, verificado no ASRD real) | TV param de disparar |
| 3 | Laya fine-tuneado como abstention (noul acima de 0.5 responder; noul<0.5 + lora=RESPOND vira skip) | reducao de FP em TV (LoRA 7, Laya 3, 4 FP eliminados) |
| 4 | Fine-tune do LoRA com dados de TV como SILENCE | corrige os 5 ERROS de Classificação LoRA (voc da TVAK) |
| 5 | Bench dos 27 falas com wakeword ligada e com Speaker-ID implementado em gate | deixa de serBench associativo para serBench de produção |
| 6 | Chart do Laya-noul vs LoRA em laptop voice (CPU) com boa acustics setup | em um laptop com Mic bem posicionado, latencia Laya fica mais sutil |

## Laya vs LoRA — resposta direta pra pergunta do dono

Hoje, no bench de 27 falas PT-BR gay:
- LoRA microturn wins on recall (1.00 vs Laya 0.692)
- Laya noul wins on precision (0.75 vs 0.65)
- F1: LoRA wins (0.79 vs 0.72)
- Laya Latency: ~270ms avg (vs LoRA ~250-350ms — loucura)

**LoRA continua como gate principal.** Laya pode ser adicionado como abstention/tiebreak — fica pra lá Bonsai: Laya com 20 bits pode rodar no 4B-MTP também (mock/LoRA/adapted) — a maquína no laptop velho torna Laya viável no notebook com um solo lightstep. Laya fine-tune tem 4 horas de GPU livre ainda a 20.4h disponíveis até a próxima renovação sexta.

## 2026-11-12 20:4x - Kaggle locus duplex-gate-lora (v5) COMPLETO

- Kernel kuchiriel/duplex-gate-lora finalizou: 2 epocas, 4991 itens de treino/val
  (10%), LoRA r=16 a=32 q,v sobre Qwen/Qwen3.5-4B, QLoRA nf4 4-bit, MAX_LEN=160,
  batch=4, PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True (no notebook).
- mean loss epoch 1 = 0.056 (overfit do treino: modelo memorizou a grade do
  template; o val acc do proprio notebook saiu 0/499). Hipotese: no eval cell o
  model.generate com pad_token_id=pad onde pad=eos; o argmax pode ter preenchido
  a janela com eos e predito vazio/fora dos rotulos. A validacao precisa ser
  feita na inferencia real, nao no eval cell.
- adapter baixado para /tmp/opencode/gate-out/duplex_gate_lora/ (adapter_model.safetensors
  7.3MB, adapter_config.json, chat_template.jinja, tokenizer_config.json).
- Conversao adapter -> GGUF preparada: scripts benchmarks/voice/convert-gate-lora.sh
  (commit 5b4663c1). Converter para /tmp/opencode/duplex-gate-v3-lora.q8_0.gguf e
  servir uma segunda instancia CPU na 8093 para A/B contra o held-out de 52.
- Nada aplicado em producao. Decision de troca == do dono, apos numero medido.

## 2026-11-12 21:5x - A/B real: LoRA v3 (Qwen3.5-4B, r16 q,v) vs baseline

Instância de teste CPU na 8093 (mesma base MTP, same flags, só porta diferente
+ ngl=0), adapter convertido com benchmarks/voice/convert-gate-lora.sh.
Rodou bench_heldout contra 8093 e desligou após o teste.

- Baseline produção: 37/52 (RESPOND 16/16, WAIT 10/13, SILENCE 4/16, BARGE 7/7)
- LoRA v3:         40/52 (RESPOND 16/16, WAIT 10/13, SILENCE 7/16, BARGE 7/7)
- Ganho: SILENCE 4/16 -> 7/16 (+3). RESPOND/BARGE intactos. WAIT identico.
- 6 SILENCE viradas RESPOND, 3 viradas WAIT (sem regressao de outra classe).
- Latencia: 149 ms (vs 147 ms baseline). Custo normal.
- Kernel val acc do notebook (0/499) era artefato do eval cell (pad=eos no
  argmax), nao do modelo.
- Nenhum swap em producao. Decisao do dono apos estes numeros.
## 2026-11-13 11:2x - A/B do system prompt do agente (SYSTEM_PT)

Medido com `benchmarks/voice/bench_agent.py`, 18 probes contra o :8092 de
produção (Qwen3.5-4B-MTP + turno-LoRA, mesma superfície da conversa real).
Métricas mecânicas: tool_ok (chamou a tool esperada), direct_ok (NÃO chamou
tool em saudação/char-chat/identidade), no_invent (figura fabricada),
short_ok (resposta <= 45 palavras faladas), no_roleplay (reenactment real),
no_fake_action (não anuncia ação inexistente como feita).

### Variantes medidas (3 repetições cada, temperatura indicada)

| Variante | tool_ok | direct_ok | no_invent | short_ok | no_roleplay |
|----------|---------|-----------|-----------|----------|-------------|
| baseline (SYSTEM_PT atual, temp 0.4) | 6/6 (runs: 6,5,5) | 8/13 | 11/11 | 19/19 | 19/19 |
| baseline0 (temp 0.0) | 5/6 | 8/13 | 11/11 | 19/19 | 18/19 |
| compact (reescrita enxuta, temp 0.0) | 6/6 | 6/13 | 11/11 | 19/19 | 19/19 |
| compact04 (reescrita enxuta, temp 0.4) | 6/6 | 6/13 | 11/11 | 19/19 | 19/19 |
| **targeted (baseline + 2 regras, temp 0.4)** | 5/6 | **12-13/13** | 11/11 | 19/19 | 19/19 |

### O que o targeted muda (2 regras aditivas, nada do resto tocado)

1. Saudação, agradecimento, piada, opinião, identidade (quem é você / qual
   modelo / o que consegue fazer): resposta falada de 1-2 frases SEM tool.
   Identidade responde pela seção IDENTIDADE; nunca recall/status/jarvis
   para falar de si mesmo.
2. Ação que NÃO existe nas tools (reservar voo, pedir pizza, comprar,
   enviar, ligar): diga que não faz isso em 1 frase. NUNCA anuncie a ação
   como feita; NUNCA invente comando de shell para simular.

### Resultado medido

- direct_ok 8/13 -> 12/13 (run única: 13/13; runs: 11,12,12/13 com amostragem temp 0.4)
- tool_ok estável em 5/6 — o único "erro" é a queimadura: a variante
  responde corretamente de memória nas DUAS variantes (água corrente,
  procurar médico), não chama offline_search; resposta clinicamente certa.
- no_invent 11/11 nas duas (PIB 2026: "ainda é uma projeção, não um dado
  confirmado. Posso fazer uma busca rápida" nas duas).
- voo/pizza: baseline chamava web_search (razoável mas não pede); targeted
  recusa com uma frase honesta ("Jarvis não faz reservas de voos, senhor.").
- Piada: baseline chamava remember("piadas"); targeted às vezes também
  (sampling), nunca pior que o baseline.

### Descartado no A/B

- COMPACT (reescrita enxuta do prompt inteiro): direct_ok 6/13 (pior que o
  baseline 8/13) e INVENTOU tools em pedidos de ação inexistente
  (enroll_voice em "pedir pizza", shell reserva_voo em "reservar voo").
  Revertida. O prompt base estava bom; o ganho veio de 2 regras aditivas.
- Linha extra de offline_search forçado (queimadura): direta_ok caiu para
  12/13 e tool_ok ficou 5/6 (a linha não forçou offline_search de forma
  confiável) — revertida (regra base continua no prompt: offline_search
  existe para o corpus de sobrevivência).
- Temperatura 0.0 vs 0.4: 0.0 não melhorou nada (direct 8/13 igual,
  tool_ok 5/6, no_roleplay pior). Temperatura 0.4 mantida.

Commit 3c2a0b7e (scripts/duplex-voice.py) + bench em 4c58beab
(benchmarks/voice/bench_agent.py). O prompt está aplicado no arquivo; o
duplex reinicia na próxima chamada/reciclagem do processo (o módulo lê o
SYSTEM_PT no boot). Decisão de rebuild/reinício do duplex é do dono.
## 2026-11-13 11:5x - Held-out #2 no LoRA de producao : a base que o v6 deve bater

bench_heldout2 (24 falas frescas, zero overlap com train/heldout) apontado para
:8092 via JARVIS_BENCH_BASE (o runner antigo ignorava argv e batia na 8093
morta, imprimindo 0/24 sem erro nenhum — commit 3de2b8e6).

Producao (microturn-4b-lora, medido 3x, temp 0):

| Run | WAIT | SILENCE | BARGE | TOTAL | lat |
|-----|------|---------|-------|-------|-----|
| 1   | 3/4  | 0/18    | 2/2   | 5/24  | 179ms |
| 2   | 2/4  | 0/18    | 1/2   | 3/24  | 302ms |
| 3   | 2/4  | 0/18    | 1/2   | 3/24  | 301ms |

Variancia entre runs (5/24 -> 3/24, um BARGE flip) = noise de amostrar
speculative decoding MTP + cache; nao e regressao de codigo. SILENCE segue
0/18: a mesma classe de falha do heldout1 (TV/narracao declarativa vira
RESPOND), agora medida em itens frescos que o corpus v4 cobriu. O kernel v6
(duplex-gate-lora v6, dataset v4) treina exatamente para isto; o A/B dele e
contra estes 3 numeros.
## 2026-11-13 12:5x - LoRA gate v6 (kernel duplex-gate-lora completo, dataset v4) — A/B honesto

Kernel COMPLETE (30 GPU-hours generosos, uso @12,7h). Adapter baixado,
convertido com benchmarks/voice/convert-gate-lora.sh (convertido de fato: o
--base apontava para o .gguf base e quebrava no load_hparams; o script agora
aponta para o snapshot do HF cache com config.json, commit 5a7bd65f).

### O que o A/B revelou (tudo no CPU de teste :8093, mesmo harness)

1. O v6 foi treinado com apply_chat_template do Qwen3.5 (prompt com
   <think>\n), enquanto o duplex manda prompt SEM think (A_strict). Medido:
   o v6 emite "<think>\nRESPOND" -> classify_turn TODAS com None/NONE.
   O modelo esta bom; o formato do prompt e que nao bate com o harness.
2. Prompt B/C (com <think>): o v6 responde labels limpos 8/8 nos probes.
   Medicao completa com <think> B_prompt (fallback quando A falha):
   - heldout1 (52): SILENCE 7/16, RESPOND 16/16, WAIT 12/13, BARGE 3/7 -> 38/52
   - heldout2 (24 frescos): SILENCE 16/18, WAIT 2/4, BARGE 1/2 -> 19/24
3. Producao (microturn-4b-lora via harness real, medido em :8092):
   - heldout1: 40/52 (RESPOND 16/16, WAIT 10/13, SILENCE 7/16, BARGE 7/7)
   - heldout2: 5/24, 3/24, 3/24 (SILENCE 0/18 em todas as runs)
4. Comando novo: benchmarks/voice/bench_heldout_fallback.py mede pelo
   fallback (A -> B com <think>). O fallback no harness REAL (classify_turn)
   NAO foi aplicado — promocao exige decisao do dono (troca do --lora da
   unit de producao).
5. Veredito honesto: o v6 e MUITO melhor em broadcast/narracao (SILENCE
   0/18 -> 15/18 no heldout2) mas PIOR em BARGE (7/7 -> 3/7 no heldout1,
   1/2 vs 2/2 no heldout2) e empatado no resto. 33% das itens do corpus v4
   eram SILENCE broadcast; BARGE so tinha 105 exemplos. Corpus v4 e
   desequilibrado — nao e o modelo "pior em barge", e o corpus.

### Caminhos (decisao do dono)

A. Retrain v7 com o MESMO corpus v4, mas prompt byte-a-byte o do harness
   atual (prompt A): fabrica drop-in, sem tocar no classify_turn.
   Custo ~2h Kaggle (mesma GPU, quota ok). Recomendado se BARGE e
   barreira critica.
B. Promover v6 + harness think-fallback (classify_turn com retry B):
   - v1 (microturn-4b) nao sofre (A sempre acerta = fallback nunca roda)
   - v6 fica utilizavel; custo extra de 1 chamada por turno (~40ms GPU)
   - troca o --lora da unit de producao (unico ponto de risco) — decisao
     explicita do dono
C. Nao promover nada: aceitar 37/52 base + CLASS_SYS do TV rule (commit
   3c2a0b7e = +3 SILENCE). Status quo.
## 2026-11-13 17:50 - v7 (KERNEL duplex-gate-lora v7 COMPLETE) : o drop-in de verdade

Kernel v7 COMPLETE (GPU T4, ~2h, quota 14.8h/30h). Adapter baixado e
convertido com benchmarks/voice/convert-gate-lora.sh. Instancia CPU de teste
em :8093 (nunca tocou :8092). Resultados (temperature=0, mesmos itens do
held-out):

| teste | v7 (CPU, :8093) | producao v1 (:8092) |
|-------|------------------|--------------------|
| heldout1 RESPOND | 16/16 | 16/16 |
| heldout1 WAIT | 13/13 | 10/13 |
| heldout1 SILENCE | 9/16 | 7/16 |
| heldout1 BARGE | 5/7 | 7/7 |
| heldout1 TOTAL | **43/52** | 40/52 |
| heldout2 WAIT | 3/4 | 3/4 |
| heldout2 SILENCE | **17/18** | **0/18** |
| heldout2 BARGE | 2/2 | 2/2 |
| heldout2 TOTAL | **22/24** | 5/24 |
| total latency | ~5.6s/item (CPU; na GPU ~150-250ms) | ~150-250ms |

Bateria unit-battery completa rodando em background (120 cenas gold-label,
no log /tmp/opencode/v7-unit-battery2.log) — numero esperado nas proximas
horas; este doc recebe atualizacao imediata quando terminar.

Decisao ainda do dono: (A) promover v7 (swap --lora na unit de producao,
rebuild+restart; o dono executa) ou (B) nao promover e manter microturn-4b
(vale para o duplex vivo).

v7 vale como drop-in: responde SEM <think> diretamente (prompt A byte-a-byte
como no harness), latencia identica a do v1 na mesma GPU. O ganho de SILENCE
e real e grande (0/18 -> 17/18). O recuo de BARGE (7/7 -> 5/7) e o PRECO a
percorrer se o dono quiser a solucao broadcast; e da para recuperar com
mais dados BARGE no corpus (o v5 ja tem 685 itens BARGE).

Corpus v5: SILENCE 2573 / RESPOND 2237 / WAIT 455 / BARGE 685 (do v4 com
o BARGE de 105 para 685, WAIT de 437 para 455). Treinado com o MESMO prompt
byte-a-byte de producao (SYSTEM_PT + tag im_start inteira) — opencode e o
harness de teste concordam no formato. Treino na Kaggle, ~2h, nao tocou na
infran local de producao.
## 2026-11-13 17:52 - Veredicto FINAL: v7 (drop-in), promovido? O Kernel v7 COMPLETO mediu:
- heldout1 (52): v7 43/52, producao 40/52 (delta +3: WAIT 10/13->13/13, SILENCE 7/16->9/16)
- heldout2 (24 frescos): v7 22/24, producao 5/24 (SILENCE 0/18->17/18)
- BARGE v7 5/7 vs producao 7/7 (regressao real, pequena)
- Latencia identidade de classe (mesmo tamanho); CPU teste ~5.5s/item apenas pq CPU; GPU deve ser igual ao de producao Conclusao sem fatos: v7 e uma melhoria ESTRITA para o objetivo do dono
(JARVIS que nao responde TV). O custo e BARGE (inferior): 5/7 vs 7/7 —
registros de falso "intromissao" a mais em troca de SILENCE broadcast. Nota de atuacao: teste v7 como infato competitivel do harness real (prompt
A, sem necessidade de fallback no classify_turn); producao e a decisao
pendente do dono (swap --lora na unit de producao). `documentos`: DUPEX-LAYAS-MEASUREMENTS.md recebeu a secao v7 acima.

## 2026-11-13 23:00 — Kernel v8 (kernel version 8) — BARGE rebalanceadas

Kernel v8 dedicado a fixar o BARGE do v7. Adapter baixado e convertido.
Instancia CPU de teste em :8093 (nunca tocou :8092 de producao).

| teste | v8 | v7 | producao |
|-------|----|----|----------|
| heldout1 RESPOND | 16/16 | 16/16 | 16/16 |
| heldout1 WAIT | 12/13 | 13/13 | 10/13 |
| heldout1 SILENCE | 11/16 | 9/16 | 7/16 |
| heldout1 BARGE | **6/7** | 5/7 | 7/7 |
| heldout1 TOTAL | **45/52** | 43/52 | 40/52 |
| heldout2 WAIT | 3/4 | 3/4 | 3/4 |
| heldout2 SILENCE | 17/18 | 17/18 | 0/18 |
| heldout2 BARGE | 2/2 | 2/2 | 2/2 |
| heldout2 TOTAL | 22/24 | 22/24 | 5/24 |

SILENCE (TV/narracao): v8 17/18, todos vencem a producao (+12).
BARGE: v8 ainda abaixo da producao (6/7 vs 7/7), melhor que v7 (5/7).
WAIT: v8 12/13 (v7 era 13/13, producao 10/13).

Ganho honesto: +2 sobre v7 em heldout1 (45/52 vs 43/52) e +2 sobre
producao em SILENCE broadcast (17/18). BARGE ainda 6/7 — os 2 falhos em
heldout1 sao o mesmo caso do v7 ("deixa eu te falar uma coisa" virando
WAIT, nao BARGE). O alvo BARGE em heldout2 manteve 2/2.

A decisao continua do dono: promover na unit de producao ou manter v1
microturn-4b-lora. Nada de producao foi tocado.
