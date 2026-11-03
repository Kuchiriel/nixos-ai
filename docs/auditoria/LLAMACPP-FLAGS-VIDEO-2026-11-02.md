# Flags llama.cpp: a receita do vídeo `tek-IY9BRWc` vs a nossa placa (2026-11-02)

Status: **medido, com decisão**. Evidência bruta: `docs/BENCH-35B-LADDER-2026-11-02.md`
(peer `coord-naming`, commit 89c844f2). Harness: `scripts/bench-llm.sh`
(TTFT + guard CUDA + load logging, commits 8406c1a4 / 89c844f2).

## 1. Pergunta

O vídeo "What's the Best AI Model Your GPU Can Actually Run?" (4–16 GB VRAM) propõe
uma receita de flags para MoE em GPU pequena: `--fit` (auto-fit), `--fit-target MiB`
(margem por device), cache de experts na GPU, KV em q8_0, `-ub 1024`, threads = meio
dos P-cores. A pergunta: **essa receita ganha na nossa RTX 4050 6 GB?**

## 2. Resposta: não (no 35B), e o gargalo é CPU/RAM

| config (35B-A3B UD Q4_K_M, stock 1087, `-t 6`) | decode t/s | prefill t/s | TTFT (1 tok ctx) | 1o tok c/ 512 tok ctx | VRAM pico |
|---|---|---|---|---|---|
| A produção (`-ngl 45 --n-cpu-moe 35 -t 6 -c 32768 -b512 -ub512`) | 8,0–13,4 (24,6 isolado) | 7–19 | 450–1979 ms | 5,9–43,8 s | — |
| B `--fit-target 512` (auto-fit, **sem** `-ngl`) | 11,8–14,1 | 12–30 | 420–634 ms | 4,0–25,0 s | — |
| C B + `--moe-cache-mib 2048` | 9,8–11,2 | 13–19 | 703–1043 ms | 9,0–17,8 s | 5105 MiB |
| D C + `-ctk q8_0 -ctv q8_0` | 6,8–10,4 | 7–21 | 1266–9066 ms | 6,5–24,0 s | 5139 MiB |
| E C + `-ub 1024` | 9,5–11,1 | 8–18 | 546–1022 ms | 4,6–24,9 s | — |
| F C + `-t 10` | 6,5–8,5 | 9–24 | 1118–1648 ms | 5,8–17,9 s | 5105 MiB |

4B-MTP (produção, `:8092`, c20480, KV f16): **105,9 t/s**, pp 143–354, TTFT 178–203 ms,
pf512 688–740 ms, VRAM 5139 MiB.
4B receita do vídeo (fit512, ub1024, KV q8_0, sem MTP): 54,3 t/s, pp 205–562,
TTFT 153–175 ms, pf512 537–566 ms, VRAM 4557 MiB.

Vereditos:

1. **Gate do vídeo (≥17 t/s **e** TTFT ≤150 ms) FALHA no 35B** — melhor caso 14,1 t/s
   com load; TTFT 420–9066 ms; 512 tokens de contexto = 4–44 s de prefill.
   → **o 35B não serve para voz** (gate de TTFT). Ele fica como **tier de thinking**.
2. **`--moe-cache-mib` e `--fit-target` não mudam o resultado** (C ≈ B): o problema não é
   o split de VRAM, é CPU/RAM (experts na RAM, prefill CPU-bound).
3. **KV q8_0 no 35B piora o TTFT** (D: 1266–9066 ms) — não adotar.
4. **`-t 10` é pior que `-t 6`** (F) — confirma a regra da casa: `-t` = P-cores
   (6P+4E nesta CPU; `lscpu` reporta "8").
5. **No 4B, a produção ganha em velocidade** (105,9 vs 54,3 t/s — o MTP draft faz a
   diferença) e a receita do vídeo ganha em **~580 MiB de VRAM** (4557 vs 5139 MiB).
   → mantém-se a produção; a receita do vídeo fica documentada como **fallback de VRAM**
   (se router + embeddings + rerank passarem a coexistir, 580 MiB resolvem a aperto).

## 3. Quem tem o quê (matriz de flags por binário)

| binário | `--fit-target` | `--moe-cache-mib` | `--n-cpu-moe` | notas |
|---|---|---|---|---|
| `llama.cpp/build-stock` (0.7.0-dev, build 1087) | sim | sim | sim | **único com a receita completa** |
| `ik_llama.cpp/build` (build 5074) | **não** | sim | sim | o que roda hoje nos tiers MoE |
| `prism-bin/llama-prism-b10660/b10743` | sim | **não** | n/d | prism = ternário; proibido em MoE (2–3 t/s) |
| nixpkgs `llama-cpp-0.5.0` | sim | **não** | n/d | build antigo |
| `~/projects/llama.cpp/build` | — | — | — | **caminho inexistente** (o dir é `build-stock/`) |

Consequência: adotar a receita do vídeo exigiria trocar o binário dos tiers MoE
(ik → stock). É troca de flag/binário de produção → **decisão do dono**, não patch
silencioso.

## 4. Armadilhas de medição (já blindadas no harness)

- **`--fit` aborta se `-ngl` estiver setado** (`common/fit.cpp`: "n_gpu_layers already set
  by user"). A receita do vídeo *exige* remover o `-ngl` — logo, com a receita de
  produção, o auto-fit nunca roda.
- **Sem o `LD_LIBRARY_PATH` do systemd o server sobe CPU-only** (stub CUDA): 3,2 t/s
  em vez de 24 — leitura de benchmark Mentira. O harness agora **aborta** nesse caso
  (commit 8406c1a4). Qualquer número de t/s só vale se o servidor veio do systemd.
- **Nunca medir com outro processo pesado na máquina**: 24,6 t/s vira 8,0 t/s com um
  agente ativo (contentão de CPU). Medição exige load 6,5–8,7 de 16 threads.

## 5. Decisão aplicada

- `modules/ai/models.nix` **mantém** as receitas de produção (4B-MTP default, 35B = tier
  de thinking). Nenhuma flag nova entra por default.
- Comentário no bloco do 35B registra o veredito + o link desta auditoria, para a
  próxima geração não repetir a ladder.
- Fica pendente de **decisão do dono**: (a) trocar o binário dos tiers MoE para stock
  (build 1087) e remover o `-ngl` com `--fit-target 512` (ganho medido: B vs A);
  (b) usar a receita do vídeo no 4B se a VRAM apertar (−580 MiB, −51 t/s).

## 6. Fontes

- Vídeo: `tek-IY9BRWc` (transcrição em `/tmp/opencode/tek/{en,pt}.txt`).
- Evidência bruta da ladder: `docs/BENCH-35B-LADDER-2026-11-02.md`.
- Flags por build: `--help` de cada binário (medido 2026-11-02).
- Vídeo original do agente: `plans/MISSIONS-2026-11-02.md`.
