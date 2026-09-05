# llama-cpp Tuning — RTX 4050 6GB / 32GB RAM

## Versão do Pacote

Usamos **llama.cpp 10273** via overlay no flake (nixpkgs tem 9190).

```
# Overlay em flake.nix:
llama-cpp = final.llama-cpp.override { ... };
```

A versão 10273 tem flags NOVAS que não existem no 9190:
- `--load-mode` (substitui `--mlock`/`--mmap` deprecated)
- `--reasoning-preserve` (preserva reasoning trace no histórico)
- `--mcp-servers-json` (MCP inline, formato Cursor)
- `--mtmd-batch-max-tokens` (controle de batching de imagens)
- `--spec-draft-backend-sampling` (offload de sampling para backend)

---

## Causa Raiz da Degradação (32→14 t/s)

### O que acontecia

Com `--mmproj` (vision) habilitado **SEM** `--no-mmproj-offload`:

1. **Request 1**: 32 t/s ✅ (mmproj ainda não carregado em VRAM)
2. **Request 2**: 22 t/s ⚠️ (mmproj carregando em VRAM)
3. **Request 3+**: 14 t/s ❌ (VRAM insuficiente para 50 layers + mmproj)

### Mecanismo

O `mmproj-BF16` (861 MB) é denso e deve ficar na GPU. Mas com 6GB de VRAM:

```
VRAM budget (6141 MiB total):
  50 attention layers: ~3600 MiB
  mmproj BF16:          861 MiB
  KV cache q4_0 128K:  ~500 MiB
  CUDA overhead:        ~200 MiB
  TOTAL:               ~5161 MiB  ← EXCEDE 6141!
```

O `common_fit_params` falha (warning no log) e força tensors para CPU. O primeiro request funciona porque mmproj ainda não ocupa VRAM, mas a partir do segundo, a VRAM estoura e layers são empurrados para CPU.

### Solução: `--no-mmproj-offload`

```nix
"--no-mmproj-offload"  # Força mmproj para CPU
```

- Vision continua funcionando (mmproj carregado)
- mmproj roda em CPU (usa RAM, não VRAM)
- VRAM: 5079→4179 MiB (-900 MiB)
- Todos os 50 layers ficam na GPU
- Decode: **32 t/s estável** (0% drift em 8+ requests)

---

## Flags Importantes (10273)

### `--load-mode` (NOVA — substitui --mmap/--mlock)

```
--load-mode mmap   (default) — memory-map, pages sob demanda
--load-mode mlock  — força modelo em RAM (anti-swap)
--load-mode none   — sem modo especial (leitura direta)
```

**`--load-mode none` causa 19GB RSS** (modelo inteiro em RAM). Usável se tiver RAM sobrando, mas torna o PC lento. `--load-mode mmap` (default) é mais eficiente.

### `--no-mmproj-offload` (CRÍTICO para RTX 4050 6GB)

Força o projetor de visão (mmproj) para CPU. Essencial quando VRAM não comporta layers + mmproj.

### `--reasoning-preserve` (NOVA)

Preserva trace de reasoning no histórico completo, não só na última mensagem. Útil para Qwen3 com thinking.

### `--mcp-servers-json` (NOVA)

Define servidores MCP inline via JSON. Formato compatível com Cursor. Pode simplificar integração MCP.

### Flags testadas (benchmark real, 3 runs + warmup cada)

| Flag | Prefill | Decode | VRAM | Veredito |
|------|---------|--------|------|----------|
| (baseline) | 367 t/s | 31.8 t/s | 4179 MiB | — |
| `--reasoning-preserve` | 367 t/s | 32.4 t/s | 4179 MiB | ✅ **ATIVAR** |
| `--no-op-offload` | **161 t/s↓** | 32.2 t/s | 4043 MiB | ❌ destrói prefill |
| `--no-kv-offload` | 299 t/s↓ | **16.0 t/s↓** | 3165 MiB | ❌ KV na RAM |
| `--cache-reuse 1024` | 367 t/s | **15.6 t/s↓** | 4179 MiB | ❌ degrada decode |
| `--load-mode mlock` | ~370 t/s | 33.0 t/s | 4179 MiB | ⚠️ 20GB RSS |
| `--threads-batch 14` | 369 t/s↑ | 31.9 t/s | — | ⚠️ trade-off |
| `-cram 16384` | 352 t/s↓ | 31.8 t/s | — | ❌ piorou |
| `--spec-type ngram-simple` | 358 t/s | **24.2 t/s↓** | — | ❌ desastroso |
| batch 2048 | 359 t/s↓ | 32.3 t/s | — | ⚠️ prefill ↓ |
| `--cpu-range 0-11` | — | — | — | sem efeito |

---

## Configuração Final (modules/ai/models.nix)

```nix
host = {
  model = "llm-host";
  mmproj = "llm-host-mmproj";  # Vision (CPU com --no-mmproj-offload)
  threads = 16;
  ctxSize = 131072;             # 128K contexto
  batchSize = 1024;
  ubatch = 1024;
  gpuLayers = 50;
  kvCache = "-fa on -ctk q4_0 -ctv q4_0";
  moeFlags = "--n-cpu-moe 50 --split-mode none --poll 50 --poll-batch 50";
  extraArgs = [
    "--no-mmproj-offload"       # CRÍTICO: mmproj na CPU, libera 900MiB VRAM
    "--image-min-tokens" "1024"
    "--kv-unified"              # KV cache unificado
    "--ctx-checkpoints" "2"
    "--keep" "1024"
    "--no-warmup"               # +2% prefill/decode
    "--prio" "2"                # Prioridade high
    "--prio-batch" "3"          # Real-time batch
    "--reasoning-preserve"      # Preserva thinking trace (Qwen3)
  ];
  user = "root";
  scheduler = null;  # CFS default (FIFO removido)
};
```

### Métricas

| Métrica | Valor |
|---------|-------|
| Prefill | 367 t/s |
| Decode | 31.7 t/s |
| VRAM | 4179 MiB / 6141 MiB |
| RAM livre | 27 GB |
| Drift | 1.3% (5 runs) |
| Vision | Funcional (CPU) |

---

## Benchmark Script

`benchmark.sh` agora inclui:
- **Lock** com `flock` (previne concorrência)
- **Pasta** `logs/benchmark/` com timestamps
- **VRAM, RAM, temperatura** em cada run
- **`--warmup`** — 1 run descartado antes do real
- **`--repeat N`** — múltiplos runs
- **Drift detection** — alerta se decode variar >10%
- **JSON consolidado** para análise

---

## Conhecimento NÃO Confirmado

1. **Por que mmproj em CPU não afeta VRAM?** — nvidia-smi mostra a mesma VRAM (4626 MiB) com/sem mmproj. Pode ser que mmproj BF16 seja small o bastante para caber sem afetar显著, ou que o CUDA context sharing seja o problema real.

2. **Por que `--load-mode mmap` (default) degrada mas `--no-mmproj-offload` resolve?** — O mecanismo exato não está 100% claro. Hipótese: mmproj na GPU cria CUDA context que interfere no compute graph do modelo principal.

3. **`--load-mode none` vs `--load-mode mmap`** — A diferença de performance (14 vs 32 t/s) com mmproj na GPU sugere que o modo de carregamento afeta como o CUDA gerencia memória entre modelo e mmproj.

---
**Ver também:** [[slm-techniques]] | [[rag-improvements]] | [[system-overview]]
[[../benchmarks/ncmoe-sweep]] | [[../benchmarks/performance-evidence-audit]]
[[../../HANDOFF]] | [[../../AGENTS.md]] | [[../../README]]
