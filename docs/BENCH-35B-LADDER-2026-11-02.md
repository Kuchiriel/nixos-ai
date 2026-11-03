# Benchmark ladder — Qwen3.6-35B-A3B na RTX 4050 6 GB (vídeo Codacus, 02/11/2026)

Escada de flags do vídeo `tek-IY9BRWc` ("What's the Best AI Model Your GPU Can
Actually Run? 4GB to 16GB VRam", canal Codacus) aplicadas **no nosso hardware**,
com o harness da casa (`scripts/bench-llm.sh`) — mesma métrica para 35B e 4B.

> **Veredito curto:** o 35B-A3B **não serve para voz** nesta placa (prefill
> CPU-bound de 7–19 tok/s ⇒ hundreds de ms por token de contexto, TTFT de
> segundos). O 4B-MTP continua sendo o default. O `--fit`/`--moe-cache-mib` do
> vídeo **não** compensa a diferença: no nosso caso o gargalo é CPU/RAM, não
> o split de VRAM.

## 1. Hardware e software (fatos que decidem tudo)

| Item | Valor |
|---|---|
| GPU | RTX 4050 Laptop, **6141 MiB** VRAM (5853 MiB usáveis pelo driver) |
| VRAM livre no boot | ~**0,5 GB** (4B-MTP 4834 MiB + embeddings 446 MiB) |
| RAM | 31 GB total (19 GB disponíveis durante o bench) |
| CPU | 6 P-cores + 4 E-cores (16 threads lógicos) → `-t 6` (metade, como o vídeo) |
| Binário | `llama.cpp/build-stock/bin/llama-server` — **build 1087, v0.7.0-dev** |
| Modelo | `~/models/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf` (20,2 GB) |
| Baseline voz | `~/models/Qwen3.5-4B-MTP-Q4_K_M.gguf` (2,7 GB) + LoRA micro-turn + MTP draft |

### Feature-check dos builds (as flags do vídeo existem nos nossos binários?)

| Flag | stock (1087) | ik_llama.cpp (5074) | prism-bin (b10xxx) |
|---|---|---|---|
| `--moe-cache-mib` | **sim** | **sim** | a conferir (lane do colega) |
| `--fit-target` | **sim** | **não** | a conferir |
| `--fit` (on/off) | **sim**, default `on` | não | não |
| `-ctk` / `-ctv` | sim (só **short**; `--ctk` não existe) | — | — |

## 2. Duas armadilhas de medição (achadas na medição, não no vídeo)

1. **CPU-only silencioso.** Com `LD_LIBRARY_PATH` fora do serviço systemd, o
   binário carrega a **CUDA stub** e o server sobe **sem GPU**: 3,2 t/s em vez
   de 24,6. O harness agora **aborta** quando o log traz `failed to initialize
   CUDA` e aceita `BENCH_LD_ENVFILE` para importar o env do serviço.
2. **`--fit` aborta se `-ngl` estiver setado.** `common/fit.cpp` lança
   `common_params_fit_exception("n_gpu_layers already set by user to N, abort")`
   → **nossa receita de produção (`-ngl 45 --n-cpu-moe 35`) nunca usa o
   auto-fit do vídeo**. Para reproduzir o vídeo é preciso **não** passar `-ngl`.

Também medido: `nproc` = 16 (não 20), e a carga da máquina (agentes ativos)
mexe o t/s em ±50 % — o harness agora grava `load1`/`ncpu` junto de cada rep.

## 3. Resultados (harness da casa: warmup 2×64, 3 reps de 128 tok, prompt distinto por rep)

Legenda: **tg** = decode tok/s · **pp** = prefill tok/s · **ttft** = 1º token
com prompt de 1 token (latência de resposta) · **pf512** = 1º token com prompt
de 512 tokens (prefill no caminho) · **VRAM** = pico durante a run.

| # | Config | tg (t/s) | pp (tok/s) | ttft (ms) | pf512 (ms) | VRAM pico |
|---|---|---|---|---|---|---|
| A | `-ngl 45 --n-cpu-moe 35 -t 6 -c 32768` (receita de produção) | 8,0–13,4 (24,6 em run isolado) | 7–19 | 450–1 979 | 5 872–43 780 | — |
| B | `--fit-target 512` (auto-fit do vídeo, **sem** `-ngl`) | 11,8–14,1 | 12–30 | 420–634 | 3 996–24 984 | — |
| C | B + `--moe-cache-mib 2048` | 9,8–11,2 | 13–19 | 703–1 043 | 9 025–17 802 | 5 105 MiB |
| D | C + `-ctk q8_0 -ctv q8_0` | 6,8–10,4 | 7–21 | 1 266–9 066 | 6 450–23 953 | 5 139 MiB |
| E | C + `-ub 1024` | 9,5–11,1 | 8–18 | 546–1 022 | 4 604–24 858 | — |
| F | C + `-t 10` | 6,5–8,5 | 9–24 | 1 118–1 648 | 5 819–17 937 | 5 105 MiB |
| **4B** | **produção (:8092) — MTP + LoRA, c 20 480, KV f16** | **105,7–105,9** | **143–354** | **178–203** | **688–740** | 5 139 MiB |
| **4B** | **receita do vídeo (fit 512, ub 1024, KV q8_0, sem MTP)** | 54,3 | 205–562 | 153–175 | 537–566 | 4 557 MiB |

**Leitura:** o 4B de produção decodifica **~8× mais rápido** (105,9 vs 9,8–14,1 t/s)
e tem **prefill 10–20× maior** (143–354 vs 7–30 tok/s); o 35B só passa em
decode quando a máquina está livre (24,6 t/s) e **nunca** passa no gate de
TTFT (420–9 066 ms contra 150 ms).

Dados brutos: `/tmp/bench-ladder.jsonl` (uma linha JSON por rep, com `load1`
e `ncpu`). Logs por config: `/tmp/bench-srv-<tag>.log`.

## 4. Conclusões (o que muda na nossa stack)

1. **GATE DO VÍDEO: FALHA no 35B ⇒ o 4B-MTP continua default.** O gate era
   "≥ classe de 17 t/s **e** TTFT ≤ 150 ms a `-t 6`". Medido: 9,8–14,1 t/s com
   a máquina compartilhada (24,6 t/s isolado) e **TTFT de 420 ms a 9 s**.
   O 4B de produção mede **TTFT 178–203 ms** com prefill de 143–354 tok/s.
2. **O gargalo é CPU/RAM, não a VRAM.** Com experts na CPU, o prefill do 35B
   fica em 7–30 tok/s ⇒ **512 tokens de contexto = 4–44 s**. Para voz isso
   é inviável; o 35B é tier de *thinking* (texto longo, sem urgência).
3. **`--moe-cache-mib` e `--fit-target` não mudam o veredito** (C ≈ B ≈ A):
   o cache de experts em VRAM ajuda marginalmente o decode e o `--fit` só
   funciona **sem** `-ngl` (e o `--fit` escolheria um split pior que o nosso).
4. **`-t 10` é pior que `-t 6`** (6,5–8,5 vs 9,8–11,2 t/s) — confirma a
   regra da casa: metade dos P-cores, não metade dos threads lógicos.
5. **KV q8_0 no 35B piora o TTFT** (D: 1 266–9 066 ms) — mais ops por token
   quantizado sem ganho de prefill neste gargalo de CPU.
6. **Achado útil para o 4B**: a receita do vídeo no 4B usa **4 557 MiB**
   (KV q8_0 + sem MTP) contra **5 139 MiB** da produção — ~580 MiB de VRAM
   a mais no default, o que importa numa placa de 6 GB com o router.
   Trade-off: decode 54,3 vs 105,9 t/s (a produção tem MTP draft +24 %).

## 5. Pendências para o `models.nix` (lane do colega `voice-flags-en`)

- `uncensored-35b` (:8084): a receita atual (`-ngl 45 --n-cpu-moe 35 -t 6
  -c 32768 -b 512 -ub 512`, KV q4_0) **já é a melhor das testadas**; o
  `--fit` do vídeo não se aplica (conflita com `-ngl`). O que falta é
  **documentar o porquê** no serviço e, se quiser o split automático, uma
  variante *sem* `-ngl` + `--fit-target 512`.
- `duplex-35b` (:8085, lane de voz): manter `-ngl 99 --n-cpu-moe 44` (medido
  aqui: o cache de experts **não** compensa o `--fit`).
- `uncensored-4b` (:8092, default/voz): **manter** — é o que passa no gate
  de TTFT. Possível otimização: `-ub 256` → 512 e KV q8_0 (medir antes).
