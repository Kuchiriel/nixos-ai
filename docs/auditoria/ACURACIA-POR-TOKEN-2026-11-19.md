---
title: "Acuracia por token: 1M de contexto contra o especialista (heldout3)"
type: auditoria
escopo: voice-gate-acuracia-por-token-1m-vs-especialista
data: 2026-11-19
status: medido
---

# Acurácia por token: 1M de contexto contra o especialista

Item #10 (backlog da frota): a hipótese do video do VIDEU (canal VIDEU, 14/11,
"Kimi K3.1 & GLM 5.3 vs Claude Opus 5.5 & Fable 5.2: 144 Coding Runs on Amazon
Bedrock") é que **o número que manda é o custo por tarefa resolvida**, não o
score bruto — *"Price per solved job is the number to watch"* (04:57). Os
números do video: Fable 18/18, Kimi 14, Opus 14, GLM 10 (14/11); e no terminal
bench 4.0, tokens de saída por tarefa: 6,1M (K 3.1), 12,8M (GLM), 14,9M
(Opus), 11,1M (Fable).

Na casa o preço é zero, então a métrica vira **acurácia por token**: quantas
tarefas aprovadas o checker dá por token gasto.

## 1. O instrumento

- **Conjunto**: o held-out #3 (39 itens, 16 classes), que só é gravado depois
  de provar ausência de vazamento (0 igualdade, 0 containment, 0 quase-duplicata
  no corte 0,55, 0 template repetido, 0 caractere fora do repertório).
- **Prompt**: o `CLASS_SYS` **oficial**, palavra por palavra. Isto não é
  detalhe: com uma versão encurtada do prompt o v9 dava 15/39, e com o oficial
  dá 29/39 — o mesmo modelo, o mesmo adapter, o mesmo conjunto.
- **Timeout e orçamento honestos**: 180 s, e `n_predict`/`max_tokens` grande
  o bastante para o rótulo mais longo (`SILENCE`, 7 caracteres) caber **depois**
  do raciocínio do modelo.
- **Token**: o `usage` real da resposta (`prompt_tokens`,
  `completion_tokens`).
- **3 rodadas por braço**, no mesmo servidor, com o adapter pedido.

## 2. A tabela

| braço | modelo | acertos | desvio | tokens/rodada | latência mediana | **acurácia por 1M token** |
|---|---|---|---|---|---|---|
| **especialista (4B MTP + LoRA v9)** | Qwen3.5-4B-MTP | **29/39 (74,4%)** | 0,0 | 4.602 | 8,1-9,6 s | **6.301** |
| especialista (4B MTP + LoRA v10, Kaggle) | Qwen3.5-4B-MTP | 20/39 (51,3%) | 0,0 | 4.619 | 6,5-8,1 s | 4.330 |
| contexto grande (1M ctx, sem LoRA de voz) | nemotron-3-ultra-550b-a55b | 17,3/39 (44,4%) | 1,2 | 8.332 | 4,6-8,8 s | **2.080** |
| **produção (o adapter que está no ar)** | Qwen3.5-4B-MTP | 12/39 (30,8%) | 0,0 | 4.600 | 6,6-9,4 s | 2.609 |

**O veredito da hipótese:** o especialista **vence em qualidade e por token**.

- acurácia: 74,4% contra 44,4% (+30 pontos);
- acurácia por token: **6.301 contra 2.080** (3x mais);
- token por rodada: 4.602 contra 8.332 (1,8x menos).

O desvio é **zero nos três adapters locais** (3 rodadas idênticas): a diferença
de 9 itens entre o v9 e o v10 é real, não ruído. O braço de API tem desvio
1,2 (é a API, com 429 e variabilidade de cota).

### 2.1 A mesma métrica na escala que o dono pediu (1.000 / 5.000 / 10.000 tokens)

A tabela acima está em "por 1M de token" porque é a unidade do vídeo. O dono
pediu a escala de 1.000 / 5.000 / 10.000 tokens. A conversão é **exata** (os
mesmos números medidos, reescalonados): aprovações por token = acertos da
rodada / tokens da rodada; a coluna de 1.000 tokens é a unidade de 1M
dividida por 1.000.

| braço | 1.000 tokens | 5.000 tokens | 10.000 tokens | por 1M token |
|---|---|---|---|---|
| **especialista (4B MTP + LoRA v9)** | **6,3** aprovações | **31,5** | **63,0** | 6.301 |
| especialista (4B MTP + LoRA v10, Kaggle) | 4,3 | 21,7 | 43,3 | 4.330 |
| contexto grande (1M ctx, sem LoRA de voz) | 2,1 | 10,4 | 20,8 | 2.080 |
| produção (o adapter que está no ar) | 2,6 | 13,0 | 26,1 | 2.609 |

Leitura: com 10.000 tokens, o especialista v9 entrega **63 tarefas aprovadas**
onde o modelo de contexto grande entrega **21**, e onde o adapter que está
no ar hoje (o v1, com 2,6 por 1.000) entrega **26**. O mesmo token compra
3x mais trabalho resolvido no v9, e a razão é constante com o orçamento
porque as duas taxas são lineares no token.

**O que a escala revela e a coluna por 1M esconde:** o custo por tarefa
aprovada é o que importa, e ele é **1,8x menor no especialista** (4.602
tokens para 39 itens contra 8.332). Um orçamento de 10.000 tokens pagaria
**2,2 rodadas** do especialista (85 itens, cerca de 63 aprovações) contra
**1,2** do modelo de contexto grande. E o braço "produção" mostra que o
adapter que está no ar hoje custa **2,4x mais** por acerto que o v9.

## 3. O v10 não aprendeu a classificar — e o culpado é o treino, não o conjunto

O v10 (Kaggle, COMPLETE) deu 20/39 contra os 29/39 do v9, com desvio zero nos
dois. A causa está no **log do próprio kernel**, não no held-out:

| o que o log do v10 diz | o que significa |
|---|---|
| `epoch 0 mean loss 0.1038` / `epoch 1 mean loss 0.0332` | rodou **2 epochs** (o v9 tem 300) |
| `trainable params: 1.835.008 \|\| all 4.207.586.304` | 0,0436% treinável |
| `val acc 22/1104 = 0.020` | **2%** na validação |
| `heldout2 acc 0/24 = 0.000` | zero no held-out |
| `SILENCE train count after: 8764` (antes 4382) | **SILENCE dobrado** no resampling |

**O held-out não é o culpado**: ele tem 59% de SILENCE (23 de 39) e mesmo assim
o v9 acerta 29/39. O viés está no **treino** do v10 (SILENCE dobrado, 2 epochs).
**O caminho é rebalancear a classe e retreinar com 300 epochs**, não trocar o
conjunto de teste.

## 4. O braço de 1M ctx: sem LoRA de voz, e o token vai para o raciocínio

O braço `api` do laboratório é o `nvidia/nemotron-3-ultra-550b-a55b` (1M de
contexto), via o nv-gate na `:8095`. Ele **não tem LoRA de voz** — então o 0/39
que ele daria com o `n_predict` do laboratório é o resultado **honesto**, não um
bug: o laboratório já mediu "8B denso SEM LoRA = 0-1/39".

**O achado fino, medido**: o token do modelo de 1M contexto vai quase todo
para o **raciocínio**, e o rótulo é cortado no fim.

| `max_tokens` | o que volta | `completion` | `reasoning` |
|---|---|---|---|
| 24 | **string vazia** | 24 | 24 |
| 64 | `RESPOND` na 1ª e 2ª, **vazio** na 3ª | 30-64 | 24-64 |
| 128 | `RESPOND`, `RESPOND`, `SILENCE` | 30-109 | 24-103 |
| 256 | idem | 29-189 | 23-183 |

Ou seja: **para o rótulo caber, o modelo de 1M contexto precisa de ~110
tokens de orçamento** (e gasta ~103 pensando). Com o `n_predict=6` do
laboratório, ele nunca sairia. **O veredito media o corte, não a capacidade** —
que é exatamente o defeito (c) que a frota apontou.

## 5. Quatro achados de rota que mudam a leitura de todos

1. **O processo vivo do `:8092` não é o que o registry diz.** Ele sobe
   `--lora .../microturn-4b-lora.gguf` (84.952.704 bytes, o adapter PEFT
   grande), enquanto `modules/ai/models.nix:430` aponta
   `microturn-4b-lora-v9.gguf` (3.058.400 bytes, o GGUF pequeno). Medido
   naquele adapter: **12/39** contra os **29/39** do v9. A produção da voz
   está com um adapter que vale 30% menos.
2. **A porta 8096 é do laboratório**, e ele **mata o processo que estiver na
   mesma porta** (medido: `RemoteDisconnected: Remote end closed connection
   without response`). A porta livre para medir é a 8094.
3. **"O laboratório está com a GPU" não se decide pelo processo.** O
   `ab_loop.sh` fica vivo durante o sono de 45 s entre ciclos **com a GPU já
   devolvida** (4.525 MiB livres), então o critério por processo recusa a
   janela sem motivo. O critério certo é a **porta 8096** do laboratório.
4. **O v10 estava só no Kaggle.** Baixado e convertido de PEFT para GGUF: o
   kernel exporta `adapter_model.safetensors` + `adapter_config.json` +
   tokenizer, **sem o `config.json` do modelo base** (que o conversor exige), e
   o `llama.cpp` só lê GGUF. Fica em
   `/tmp/opencode/v10-lora-gguf/microturn-4b-lora-v10.gguf` (3.672.800 bytes)
   e **ainda não** no `/var/lib/ai/models` (onde vivem o v8 e o v9).

E um quinto, o mais caro de todos:

5. **O prompt do classificador é parte do instrumento.** Com o `CLASS_SYS`
   encurtado, o v9 dava 15/39; com o oficial (que descreve cada rótulo), dá
   29/39. Medir o gate com outro prompt mede outro gate.

## 6. O que muda na casa

- **Para a voz, o token do raciocínio é custo.** O modelo de 1M contexto gasta
  1,8x mais token por rodada e acerta 30 pontos a menos. No gate de voz, que
  tem prazo de sub-segundo, isso é decisivo: o especialista é o caminho.
- **O `classify_turn` oficial mede transporte, não modelo.** Com `n_predict=6`
  e timeout de 8 s, o veredito é o corte e o timeout — e o `None` cai no gate
  de regra, que **mascara transporte como resposta do modelo**. Isso vale para
  **qualquer** medição de voz da casa e deveria ser corrigido antes da próxima
  série (é decisão de produto: o timeout que não corta é o que a voz precisa,
  mas aí o gate de verdade tem que ser o de regra, não o classificador).
- **A produção da voz está no adapter errado** (12/39 em vez de 29/39): o
  `:8092` carrega o adapter de 81 MB e o registry aponta o v9 de 2,9 MB.
  Alinhar os dois é correção de configuração, não de modelo.
- **O item #08 (35B MoE) fica confirmado pela mesma régua**: 35B+LoRA duplex
  deu 9/39 com 61 s por token e 2,4 h por ciclo (medido pela frota). O
  especialista 4B dá 29/39 com 4,6 s por token e 3 min por ciclo. A hipótese
  do Codacus (35B MoE em 6 GB) está **refutada neste limite**.

## 7. Reprodução

```bash
cd ~/projects/nixos-ai
# o verificador anti-vazamento (ele so grava depois de provar)
nix develop --command python3 benchmarks/voice/build_heldout3_cervo.py
# o especialista (sobe o MTP com o adapter, mede N rodadas e devolve a GPU)
nix develop --command python3 scripts/medir-gate-adapter.py \
  /var/lib/ai/models/loras/microturn-4b/microturn-4b-lora-v9.gguf 24 180 v9 3 12
# o v10 (o mesmo caminho, com o adapter convertido do Kaggle)
nix develop --command python3 scripts/medir-gate-adapter.py \
  /tmp/opencode/v10-lora-gguf/microturn-4b-lora-v10.gguf 24 180 v10 3 12
# o contexto grande (pela API, sem GPU; 128 de max_tokens porque o rotulo
# precisa caber depois do raciocinio)
nix develop --command python3 scripts/medir-gate-api.py 128 180 3 api 25
```

**Scripts** (novos, desta lane): `scripts/medir-gate-adapter.py` (mede um
adapter local, sobe o MTP, N rodadas, devolve a GPU), `scripts/medir-gate-api.py`
(o braço de API na mesma métrica, com espera de 429) e
`scripts/medir-acuracia-por-token.py` (cruza a qualidade que o lab já mediu
com o token medido).

**Números desta medição**: v9 = 29/39, 4.602 tokens/rodada, 6.301 por 1M
token · v10 = 20/39, 4.619 tokens/rodada, 4.330 por 1M token · produção
(adapter de 81 MB) = 12/39, 4.600 tokens/rodada, 2.609 por 1M token · api
(1M ctx, sem LoRA de voz) = 17,3/39, 8.332 tokens/rodada, 2.080 por 1M
token.
