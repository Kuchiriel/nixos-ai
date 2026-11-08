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
| `nanbeige` upstream **não** é a mesma arch (layouts diferentes) | Dory separa attn e FFN em blocos físicos distintos (72 blocos, `blk.0` só attn, `blk.1` só FFN, `dory.layer_pattern = S-S-S-*-…`); o `nanbeige` upstream espera attn+FFN no mesmo índice → **renomear a arch no GGUF dá tensor mismatch** |
| O suporte está no **PR #30306** (ggml-org/llama.cpp), **aberto** (08/11) | `gh pr view 30306` → state OPEN, autor `brianchmielNV`, branch `dory-support`, sem merge |
| O card manda usar o **fork** `brianchmielNV/llama.cpp` pinado em `98a74c97ea09ac72f6ceda1559808fc0a2f447ce` | card do HF, seção "llama.cpp" |
| Build local: `0.6.0-dev (build 11551, commit 98a74c97e)`, CUDA sm_89 | `--version` do binário que compilamos |
| O **loop count é um override de KV**, não flag | `--override-kv "dory.num_loops=int:N,dory.recurrent_kv_cache_mode=str:per_loop\|last_loop"` (`src/models/dory.cpp` aceita só `per_loop` ou `last_loop`) |
| Download íntegro | sha256 `96080be…a660e0` = o publicado pela NVIDIA → **SUCESSO** ✓ (3,61 GB em `~/models/`) |

## 2. Números (harness da casa `scripts/bench-llm.sh`, load 4,3–6,5 de 16 threads)

Config: `-ngl 999 -t 6 -b 512 -ub 512 --cache-type-k/v f16 --flash-attn off
--no-context-shift --jinja --reasoning on`, 20480 de contexto (o mesmo do 4B-MTP).

| modelo/config | decode t/s | prefill t/s | TTFT (1 tok ctx) | 1o tok c/ 512 tok | VRAM |
|---|---|---|---|---|---|
| **Dory loop=1** (`per_loop`, c20480) | **17,9–22,8** | 29–97 | **574–970 ms** | 1787–2285 ms | 4,5 GB (sozinho) |
| **Dory loop=4** (`per_loop`, c4096) | **7,8–9,9** | 9–27 | **1846–2941 ms** | 4426–4896 ms | — |
| Dory loop=2 (`per_loop`, c20480) | — | — | — | — | **NÃO CABE**: `failed to allocate CUDA0 buffer of size 768612352` (733 MiB) → OOM de VRAM |
| 4B-MTP produção (`:8092`, MTP draft) | **105,7–105,9** | 143–354 | **178–203 ms** | 688–740 ms | 5139 MiB |
| 4B receita do vídeo (fit512, KV q8_0, sem MTP) | 54,3 | 205–562 | 153–175 ms | 537–566 ms | 4557 MiB |

## 3. Veredito

1. **O Dory NÃO passa o gate de voz** (TTFT ≤ 150 ms): 574–970 ms no loop=1 — **4–6×
   acima** — e 1846–2941 ms no loop=4. O loop é o dial de compute, então **mais loop =
   mais latência**, exatamente ao contrário do que a voz quer.
2. **É ~6× mais lento que o nosso 4B-MTP** em decode (17,9–22,8 vs 105,9 t/s) e 3–5×
   pior em TTFT. O MTP (draft) do 4B é o que faz a diferença; o Dory não tem draft.
3. **O loop custa VRAM**: loop=2 já estoura a placa a 20k de contexto (o grafo expandido
   pede 733 MiB de compute buffer). O modo `last_loop` (o "memory-efficient looping" do
   card: um cache de KV por camada) é o modo a medir para isolar isso.
4. **English-only** (o card): o JARVIS fala pt-BR → para voz/duplex está fora de
   questão mesmo se a latência coubesse.
5. **A literatura não sustenta "vence 27B"** (ver a nota de papers): a regra do campo é
   que, a igual computo, **parâmetros×N ganha de N loops**; o loop paga em compute de
   inference adaptativo, não em qualidade por parâmetro.

**Conclusão:** o Dory entra no grupo de **candidato a tier de *thinking*** (o lugar do
35B, hoje CPU-bound demais), **não** no de voz — e só entra se a **qualidade** no
loop=1 for ≥ a do 4B-MTP (critério da própria nota). O critério de entrada da casa:
loop=1 **precisa** bater o 4B-MTP nas tarefas do JARVIS, senão não entra.

## 4. Armadilhas medidas no caminho (o harness da casa)

1. **`LD_LIBRARY_PATH` sem o `build/bin` do fork ⇒ "no backends are loaded"** e o bench
   sai em **silêncio** (nenhuma linha no TSV, sem erro no stderr — o erro vai para o
   log do servidor). O card do HF já avisa: `export LD_LIBRARY_PATH="$PWD/.../build-cuda/bin"`.
2. **O guard de VRAM do harness não pega esse caso**: ele aborta quando o log traz
   `failed to initialize CUDA`, mas aqui o erro é `no backends are loaded` → o bench
   "roda" e não mede nada. *Gap do harness (não corrigido: é da casa, da lane da peer
   que patchou o `bench-llm.sh` — vou levar isso no bus).*
3. **Porta fixa 8095 colidia com o serviço da casa `nv-gate.py --port 8095`** → o server
   do bench não subia ("couldn't bind HTTP server socket") e o bench saía sem medir.
   → **Corrigido aqui**: `PORT=${PORT:-8095}` (08/11) — `PORT=8097 scripts/bench-llm.sh …`.
4. A VRAM do Dory (3,7 GB de pesos) **não divide** com o 4B-MTP (4,0 GB) na placa de
   6,1 GB → para medir o Dory, o 4B tem que estar parado (janela combinada com a peer).
