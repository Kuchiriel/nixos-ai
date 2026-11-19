---
title: "Backlog #08 — Codacus 35B-A3B em 6 GB (expert-cache) vs 8B denso: qualidade e DUR no heldout3"
type: auditoria
escopo: voice-gate-heldout3-codacus-35b-vs-8b-denso
data: 2026-11-19
janela: 2026-11-18 22:50 -> 2026-11-19 04:00
status: medido
---

# Backlog #08 — 35B-A3B (expert-cache) contra 8B denso no gate de voz

Item do backlog: `H: Codacus 35B-A3B em 6GB via expert-cache vs 8B denso — medir
qualidade heldout2 e dur por ciclo; gate ck=v3 3 amostras`.
O bus (19/11 00:00, `jarvis@nitro-v15`) corrigiu o conjunto: **heldout3**, nao
heldout2 (o v2 esta contaminado). Este doc e o medido.

## 1. Resumo (o veredito)

| braco | o que e | acuracia no heldout3 (39) | latencia por fala | dur por ciclo (39 falas) |
|---|---|---|---|---|
| 4B MTP + LoRA v9 (producao da voz) | `jarvis-mtp-lora` na :8092 | **29/39 (74,4%)** · 3 amostras identicas | 4,6–5,5 s | 180–213 s |
| 35B-A3B + LoRA duplex (Codacus) | `jarvis-duplex` na :8085 | **14/39 (35,9%)** (amostra limpa, 4 slots) | **72,6 s** (media) | **2.832 s (47 min)** |
| 8B denso (bonsai, sem LoRA de voz) | `Ternary-Bonsai-8B` na :8080 | **0–1/39 (0–2,6%)** · 3 amostras | 0,9–1,0 s | 35–40 s |

**Veredito:** a hipotese do Codacus **nao se sustenta no gate de voz nesta
maquina**. O 35B **sobe** (a frase "35B MoE impossivel" que foi publicada no bus
esta errada), mas:

1. **Ele e 15–40x mais lento** que o 4B MTP (72,6 s por fala contra 4,6–5,5 s),
   e a voz precisa de sub-segundo: o classificador oficial aborta em **8 s**.
2. **Ele erra mais**: 14/39 contra 29/39 do MTP, no mesmo conjunto limpo.
   Parametro nao ajuda o gate: 35B nao e melhor que 4B aqui.
3. **O gargalo nao e VRAM**: e **RAM/swap**. O 35B-A3B Q4_K_M tem 20,2 GB de
   arquivo e precisa de ~23 GB de RAM (`memHigh` do registry); este host tem
   31 GB com a frota rodando, e sobra ~16–18 GB. O servidor passa a ser
   **limitado por disco** (197 MB/s de leitura, page-in dos experts), e o prompt
   eval cai de 5,49 tok/s (cache quente) para 1,1–2,5 tok/s.

O 8B denso nem entra na disputa: **sem o LoRA de voz ele nao faz a tarefa**
(33/39 respostas sem rotulo: ele "pensa" em vez de responder e o `n_predict 6`
corta "SILENCE" em "SILE").

## 2. Instrumento

O runner oficial do heldout3 e `benchmarks/voice/bench_heldout3.py` (Cervo/sweep).
Este medido **nao o substitui**: usa o mesmo conjunto
(`benchmarks/voice/heldout3.py`), o mesmo prompt (`CLASS_SYS` de
`scripts/duplex-voice.py`) e o mesmo parse de rotulo, e acrescenta:

- **N amostras** no mesmo servidor (o oficial roda 1 vez) e salvamento
  incremental do JSON apos cada amostra (um ciclo de 47 min nao pode ser
  perdido no meio).
- **Timeout por chamada parametrizavel** (padrao 180 s). O oficial usa 8 s: no
  35B isso mede o **timeout**, nao o modelo (ver §5).
- **Braco sem LoRA** (`--lora off`): o 8B denso nao tem LoRA de voz, e o POST
  `/lora-adapters` do classificador oficial **falha** — o runner oficial marca
  tudo como `NONE` e mede o harness, nao o modelo.
- **Ciclo de vida do braco**: o 35B sobe pelo **unit do registry**
  (`llama-duplex-35b.service`, flags em `modules/ai/models.nix`), que e a fonte
  de verdade; o 8B sobe pelo `scripts/llm-swap.sh bonsai`.

Script: `scripts/bench-35b-codacus.py` (runner, header com uso e exemplo).
Resultados: `benchmarks/model-tiers/results/35b-a3b-heldout3-*.json`,
`8b-denso-heldout3-*.json`, `mtp4b-lora-heldout3-*.json`.

## 3. Ambiente medido

| item | valor |
|---|---|
| GPU | RTX 4050 Laptop, 6141 MiB (6 GB) |
| RAM | 31 GB total; 16–18 GB disponiveis com a frota rodando |
| Swap | 15 GB (10–12 GB **ja usados** por outros processos da casa) |
| Modelo | `/var/lib/ai/models/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf` (20,2 GB) |
| LoRA do Codacus | `/var/lib/ai/models/loras/microturn-duplex/microturn-duplex-lora.gguf` (14,6 MB) |
| Perfil do 35B (registry) | `llama-duplex-35b.service`: `-ngl 99 --n-cpu-moe 44 -fa off -ctk f16 -ctv f16 -c 8192 -b 512 -ub 512`, 4 slots, `memHigh 23G` |
| Binario | `llama.cpp/build-stock` (o unico com LoRA funcional no 35B) |

## 4. O 35B: sobe, e quanto custa

**Subida (DUR de partida):**

| evento | tempo | evidencia |
|---|---|---|
| unit do registry, cache frio | **68 s** | 00:10:30 -> 00:11:38 (journal do unit) |
| unit do registry, cache quente | **25,8 s** | 03:23:43 -> 03:24:09 (39 GB lidos do disco) |
| variante `--parallel 1` (mesmos flags) | **60 s** | 02:18:09 -> 02:19:10 |

**VRAM:** 2.795 MiB usados pelo 35B (5.396 MiB livres antes, 3.059 depois) — a
tese "35B nao cabe em 6 GB" **esta errada**: com `--n-cpu-moe 44` os experts
ficam na RAM e a GPU so carrega o resto.

**Velocidade (o gargalo real):**

| fase | tok/s | observacao |
|---|---|---|
| prompt eval, isolado e quente (00:22) | **5,49** | 102 tokens em 18,6 s |
| prompt eval, com a RAM cheia (01:27+) | **1,10–2,49** | 109–118 tokens em 44–103 s |
| geracao, isolado e quente (00:22) | **0,44** | 2.173 ms **por token** |
| geracao, mais tarde | 1,07–1,62 | ainda 0,6–0,9 s por token |

O CPU fica ocioso (97% idle) durante a geracao e o disco entrega 197 MB/s: o
modelo esta **limitado por I/O**, porque os experts nao cabem na RAM disponivel
e sao page-in a cada token. Nao e a flag, nao e a VRAM: e **memoria**.

## 5. As tres armadilhas que custaram tempo (registradas no P0)

1. **`python3` do sistema nao tem numpy.** O runner do heldout3 importa
   `scripts/duplex-voice.py` e morre com `ModuleNotFoundError: No module named
   'numpy'`. Correcao: `nix develop --command python3 ...`.
2. **O timeout de 8 s do `classify_turn` mede o timeout, nao o modelo.** No
   35B, uma resposta de 6 tokens leva 13 s (isolado) a 100 s (RAM cheia): o
   classificador oficial devolve `None` em 39/39. Com timeout de 180 s o mesmo
   classificador devolve rotulo — inclusive `RESPOND` para *"meu cao me mordeu,
   o que faco"*, que o 4B MTP classifica como `SILENCE`.
3. **Duas medicoes no mesmo servidor se contaminam.** Um segundo bench rodando
   na :8085 (outro agente, timeout de 60 s) deixou a amostra 1 com **22
   timeouts** e latencia media de 68 s. A acuracia nao muda (temperatura 0), a
   latencia muda muito. Regra: **uma medicao por vez, com a GPU e a RAM
   Exclusivas**.

## 6. Resultados por amostra

### 6.1 35B-A3B (Codacus, :8085)

| amostra | condicao | acertos | latencia media | dur do ciclo | erros (timeout) |
|---|---|---|---|---|---|
| A | **contaminada** (2o bench na mesma porta) | 7/39 (17,9%) | 68,1 s | 2.657 s | 22 |
| B | limpa (so o bench) | **14/39 (35,9%)** | 72,6 s | 2.832 s | 2 |
| C | limpa (perfil do registry, 3 amostras) | ver JSON | | | |
| D | limpa (idem) | ver JSON | | | |

### 6.2 4B MTP + LoRA v9 (producao, :8092)

| amostra | acertos | latencia media | dur do ciclo |
|---|---|---|---|
| 1 | 29/39 (74,4%) | 5,47 s | 213 s |
| 2 | 29/39 (74,4%) | 5,06 s | 197 s |
| 3 | 29/39 (74,4%) | 4,61 s | 180 s |

As 3 amostras sao **identicas** (temperatura 0: o classificador e deterministico
com o mesmo prompt). Isto muda o que "3 amostras" significa aqui: no gate de voz
a repeticao **prova determinismo**, nao variancia. (A variancia que a frota
procura no lab A/B e de outro instrumento: o checker do patch.)

**Correcao ao numero publicado:** o audit do heldout3
(`docs/auditoria/HELDOUT3-GATE-VOZ-2026-11-18.md`) registra **23/39 (59%)** para
o mesmo braco. O numero medido agora e **29/39 (74,4%)**. A diferenca sao 6
itens: a extracao do rotulo foi corrigida em 18/11 (o rotulo agora e procurado
em qualquer posicao da saida, e nao so no inicio — `duplex-voice.py:687`), e o
audit foi escrito antes dessa correcao. A latencia bate com o audit (4,6 s
contra 4,47 s), o que confirma que e o mesmo braco.

### 6.3 8B denso (bonsai, :8080, sem LoRA)

| amostra | acertos | latencia media | dur do ciclo | sem rotulo |
|---|---|---|---|---|
| 1 | 0/39 (0%) | 0,95 s | 37 s | 33/39 |
| 2 | 1/39 (2,6%) | 1,02 s | 40 s | 32/39 |
| 3 | 1/39 (2,6%) | 0,90 s | 35 s | 32/39 |

O 8B denso **nao faz a tarefa**: sem o LoRA de voz ele abre `<think>` ("Okay,
let's...") e o `n_predict 6` corta "SILENCE" em "SILE". O `NONE` do runner
oficial (33/39) e o mesmo fenomeno.

## 7. Como reproduzir

```bash
cd ~/projects/nixos-ai
# 1) 35B do Codacus: o unit do registry sobe (flags em models.nix)
sudo -n systemctl start llama-duplex-35b.service
# 2) 3 amostras do heldout3 com o timeout corrigido
nix develop --command python3 scripts/bench-35b-codacus.py \
    --arm none --base http://127.0.0.1:8085 --lora on --samples 3 --oficial
# 3) 8B denso (sobe e devolve a GPU sozinho)
nix develop --command python3 scripts/bench-35b-codacus.py \
    --arm 8b --lora off --samples 3
# 4) referencia de producao (4B MTP + LoRA v9)
bash scripts/llama-swap.sh --start-mtp lora
nix develop --command python3 scripts/bench-35b-codacus.py \
    --arm none --base http://127.0.0.1:8092 --lora on --samples 3
```

## 8. O que fica para a proxima vez

- Se o 35B for importante para a voz, o caminho nao e "subir o 35B no gate": e
  **congelar a maquina** (host vazio, sem a frota) ou aceitar a latencia. Com a
  frota rodando, o ciclo de 39 falas do 35B custa **47 min** contra 3 min do MTP.
- O `memHigh 23G` do registry ja avisa que o perfil pede ~23 GB; o que falta e
  um **guard de RAM** que recuse a subida do 35B quando a RAM livre esta abaixo
  do que os experts precisam (hoje o servidor sobe e degrada em silencio).
- O `n_predict 6` do classificador corta "SILENCE" em "SILE" em modelos sem o
  LoRA: um `n_predict` maior (ou um stop por rotulo) tornaria o 8B denso
  mensuravel em vez de "NONE".
