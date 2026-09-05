# Bonsai Ternary 8B vs Qwen MoE — Benchmark Real (2026-09-05)

> Evidência LEVEL 4 (E2E executado, números observados). Números antigos
> de 32 t/s do Qwen eram de config instável (OOM) — ver §5.

## 1. Método

| Item | Valor |
|------|-------|
| Ferramenta | `prism-bin/llama-prism-b10660-e311ed3/llama-bench` (fork PrismML, CUDA) |
| Servidor live | mesmo binário via `llama-prism-wrapper.sh`, profile `bonsai` |
| Modelo | `Ternary-Bonsai-8B-Q2_0_g64.gguf` (2.15 GiB, prism-ml/Ternary-Bonsai-8B-gguf) |
| Hardware | RTX 4050 Laptop 6GB (cc 8.9), i7-13620H (16 threads), 31GB RAM |
| Servidor flags | `-ngl 99 -c 32768 -t 8 -b 2048 -ub 512 -fa on -ctk q4_0 -ctv q4_0 --parallel 1 --jinja` |

## 2. Resultados

### llama-bench, GPU full offload (`-ngl 99 -p 512 -n 128 -t 8`)

| Métrica | Bonsai 8B | Qwen 35B-MoE (`fast`) |
|---------|-----------|----------------------|
| PP512 | **1955.8 t/s** | ~350 (histórico) |
| TG128 | **76.7 t/s** | ~10 (medido) / 32.5 (config instável) |
| VRAM pesos | 2.15 GiB | ~4.6 GB |

### Servidor live (porta 8080, 5 runs × 128 tokens, ctx 32K)

| Run | PP | TG |
|-----|----|----|
| 1 | 743.8 | 71.4 |
| 2 | 70.0 | 71.7 |
| 3 | 71.4 | 71.5 |
| 4 | 70.2 | 71.6 |
| 5 | 71.4 | 72.0 |

- **TG médio sustentado: 71.6 t/s** (7.2x vs Qwen `fast`).
- VRAM em repouso: 4071 MiB (pesos 2.15GB + KV 32K q4_0 ~1.2GB + buffers).
- Qualidade: resposta PT-BR coerente ("NixOS é um sistema operacional...").
- **Anomalia não explicada**: PP 743 no run 1, ~70 nos runs 2-5; prompt curto
  isolado deu PP 813. TG estável em todos. Hipótese: variação de clock
  (PP é compute-bound, TG é memory-bound). Requer follow-up, não bloqueia uso.

### CPU (`-ngl 0`): **travou** — abortado pelo operador. Sem número. Esperado:
Q2_0 g64 no x86 sem kernels dedicados cai em fallback escalar.

## 3. Falhas encontradas no caminho (reais, corrigidas)

1. `prism-llama.cpp/build/` **não tem executáveis** (só `.so`) — build incompleto.
   Solução: binários pré-compilados em `prism-bin/llama-prism-b10660-e311ed3/`
   (`llama-bench`, `llama-cli`, `llama-server` + `libggml-cuda.so`).
2. Binários prism exigem fora do store: `libcudart`, `libcublas`, `libssl3`,
   `libcrypto3`, `libstdc++6`, `libcuda`. Solução declarativa:
   `environment.LD_LIBRARY_PATH` no `llama-cpp.nix` com
   `stdenv.cc.cc.lib`, `openssl.out`, `cudaPackages.cuda_cudart`,
   `cudaPackages.libcublas.lib` (+ `/run/opengl-driver/lib`).
   Armadilha: `cudaPackages.libcublas` (default output) só tem `src` —
   usar o output **`.lib`**.
3. `llama-cli` do **nixpkgs trava no load** do Q2_0 g64 (>300s sem output).
   Confirma o aviso upstream: Q2_0 g64 ainda fora da mainline
   (PRs #24448 CPU, #25707 CUDA pendentes de merge na versão pinnada).
   Por isso o servidor usa o binário prism via `wrapper`, não o nixpkgs.

## 4. Declarado em `models.nix`

- Modelo `llm-bonsai` (fetchurl + sha256 verificado no rebuild).
- Profile `bonsai` (única fonte de verdade) + enum `bonsai` em `llama-cpp.nix`.
- Host `nitro-v15` com `profile = "bonsai"`.
- Rebuild 2026-09-05: ✅ sucesso, store −18.4 GiB (Qwen MoE removido).
- **Limitação conhecida**: sem mmproj (text-only; `observe_screen` inoperante
  até decisão sobre vision).

## 5. Correção histórica

Os 32 t/s do Qwen citados em notas antigas vieram de config `-ngl 45`
que **crashava após o 1º request (OOM)** — documentado no próprio
`models.nix` (profile `fast`). Config estável (`fast`, `-ngl 25`) entregava
10–13.8 t/s. Comparação honesta: **71.6 vs ~10 t/s = 7.2x**.

**Ver também:** [[../architecture/system-overview]] | [[../architecture/llama-cpp-tuning]]
[[ncmoe-sweep]] | [[performance-evidence-audit]]
