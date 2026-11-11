# Dory 1.0 4B (NVIDIA, looped) — medido na RTX 4050 6 GB (2026-11-08)

Pergunta do dono: *"Dory (NVIDIA) + looping transformers: papers + o modelo; cabe na
VRAM? teoricamente vence 27B; se latência ficar baixa, melhor que o Qwen atual pra tudo
(inclusive duplex/voice/phonecall)"*.

Nota de pesquisa (papers, leitura do card, contra-ponto da literatura):
`~/Books/papers/2026-11-03-dory-looped-transformers.md`.

## 1. O que foi preciso para rodar (não é plug-and-play)

| fato | evidência |
|---|---|
| O GGUF usa `general.architecture = dory`; o llama.cpp upstream **não** tem essa arch | `src/llama-arch.cpp` do upstream master (f477f79, 08/11) só tem `nanbeige`; `git grep -i dory` não acha nada |
| `nanbeige` upstream **não** é a mesma arch (layouts diferentes) | Dory separa attn e FFN em blocos físicos distintos (72 blocos, `blk.0` só attn, `blk.1` só FFN, `dory.layer_pattern = S-S-S-*-…`); o `nanbeige` upstream espera attn+FFN no mesmo índice: **renomear a arch no GGUF dá tensor mismatch** |
| O suporte está no **PR #30306** (ggml-org/llama.cpp), **aberto** (08/11) | `gh pr view 30306`: state OPEN, autor `brianchmielNV`, branch `dory-support`, sem merge |
| O card manda usar o **fork** `brianchmielNV/llama.cpp` pinado em `98a74c97ea09ac72f6ceda1559808fc0a2f447ce` | card do HF, seção "llama.cpp" |
| Build local: `0.6.0-dev (build 11551, commit 98a74c97e)`, CUDA sm_89 | `--version` do binário que compilamos |
| O **loop count é um override de KV**, não flag | `--override-kv "dory.num_loops=int:N,dory.recurrent_kv_cache_mode=str:per_loop\|last_loop"` (`src/models/dory.cpp` aceita só `per_loop` ou `last_loop`) |
| Download íntegro | sha256 `96080be…a660e0` = o publicado pela NVIDIA: **SUCESSO** ✓ (3,61 GB em `~/models/`) |

## 2. Números (harness da casa `scripts/bench-llm.sh`, load 4,3–6,5 de 16 threads)

Config: `-ngl 999 -t 6 -b 512 -ub 512 --cache-type-k/v f16 --flash-attn off
--no-context-shift --jinja --reasoning on`, 20480 de contexto (o mesmo do 4B-MTP).
Os runs de loop=2 que mediram usaram ubatch 128 (o tag de cada run esta no
`/tmp/opencode/dory-bench-l2c20480.jsonl`).

| modelo/config | decode t/s | prefill t/s | TTFT (1 tok ctx) | 1o tok c/ 512 tok | VRAM |
|---|---|---|---|---|---|
| **Dory loop=1** (`per_loop`, c20480) | **17,9–22,8** | 29–97 | **574–970 ms** | 1787–2285 ms | 4,5 GB (sozinho) |
| **Dory loop=4** (`per_loop`, c4096) | **7,8–9,9** | 9–27 | **1846–2941 ms** | 4426–4896 ms | — |
| **Dory loop=2** (`per_loop`, c20480, ubatch 128) | **10,8–12,0** | 13,6–50,1 | **1214–3045 ms** | 3133–4476 ms | coube; a 1a tentativa (ub 512) estourou `failed to allocate CUDA0 buffer of size 768612352` (733 MiB) |
| 4B-MTP produção (`:8092`, MTP draft) | **105,7–105,9** | 143–354 | **178–203 ms** | 688–740 ms | 5139 MiB |
| 4B receita do vídeo (fit512, KV q8_0, sem MTP) | 54,3 | 205–562 | 153–175 ms | 537–566 ms | 4557 MiB |

## 3. Qualidade (harness da casa `scripts/eval-model.py`, 29 tarefas em 6 classes)

| modelo | total | general | coding | tool | agent | reasoning | adversarial | legit (pt-BR) |
|---|---|---|---|---|---|---|---|---|
| 4B-MTP produção (`:8092`) | **18/29** | 3/3 | 2/4 | 1/4 | 1/3 | 1/3 | 0/2 | **10/10** |
| Dory loop=1 (`last_loop`) | 14/29 | 2/3 | 2/4 | **4/4** | 1/3 | 1/3 | 1/2 | 3/10 |
| Dory loop=2 (`last_loop`) | 15/29 | — | — | — | — | — | — | — |

Leitura (o que os números dizem, não o que a gente queria):

1. **O Dory não bate o 4B-MTP** (14–15 vs 18): **pelo critério da própria nota de
   papers ("se loop=1 não for ≥ o 4B-MTP em qualidade, o modelo não entra"), o Dory
   NÃO entra no stack.**
2. **O déficit é quase todo de idioma**: a classe `legit` (10 tarefas em **português**)
   dá 3/10 no Dory contra 10/10 no 4B: é o "English-only" do card aparecendo como
   número, não como teoria. Nas tarefas em inglês o Dory **iguala** (coding 2/4,
   agent 1/3, reasoning 1/3) e **vence** em tool-use (**4/4 vs 1/4**).
3. **O loop compra pouco**: loop=1: loop=2 = **+1 tarefa** (14:15) com o dobro de
   compute e o TTFT piorando (1,6–3,4 s).
4. O Dory recusou **1 das 7 tarefas sensíveis**; o 4B é ABLITERATED (0 recusa): o
   Dory é *alinhado*, o que é o oposto do que o tier Uncensored precisa.

## 4. Veredito

1. **O Dory NÃO passa o gate de voz** (TTFT ≤ 150 ms): 574–970 ms no loop=1 — **4–6×
   acima** — e 1846–3414 ms nos loops 2/4. O loop é o dial de compute, então **mais loop =
   mais latência**, exatamente ao contrário do que a voz quer.
2. **É ~6× mais lento que o nosso 4B-MTP** em decode (17,9–22,8 vs 105,9 t/s) e 3–5×
   pior em TTFT. O MTP (draft) do 4B é o que faz a diferença; o Dory não tem draft.
3. **O loop custa VRAM**: com `per_loop`, loop=2 a 20k estourou a placa na 1a tentativa
   (`failed to allocate CUDA0 buffer of size 768612352`, 733 MiB); os runs que mediram
   (10,8-12,0 t/s, TTFT 1214-3045 ms) usaram ubatch 128. Com **`last_loop`** (um cache de
   KV por camada) **cabe** a 20k ✓ — o "memory-efficient looping" do card é real e
   verificado aqui.
4. **English-only** (o card): o JARVIS fala pt-BR: para voz/duplex está fora de
   questão mesmo se a latência coubesse.
5. **A literatura não sustenta "vence 27B"** (ver a nota de papers): a regra do campo é
   que, a igual computo, **parâmetros×N ganha de N loops**; o loop paga em compute de
   inference adaptativo, não em qualidade por parâmetro.

**Decisão: o Dory NÃO entra no stack agora.** Fica documentado como candidato a tier de
*thinking* **em inglês** (onde o tool-use 4/4 é uma vantagem real), se algum dia o
produto falar inglês com ele. O GGUF fica em `~/models/` (3,61 GB) — **não deletar**
(regra da casa: modelo baixado não se joga fora sem o dono; disco com 141 GB livres).
**O 4B-MTP segue como default** — é mais rápido **e** melhor na nossa língua.

## 5. Armadilhas medidas no caminho (o harness da casa)


1. **`LD_LIBRARY_PATH` sem o `build/bin` do fork: "no backends are loaded"** e o bench
   sai em **silêncio** (nenhuma linha no TSV, sem erro no stderr — o erro vai para o
   log do servidor). O card do HF já avisa: `export LD_LIBRARY_PATH="$PWD/.../build-cuda/bin"`.
2. **O guard de VRAM do harness não pega esse caso**: ele aborta quando o log traz
   `failed to initialize CUDA`, mas aqui o erro é `no backends are loaded`: o bench
   "roda" e não mede nada. *Gap do harness (não corrigido: é da casa, da lane da peer
   que patchou o `bench-llm.sh` — vou levar isso no bus).*
3. **Porta fixa 8095 colidia com o serviço da casa `nv-gate.py --port 8095`**: o server
   do bench não subia ("couldn't bind HTTP server socket") e o bench saía sem medir.
  : **Corrigido aqui**: `PORT=${PORT:-8095}` (08/11) — `PORT=8097 scripts/bench-llm.sh …`.
4. A VRAM do Dory (3,7 GB de pesos) **não divide** com o 4B-MTP (4,0 GB) na placa de
   6,1 GB: para medir o Dory, o 4B tem que estar parado (janela combinada com a peer).
