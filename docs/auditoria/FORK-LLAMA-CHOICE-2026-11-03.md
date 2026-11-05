# Qual binário para os tiers MoE: ik_llama.cpp vs llama.cpp stock (2026-11-03)

Pergunta do dono: "avalia git pull, forks, pesquise para saber a resposta" — o tier
MoE (35B-A3B, `:8084`) roda hoje no `ik_llama.cpp`; o upstream do stock tem 348 commits
a mais, incluindo **fusão CUDA de MoE**. Vale trocar?

Estado da pesquisa (evidência de git + papers + RFC upstream). A decisão final depende
da medição 3-vias (seção 5) — nada entra em produção sem ela.

## 1. Estado dos dois checkouts (fetch em 2026-11-03)

| repo | HEAD local | origem | atrás | commits locais únicos |
|---|---|---|---|---|
| `~/projects/llama.cpp` (stock) | `9d1878a4` (build 1087) | `2cbca389` | **348** | 0 |
| `~/projects/ik_llama.cpp` | `c446f1e0` (17/10) | `35e0be56` | **101** | 0 |

Nenhum dos dois é um fork nosso com patch próprio: são checkouts estagnados de upstream.
Ou seja: a escolha real é **"qual upstream, em que commit, com quais flags"**.

> Nota: o build local `build-stock/` (o que a produção usa para 4B/30B e o que a peer
> mediu) é o `9d1878a4` — 348 commits atrás. O path `~/projects/llama.cpp/build` não
> existe (o dir é `build-stock/`).

## 2. O que o upstream do stock trouxe depois do nosso build (348 commits)

Relevantes para nós:

- `f5222f25 cuda: fuse MoE (MUL_MAT_ID) gate/up and GLU in MMQ (#31188)` — **fusão CUDA
  de MoE** (o MUL_MAT_ID dos experts passa a calcular gate/up + GLU fundidos). É
  exatamente o gargalo do nosso tier MoE (experts na RAM, matmul no accelerate path).
- `a7af149a cuda: add top-k MoE fusion for 384 experts (#31288)`.
- `85cc432e server: add router device memory margin parameter for dynamic unload` — a
  família do `--fit-target` (margem por device) evoluindo.
- `7df8b876 server: restore the spec checkpoint for drafts longer than n_rs_seq` — correções
  no caminho de spec/MTP (o que a produção 4B usa).
- `fa3645fe llama: respect no_alloc in all memory caches`, `73adf89e minimax-m3: forward
  quant scales to the graph` (fix de quant do minimax — nosso modelo de nuvem).

## 3. O que o ik trouxe depois do nosso commit (101 commits)

`35e0be56` "Allow using merged up/gate experts with Hadamard rotations" · `5635f95a`
"Fuse scale → sigmoid → scale → FMA" · `7dce673e` "Add optimized build options for
AVX-512 CPUs" · `4955387a` "Fix TQ on CUDA" · `e6d43ccd` "qwen4exp: load GGUFs with merged
weight pairs" · `4e8dc3d3`/`ef45f229` "minimax-m3: BF16 indexer + sparse attention no
backend CPU" · `b25c3fd2` "ggml: faster q8_k_r16" · `0a81bfe9` "Q8_0_R16 setup cost" ·
`13cffc00` "CUDA: static cuBLAS workspace per stream" · `9462969f`/`b7a47528` "MLA decode
micro-opt / shared expanded MLA prefill".

Ou seja: o ik é **mais agressivo em CPU/AVX-512 e em modelos novos** (qwen4exp,
minimax-m3), e está em `AVX-512 optimized builds` — relevante numa CPU 6P+4E ( Alder Lake
P-cores = Golden Cove/Raptor Cove, com AVX-512 ✓).

O que o ik **não** tem: `--fit`/`--fit-target` (o auto-fit do vídeo) — só `--moe-cache-mib`.

## 4. O "expert cache" do vídeo: o que a literatura e o upstream dizem

- **Upstream tem a flag** (`common/arg.cpp`: `--moe-cache-mib`) e a implementa
  (`cparams.moe_cache_size` → contexto). **Medido aqui: não muda nada** (C ≈ B na ladder).
- A implementação que **ganha** é a do RFC **#24528** ("MoE expert cache, VRAM caching of
  hot CPU-resident experts with **hybrid hit/miss execution**", leloch, 12/06/2026, 51
  comentários): branch `leloch:moe-cache-pr`, tabela do autor: **13,57 t/s vs 6,88 do
  upstream (+97%)** a 65535 de contexto, +84% a 405k. O PR de código (#24524) foi
  **fechado por grande demais para review** e o RFC está **aberto** → **não está no
  upstream** (nenhum commit de expert/moe cache entre `9d1878a4` e `2cbca389`).
  Point: o `--moe-cache-mib` do upstream **não** é a mesma coisa que a receita do vídeo.
- Papers que sustentam (e explicam) o resultado:
  - **MoEpic / Adaptive Expert Split** (arXiv 2509.08342): experts em RAM + cache
    parcial na VRAM; o speed degrada por **baixa taxa de acerto do cache + latência de
    carregar experts da RAM** → ou seja, o cache só paga se o *split* forVertical e o
    hit rate for alto (nossa 35B roteia 8 de 256 experts → cache de 2 GB não cobre).
  - **CPU-GPU collaborative inference para MoE** (arXiv 2512.16473): divide a VRAM em
    *expert cache* + componentes essenciais (atenção, normalização, router, KV) — **é o
    desenho da receita do vídeo**; o paper mede ganho **dependente do modelo** (não
    universal).

## 5. Decisão: precisa de medição 3-vias (protocolo da casa)

O número de 25/09 ("ik 36 t/s vs upstream 32 t/s, +11%") é **obsoleto**: o stock de
então era ~700 commits mais velho e **não tinha a fusão CUDA de MoE**. Medição 3-vias
(mesmo harness `scripts/bench-llm.sh`, mesma janela, `LD_LIBRARY_PATH` do systemd,
guard de VRAM, load 6,5–8,7/16):

| # | binário | receita |
|---|---|---|
| X1 | `ik_llama.cpp/build` (5074, produção do tier MoE) | `-ngl 45 --n-cpu-moe 35 -t 6 -c 32768 -b 512 -ub 512` |
| X2 | `llama.cpp/build-stock` (1087, produção 4B/30B) | idem X1 (controle) |
| X3 | stock `2cbca389` (**build novo, CUDA, sm_89**) | idem X1 **e** `--fit-target 512` (sem `-ngl`) |

Critério de decisão:

1. Se **X3 ≥ X1** no decode e no TTFT → trocar o tier MoE para o **stock atualizado**
   (um binário a menos no stack: 4B e 30B já são stock; e o stock tem `--fit`,
   `--lora`, spec/MTP e recebe a fusão CUDA de MoE).
2. Se **X1 > X3** → manter ik no tier MoE, mas **atualizar o ik** (101 commits atrás:
   AVX-512, MLA, q8_k_r16, minimax-m3) e reavaliar; registrar que o auto-fit do vídeo
   fica indisponível nesse binário.
3. Em qualquer caso, **o tier MoE não serve para voz** (ver
   `LLAMACPP-FLAGS-VIDEO-2026-11-02.md`: TTFT 420–9066 ms) — voz é do 4B-MTP.

### Status 03/11 (03:50): X3 COMPILADO, medição ainda pendente

O binário X3 está pronto e verificado:

- `~/projects/llama.cpp/build-master/build/bin/llama-server` (movido de /tmp
  para sobreviver ao reboot — 247 MB; o repo llama.cpp é "track only", o
  diretório fica **untracked**).
- `version: 0.8.0-dev (build 1, commit 2cbca38)` · GNU 15.3.0 · CUDA sm_89
- Flags presentes: `--fit-target`, `--moe-cache-mib`, `--n-cpu-moe`, `--lora`,
  `--spec-type` (o stock 1087 de produção tem todas, menos as fuses de MoE).
- ⚠️ **Precisa de `LD_LIBRARY_PATH`** (o RUNPATH gravou o path de build
  antigo, `/tmp/opencode/...`):
  `LD_LIBRARY_PATH=~/projects/llama.cpp/build-master/build/bin`
  → é o mesmo mecanismo do `BENCH_LD_ENVFILE` do `scripts/bench-llm.sh`.
- Build: cmake 4.1.6 + ninja 1.13.2 + cuda-merged-12.9 + gcc-wrapper-15.3.0
  (nix); receita do configure: `-DCMAKE_CUDA_FLAGS=-I$CUDA/include
  -DCUDAToolkit_ROOT=$CUDA -DCMAKE_CUDA_ARCHITECTURES=89 -DLLAMA_CURL=OFF`
  (o `cuda-merged` do nix NÃO expõe os headers no path do nvcc — precisa do
  `-I` + `NIX_CFLAGS_COMPILE` do cc-wrapper).
- **A medição NÃO foi feita**: o driver do kernel (615.71.09) ainda não casa
  com o userspace novo (615.78) → medir VRAM/throughput agora mediria o stack
  antigo. Medir **depois do reboot**, com o agente parado.

## 6. Armadilhas (as mesmas da ladder)

- Sem o `LD_LIBRARY_PATH` do serviço systemd o server sobe **CPU-only** (stub CUDA):
  3,2 t/s em vez de 24,6 → o harness aborta nesse caso (`BENCH_LD_ENVFILE`).
- Carga da máquina muda o t/s em ±50 % → medir com o agente **parado** e sem outro
  llama-server pesado.
- `--fit` **aborta** se `-ngl` estiver setado → para reproduzir o vídeo, sem `-ngl`.
- Guard de VRAM: com 4B (:8092) + router (:8080) + embeddings residentes, a VRAM
  livre (~550 MiB) não comporta outro tier → parar os serviços pesados antes do bench.

## Fontes

- Git: `git fetch` + `git log HEAD..origin/{master,main}` em `~/projects/llama.cpp` e
  `~/projects/ik_llama.cpp` (2026-11-03).
- RFC upstream: https://github.com/ggml-org/llama.cpp/discussions/24528 (leloch).
- Papers: arXiv 2509.08342 (MoEpic / Adaptive Expert Split), arXiv 2512.16473
  (CPU-GPU collaborative inference para MoE).
- Ladder da peer: `docs/BENCH-35B-LADDER-2026-11-02.md`.
