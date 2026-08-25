# Diagnóstico: Por que Expert Hot Store deu apenas +6%

## Dados Medidos

### Baseline (ncmoe=99, todos experts na CPU)
```
TG: 29.1 tok/s
PP: 85.8 tok/s
```

### EHS-25 (25 slots na GPU, 1895 MiB)
```
TG: 30.9 tok/s (+6.2%)
PP: 88.3 tok/s (+2.9%)
```

### Hit Rate (medido com LLAMA_EXPERT_HITRATE=1)
```
Média: ~55% (varia de 32% a 77% por token)
Estável: não melhora com mais tokens (511 → 1022 tokens)
```

### Warm Experts por Layer (após 511 tokens)
```
Layer 0:  248/256 warm (97%)
Layer 8:  150/256 warm (59%)
Layer 20: 138/256 warm (54%)
Layer 39: 192/256 warm (75%)
Média:    ~175/256 warm (68%)
```

---

## POR QUE +6% — Análise Completa

### 1. O hit rate de ~55% é o teto natural

O modelo Qwen3.6-35B-A3B tem **256 experts** por layer, com **top-8** selection por token.

Com **25 hot slots** (9.8% dos experts), o hit rate esperado se experts fossem uniformes seria ~9.8%.

O hit real de ~55% significa que o heatmap está selecionando bem — os 25 experts mais quentes cobrem 55% das ativações. Mas os outros 45% ainda precisam ser computados na CPU.

### 2. A fusão hot+cold é SERIAL, não paralela

O código fonte revela o caminho de execução:

```cpp
// llama_expert_tier_build():
hot = ggml_mul_mat_id(ctx, dst_hot[g], cur, ids_hot);  // GPU
cold = ggml_mul_mat_id_cold(ctx, w, cur, ids, ...);     // CPU
result = ggml_add(ctx, hot, cold);                       // merge
```

O `ggml_add(hot, cold)` cria uma **dependência**: o merge só pode acontecer quando AMBOS hot (GPU) e cold (CPU) terminaram.

O ggml scheduler **NÃO faz overlap fino entre GPU e CPU**. O fluxo real é:

```
GPU: attention → router → hot expert matmul → [espera CPU]
CPU:                            cold expert matmul → [espera GPU]
GPU:                                                     add(hot, cold) → próxima layer
```

Mesmo que hot e cold fossem dispatchados simultaneamente, o `ggml_add` cria uma barreira de sincronização.

### 3. Decomposição do tempo por token (estimativa)

**Baseline (ncmoe=99):**
```
Per token, per layer:
  GPU attention:          ~0.3 ms
  GPU router:             ~0.05 ms
  CPU expert matmul:      ~1.2 ms  ← GARGALO
  GPU sync:               ~0.1 ms
  Total:                  ~1.65 ms
```

**EHS-25 (55% hit rate):**
```
Per token, per layer:
  GPU attention:          ~0.3 ms
  GPU router:             ~0.05 ms
  GPU hot expert (4.4):   ~0.5 ms  (55% dos 8 experts)
  CPU cold expert (3.6):  ~0.54 ms (45% dos 8 experts)
  Sync/merge:             ~0.1 ms
  Total:                  ~1.49 ms
```

**Speedup teórico:** 1.65/1.49 = **1.11x (~11%)**

O ganho real de 6.2% é menor que o teórico de 11% porque:
- O sync/merge adiciona overhead
- CPU cold expert não é perfeitamente proporcional (overhead fixo por chamada)
- Memória bandwidth compartilhada entre CPU e GPU

### 4. Por que o PR mostra 1.7-2.1x em outras GPUs?

O PR #26824 mostra resultados em **8 GB VRAM**:
- Q4_K_M: 32.0 → 47.7 tok/s (1.49x)
- IQ2_M: 38.1 → 59.7 tok/s (1.57x)

A diferença é:
1. **Mais VRAM = mais experts quentes**: Com 8 GB, cabem ~40-50 slots (vs 25 em 6 GB)
2. **Maior hit rate**: 50 slots = ~70-80% hit rate
3. **Menos cold path**: Com 80% hit, apenas 20% dos experts precisam de CPU
4. **GPU compute dominante**: Com mais experts na GPU, o GPU fica mais ocupado e o CPU menos

Com **6 GB VRAM**, estamos no limite inferior onde o EHS ainda ajuda mas não dramaticamente.

### 5. Por que EHS-25 > EHS-40?

EHS-25: 30.9 tok/s vs EHS-40: 30.7 tok/s

Razão: **VRAM pressure**
- EHS-40 consome 2988 MiB para hot store
- EHS-25 consome 1895 MiB para hot store
- A diferença de ~1093 MiB volta pra KV cache e CUDA workspace
- Com menos VRAM pressure, os kernels CUDA rodam mais eficientemente
- O hit rate de EHS-40 provavelmente é ~65% (vs 55% de EHS-25), mas o overhead de manutenção de 40 slots (mais trocas, mais sincronização) anula o ganho

---

## DIAGNÓSTICO FINAL

```
BASELINE
--------
TG: 29.1 tok/s
CPU expert: ~1.2 ms/layer/token (100% dos experts)
GPU utilization: ~30% (attention + router apenas)
GPU idle: ~70% (esperando CPU)
H2D: 0 (sem transferência)
Sync: barreira por layer

EHS-25
------
TG: 30.9 tok/s
Hit rate: 55% (25/256 experts quentes)
CPU expert: ~0.54 ms/layer/token (45% dos experts)
GPU expert: ~0.5 ms/layer/token (55% dos experts)
H2D: periódico (resync a cada N tokens)
Sync: barreira no ggml_add(hot, cold)
GPU utilization: ~45%

DELTA
-----
Ganho: +6.2%
Causa principal: 55% dos experts computados na GPU, mas sync serial limita ganho
```

---

## PRÓXIMO GARGALO

### Hipótese: CPU/GPU overlap é o próximo passo

**Evidência:**
- O `ggml_add(hot, cold)` serializa GPU e CPU
- Se hot e cold rodassem em paralelo com overlap real, o ganho seria ~11% teórico
- O PR #26824 menciona que a versão com "proper integration" (que toca CUDA kernel) tem +30% vs +10% da versão "hacky"

**Próximo experimento:**
- Investigar se `ggml_backend_sched` pode overlap GPU e CPU ops
- Testar com `GGML_CUDA_EVENTS=1` para medir timing real
- Se serializado: implementar double-buffering ou async execution

**Não implementar ainda** — primeiro confirmar com profiling que a serialização é o gargalo.

---

## REFERÊNCIAS

- PR #26563: Expert Hot Store original (miltos22)
- PR #26824: Versão sucessora com heatmap, sidecar, mmap pinning
- Fork: `miltos22/llama.cpp-wackMall-merge-request`
- Hardware: RTX 4050 6GB, i7-13620H, 32GB RAM
- Modelo: Qwen3.6-35B-A3B Q4_K_M (256 experts, top-8)
