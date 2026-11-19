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
- **Prompt**: o mesmo do classificador de voz do laboratório
  (`CLASS_SYS` + a fala), palavra por palavra.
- **Veredito**: o rótulo extraído da resposta, com o bloco de raciocínio
  removido.
- **Timeout e n_predict honestos**: 180 s e 24 (ou 96 para o braço de API).
  **Motivo medido**: com `n_predict=6` o rótulo mais longo (`SILENCE`, 7
  caracteres) sai cortado como `SILE`, e o timeout de 8 s do `classify_turn`
  oficial mede o **timeout**, não o modelo.
- **Token**: o `usage` real da resposta (`prompt_tokens`,
  `completion_tokens`), não uma estimativa.
- **3 rodadas por braço**, no mesmo servidor, com o adapter pedido.

## 2. A tabela

| braço | modelo | acertos | desvio | tokens/rodada | latência mediana | **acurácia por 1M token** |
|---|---|---|---|---|---|---|
| **especialista (4B MTP + LoRA v9)** | Qwen3.5-4B-MTP | **15/39 (38,5%)** | 0,0 | 2.770 | 3,8-5,4 s | **5.415** |
| especialista (4B MTP + LoRA v10, Kaggle) | Qwen3.5-4B-MTP | 13/39 (33,3%) | 0,0 | 2.768 | 3,9-4,1 s | 4.697 |
| **contexto grande (1M ctx, sem LoRA de voz)** | nemotron-3-ultra-550b-a55b | 10/39 (25,6%) | 0,8 | 5.805 | 3,1-3,7 s | **1.723** |

**O veredito da hipótese:** o especialista **vence em qualidade e por token**.

- acurácia: 38,5% contra 25,6% (+12,9 pontos);
- acurácia por token: **5.415 contra 1.723** (3,1x mais);
- token por rodada: 2.770 contra 5.805 (2,1x menos).

E o desvio é **zero nos dois adapters locais** (3 rodadas idênticas): a diferença
de 2 itens entre v9 e v10 é real, não ruído.

## 3. O v10 não aprendeu a classificar — e o culpado é o treino, não o conjunto

O v10 (Kaggle, COMPLETE) deu 13/39 contra os 15/39 do v9, com desvio zero nos
dois. A causa está no **log do próprio kernel**, não no held-out:

| o que o log do v10 diz | o que significa |
|---|---|
| `epoch 0 mean loss 0.1038` / `epoch 1 mean loss 0.0332` | rodou **2 epochs** (o v9 tem 300) |
| `trainable params: 1.835.008 \|\| all 4.207.586.304` | 0,0436% treinável |
| `val acc 22/1104 = 0.020` | **2%** na validação |
| `heldout2 acc 0/24 = 0.000` | zero no held-out |
| `SILENCE train count after: 8764` (antes 4382) | **SILENCE dobrado** no resampling |

**O held-out não é o culpado**: ele tem 59% de SILENCE (23 de 39) e mesmo assim
o v9 acerta 15/39. O viés está no **treino** do v10 (SILENCE dobrado, 2 epochs).
**O caminho é rebalancear a classe e retreinar com 300 epochs**, não trocar o
conjunto de teste.

## 4. O braço de 1M ctx: sem LoRA de voz, e o token vai para o raciocínio

O braço `api` do laboratório é o `nvidia/nemotron-3-ultra-550b-a55b` (1M de
contexto), via o nv-gate na `:8095`. Ele **não tem LoRA de voz** — então o 0/39
que ele daria com o `n_predict` do laboratório é o resultado **honesto**, não um
bug: o laboratório já mediu "8B denso SEM LoRA = 0-1/39".

**O achado fino**: com `n_predict=24` o modelo de 1M ctx devolve **string
vazia** ou cortada (`'RE'`), e o `usage` mostra onde o token foi:
`completion_tokens_details.reasoning_tokens = 24` de 24. Com `n_predict=96` o
rótulo sai (`'RESPOND'`). Ou seja: **o veredito media o corte, não a
capacidade** — exatamente o defeito (c) que a frota apontou.

## 5. Quatro achados de rota que mudam a leitura de todos

1. **O processo vivo do `:8092` não é o que o registry diz.** Ele sobe
   `--lora .../microturn-4b-lora.gguf` (84.952.704 bytes, o adapter PEFT
   grande), enquanto `modules/ai/models.nix:430` aponta
   `microturn-4b-lora-v9.gguf` (3.058.400 bytes, o GGUF pequeno). Medir no
   `:8092` mede **outro adapter** (12/39). Divergência entre código e processo.
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

## 6. O que muda na casa

- **Para a voz, o token do raciocínio é custo.** O modelo de 1M ctx gasta 2,1x
  mais token por rodada e acerta menos. No gate de voz, que tem prazo de
  sub-segundo, isso é decisivo: o especialista é o caminho.
- **O `classify_turn` oficial mede transporte, não modelo.** Com `n_predict=6` e
  timeout de 8 s, o veredito é o corte e o timeout. Isso vale para **qualquer**
  medição de voz da casa e deveria ser corrigido antes da próxima série (é
  decisão de produto: o timeout que não corta é o que a voz precisa, mas
  então o gate de verdade tem que ser o de regra, não o classificador).
- **O item #08 (35B MoE) fica confirmado pela mesma régua**: 35B+LoRA duplex
  deu 9/39 com 61 s por token e 2,4 h por ciclo (medido pela frota). O
  especialista 4B dá 15/39 com 4,6 s por token e 3 min por ciclo. A hipótese
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
# o contexto grande (pela API, sem GPU)
nix develop --command python3 scripts/medir-gate-api.py 96 180 3 api
```

**Scripts** (novos, desta lane): `scripts/medir-gate-adapter.py` (mede um
adapter local sobe o MTP), `scripts/medir-gate-api.py` (mede o braço de API na
mesma métrica) e `scripts/medir-acuracia-por-token.py` (cruza a qualidade que o
lab já mediu com o token medido).

**Números desta medição**: v9 = 15/39, 2.770 tokens/rodada, 5.415 por 1M
token · v10 = 13/39, 2.768 tokens/rodada, 4.697 por 1M token · api (1M ctx,
sem LoRA de voz) = 10/39, 5.805 tokens/rodada, 1.723 por 1M token.
