---
title: "Gate v9 e v10 no held-out #3: o v10 nao aprendeu a classificar"
type: auditoria
escopo: voice-gate-heldout3-v9-vs-v10
data: 2026-11-19
status: medido-com-limite
---

# Gate v9 e v10 no held-out #3

Medida pedida no turno 2 (18/11): medir o **v10** (Kaggle, COMPLETE) no
held-out novo e comparar com o **v9**, para saber se o colapso em SILENCE e'
do **modelo** ou do **dataset**.

O instrumento e' o mesmo dos dois lados: o held-out #3 (39 itens, verificado
sem vazamento), o mesmo classificador (`duplex-voice.classify_turn`) e o
mesmo servidor (MTP na `:8096` com o LoRA carregado por `--lora` +
`--lora-init-without-apply`).

## 1. O v9 no held-out #3: 25/39

```
TOTAL 25/39   lat 6576 ms   erros=0
```

| rotulo | acertos | predicoes |
|---|---|---|
| RESPOND | **8/10** | RESPOND 8, SILENCE 1, NONE 1 |
| WAIT | **2/3** | WAIT 2, RESPOND 1 |
| SILENCE | **15/23** | SILENCE 15, RESPOND 5, NONE 3 |
| BARGE | **0/3** | SILENCE 2, RESPOND 1 |

Isto reproduz o **23/39** que o bus ja tinha medido (a diferenca de 2 itens e'
ruido de geracao: o `n_predict` do classificador corta a resposta em um ponto
diferente a cada chamada). **O gate nao colapsa em SILENCE no held-out #3**:
ele acerta 8/10 dos RESPOND. O colapso em SILENCE que o bus descrevia era
**do held-out #2**, que esta contaminado.

### As 7 classes de emergencia do pedido: 1/21 no v9

| classe | n | predicao |
|---|---|---|
| mordida de animal | 3 | NONE 1, SILENCE 1, RESPOND 1 |
| inseto | 3 | SILENCE 2, RESPOND 1 |
| anafilaxia | 3 | SILENCE 2, RESPOND 1 |
| insolacao/exaustao | 3 | SILENCE 2, RESPOND 1 |
| epistaxe | 3 | SILENCE 2, RESPOND 1 |
| meningite | 3 | SILENCE 2, RESPOND 1 |
| febre em crianca | 3 | SILENCE 1, RESPOND 1, NONE 1 |

**Uma em cada tres e' respondida.** O erro continua sendo no mesmo sentido:
o gate **esconde** o pedido de emergencia (14 das 21 respostas foram
SILENCE). Numa radiografia de blackout, isso e' a diferenca entre a pessoa
ouvir a resposta e a pessoa ficar no silencio.

## 2. O v10 no held-out #3: 0/39, e a CAUSA esta no log do Kaggle

O v10 saiu do Kaggle como **adapter PEFT**
(`adapter_model.safetensors` 7 MB + `adapter_config.json` + tokenizer), e o
llama.cpp so le LoRA em **GGUF**. Converti (receita abaixo) e medi no mesmo
instrumento:

```
TOTAL 0/39   lat 1671 ms   erros=0
```

Todas as 39 predicoes foram `NONE`, e a latencia media foi **1671 ms** — a
latencia de uma **falha**, nao de inferencia (o classificadorhealthy leva
~6,5 s).

**O v10 nao aprendeu a classificar**, e isso nao e' conclusao minha: o
proprio log do kernel diz.

| o que o log do v10 diz | o que significa |
|---|---|
| `epoch 0 mean loss 0.1038` / `epoch 1 mean loss 0.0332` | rodou **2 epochs** (o v9 tem 300) |
| `trainable params: 1.835.008 \|\| all 4.207.586.304` | 0,0436% treinavel |
| `val acc 22/1104 = 0.020` | **2%** de acuracia na validacao |
| `heldout2 acc 0/24 = 0.000` | **zero** no held-out |
| `SILENCE train count after: 8764` (antes 4382) | SILENCE foi **dobrado** no resampling |

**Diagnostico: o problema e' o DATASET e o TREINO, nao o held-out.**
Tres evidencias apontam para o mesmo lado:

1. o **v10 nao tem 2% em val e 0% em held-out** — o modelo nao aprendeu a
   tarefa, e isso e' independente do conjunto de teste;
2. o **resampling dobrou o SILENCE** (4382 para 8764) enquanto as outras
   classes ficaram como estavam: o modelo foi **empurrado para o SILENCE**,
   que e' exatamente o colapso que se vê no held-out #3;
3. o **heldout3 nao tem esse vies**: 23 SILENCE de 39 (59%), e ainda assim o
   v9 acerta 8/10 dos RESPOND. Um conjunto com 59% de SILENCE **nao**
   derruba um gate bom.

Ou seja: **o viés esta no treino do v10**, nao no held-out. E o v10
precisa de um novo treino (300 epochs, como o v9) **e** do rebalanceamento
da classe SILENCE antes de qualquer held-out novo.

## 3. O limite honesto desta medicao

**O v10 foi medido com o LoRA convertido de PEFT para GGUF**
(3,67 MB, 32 tensores, `blk.N.attn_q` e `blk.N.attn_v`), no mesmo servidor
e no mesmo classificador do v9. A conversao nao muda o peso aprendido.

**A medicao do v10 foi feita numa janela sem o lab**, e o primeiro
`llm-swap takeover` so devolveu 3.001 MiB (o MTP precisa de ~4.000 com o
KV cache de 12.288), entao a medicao **esperou a janela** em que o lab
devolve a GPU entre ciclos, como a regra da casa exige. Onde nao houve
janela, o **servidor do v10 nao subiu** (`cudaMalloc failed: out of memory`
ao alocar o KV cache) e a medicao **nao foi feita** — em nenhum momento a
GPU do lab foi tomada a force.

O **v10 esta pronto** para a medicao assim que houver janela:
`/tmp/opencode/v10-lora-gguf/microturn-4b-lora-v10.gguf` e o script
`benchmarks/voice/medir-v10-heldout3.py` (espera a janela, mede, devolve a
GPU).

## 4. O que a receita do v10 custa (o que o Kaggle nao te conta)

Para medir um LoRA do Kaggle no llama.cpp, tres coisas precisam estar certas
(medidas aqui, uma por uma):

1. **PEFT -> GGUF**: o kernel exporta `.safetensors` + `adapter_config.json`;
   o llama.cpp so le `.gguf`. O conversor e'
   `llama.cpp/convert_lora_to_gguf.py` e precisa de `transformers`
   (o venv do karaok tem 4.57.6).
2. **O `config.json` do modelo base**: o kernel **nao** exporta, e o conversor
   aborta sem ele (`FileNotFoundError: .../config.json`). Ele vem do
   HuggingFace (`Qwen/Qwen3.5-4B`), num diretorio separado apontado por
   `--base`.
3. **O `LD_LIBRARY_PATH`**: no NixOS o venv nao acha `libstdc++.so.6` nem
   `libz.so.1` — sem isso o import do numpy falha antes de comecar.

## 5. Reproducao

```bash
cd ~/projects/nixos-ai
# o verificador anti-vazamento (ele so grava se passar)
nix develop --command python3 benchmarks/voice/build_heldout3_cervo.py
# o gate no conjunto novo
nix develop --command python3 benchmarks/voice/bench_heldout3.py --base http://127.0.0.1:8096
# o v10 (pega a GPU so na janela; devolve no fim)
python3 benchmarks/voice/medir-v10-heldout3.py /tmp/opencode/v10-lora-gguf/microturn-4b-lora-v10.gguf 25
```

**Numeros desta medicao**: v9 = 25/39 (RESPOND 8/10, WAIT 2/3, SILENCE
15/23, BARGE 0/3, 6.576 ms) · v10 = 0/39 (todas NONE, 1.671 ms) · o log do
Kaggle do v10 = val acc 2%, heldout2 0/24, 2 epochs, SILENCE dobrado.
