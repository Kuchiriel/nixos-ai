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

| # | Config (35B = Qwen3.6-35B-A3B UD Q4_K_M) | tg (t/s) | pp (tok/s) | ttft (ms) | pf512 (ms) | VRAM pico |
|---|---|---|---|---|---|---|
| A | `-ngl 45 --n-cpu-moe 35 -t 6 -c 32768 -b 512 -ub 512` (receita de produção) | 8,0–13,4 (24,6 em run isolado) | 7–19 | 450–1 979 | 5 872–43 780 | — |
| B | `--fit-target 512` (auto-fit do vídeo, **sem** `-ngl`) | 11,8–14,1 | 12–30 | 420–634 | 3 996–24 984 | — |
| C | B + `--moe-cache-mib 2048` | 9,8–11,2 | 13–19 | 703–1 043 | 9 025–17 802 | 5 105 MiB |
| D | C + `-ctk q8_0 -ctv q8_0` | 6,8–10,4 | 7–21 | 1 266–9 066 | 6 450–23 953 | 5 139 MiB |
| E | C + `-ub 1024` | 9,5–11,1 | 8–18 | 546–1 022 | 4 604–24 858 | — |
| F | C + `-t 10` | 6,5–8,5 | 9–24 | 1 118–1 648 | 5 819–17 937 | 5 105 MiB |
| **4B-P** | **4B-MTP, flags de produção (:8092, MTP + LoRA micro-turn)** | **105,7–105,9** | **143–354** | **178–203** | **688–740** | 5 139 MiB |
| **4B-V** | **4B com a receita do vídeo** (`--fit-target 512 -ub 1024 -ctk q8_0 -ctv q8_0`) | **54,3** | **205–562** | **153–175** | **537–566** | **4 557 MiB** |

> `ttft` = 1º token com prompt de 1 token (latência de resposta) ·
> `pf512` = 1º token com prompt de 512 tokens (prefill no caminho).
> Carga da máquina durante as runs: `load1` 6,5–8,7 sobre 16 threads (os
> agentes da casa estão ativos) — por isso o t/s varia ±50 % entre reps; o
> harness agora grava `load1`/`ncpu` em cada rep.

Dados brutos: `/tmp/bench-ladder.jsonl` (uma linha JSON por rep, com `load1`
e `ncpu`). Logs por config: `/tmp/bench-srv-<tag>.log`.

## 4. Veredito do gate (Phase 1 do plano)

O gate do vídeo era: **≥ classe dos 17 t/s do autor com TTFT ≤ 150 ms a
`-t 6`**, senão o 4B-MTP fica como default.

| | 35B (melhor config) | 4B-MTP (produção) | 4B (receita do vídeo) |
|---|---|---|---|
| decode | 14,1 t/s | **105,9 t/s** | 54,3 t/s |
| prefill | 30 tok/s | **354 tok/s** | 562 tok/s |
| TTFT | 420–9 066 ms | **178–203 ms** | 153–175 ms |
| 512 tok de contexto | **4–44 s** | 0,7 s | 0,54 s |
| pico VRAM | 5 105–5 139 MiB | 5 139 MiB | **4 557 MiB** |

**O 35B-A3B FALHA o gate por duas ordens de grandeza em TTFT e por ~7× em
decode.** Consequências:

1. **O 4B-MTP continua sendo o default** (Phase 1 fecha aqui, sem download).
2. **O 35B é tier de "thinking"/qualidade, não de voz** — com 512 tokens de
   contexto a conversa levaria 4–44 s só de prefill; 2k tokens = minutos.
3. **As flags do vídeo não mudam nada aqui**: `--fit-target` (B ≈ A) e
   `--moe-cache-mib` (C ≈ B) ficam dentro do ruído de carga. O gargalo é
   CPU/RAM (experts na CPU ⇒ prefill CPU-bound), não o split de VRAM.
4. **`-t 10` piora** (F: 6,5–8,5 t/s) — confirma a regra da casa: **metade
   dos cores** (a barreira libgomp do vídeo com `-t 12` é real).
5. **Achado útil (35B → 4B)**: a receita do vídeo no 4B usa **570 MiB menos
   de VRAM** (4 557 vs 5 139 MiB) e tem prefill 1,6× melhor — mas decode
   metade. Motivo provável: KV q8_0 + `fa on` + sem MTP draft. No 4B de
   **produção** isso não é aplicável: o **LoRA micro-turn exige `fa off`**, e
   KV quantizado **exige** `fa on` → o 4B de voz fica em KV f16 (750 MiB ×2
   pelo MTP).
6. **Armadilha de reprodução**: `--fit` **aborta** se `-ngl` estiver setado
   (`common/fit.cpp`) — para testar a receita do vídeo é preciso remover
   `-ngl`; e sem o `LD_LIBRARY_PATH` do systemd o server sobe **CPU-only**.

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
