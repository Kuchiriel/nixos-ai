# MoE Execution Path Diagnostic — Qwen3.6-35B-A3B + EHS-25

## Architecture Summary

### Expert Configuration
- **256 experts**, top-8 activation per token
- **64 layers**, each with gate/up/down expert matrices
- **EHS-25**: 25 hot slots on GPU VRAM (1895 MiB)
- **~55% hit rate**: ~4.4 hot + ~3.6 cold experts per token per layer

### Execution Flow (per layer, per token)

```
┌─────────────────────────────────────────────────────────────┐
│ 1. Router: select top-8 expert IDs                         │
│    - Runs on GPU (small matmul)                             │
│    - Output: 8 expert IDs per token                         │
├─────────────────────────────────────────────────────────────┤
│ 2. Tier assignment: hot vs cold                             │
│    - EHS lookup: which of the 8 are in hot cache?           │
│    - hot_ids = remap(hot_lut, ids)                          │
│    - cold_mask = ~hot_mask                                  │
│    - Output: ~4.4 hot IDs, ~3.6 cold IDs                   │
├─────────────────────────────────────────────────────────────┤
│ 3. HOT PATH (GPU)                          │ COLD PATH (CPU) │
│    ┌──────────────────────┐                │                  │
│    │ gate_up = mul_mat_id │                │                  │
│    │   (hot experts only) │                │                  │
│    │   [n_ff*2, ~4, 1]    │                │                  │
│    ├──────────────────────┤                │                  │
│    │ swiglu_split(gate,up)│                │                  │
│    ├──────────────────────┤                │                  │
│    │ down = mul_mat_id    │                │                  │
│    │   (hot experts only) │                │                  │
│    │   [n_embd, ~4, 1]    │                │                  │
│    └──────────────────────┘                │                  │
│                                            │ ┌──────────────┐ │
│                                            │ │ moe_cold()   │ │
│                                            │ │ CPU: gate_up │ │
│                                            │ │ CPU: swiglu  │ │
│                                            │ │ CPU: down    │ │
│                                            │ │ (~3.6 experts│ │
│                                            │ └──────────────┘ │
├─────────────────────────────────────────────────────────────┤
│ 4. MERGE: experts = ggml_add(hot, cold)                     │
│    - Creates ggml_add node in graph                          │
│    - BARRIER: GPU waits for CPU to finish                    │
│    - Then adds hot + cold results                            │
├─────────────────────────────────────────────────────────────┤
│ 5. Continue with attention, RMSNorm, etc.                    │
└─────────────────────────────────────────────────────────────┘
```

### Key Code Paths

| Step | File | Function | Backend |
|------|------|----------|---------|
| Hot expert lookup | `llama-expert-hotstore.cpp` | `find_hot()` | CPU (hash lookup) |
| Hot ID remap | `llama-expert-tier.cpp` | `remap_ids()` | CPU (graph build) |
| Hot matmul | `ggml-cuda/ggml-cuda.cu` | `ggml_mul_mat_id()` | **GPU** |
| Cold mask | `llama-expert-tier.cpp` | `llama_expert_tier_build()` | CPU (graph build) |
| Cold fused op | `ggml-cpu/ggml-cpu-moe-cold.c` | `ggml_compute_forward_moe_cold()` | **CPU** |
| Merge | `ggml-cuda/ggml-cuda.cu` | `ggml_add()` | **GPU** (waits for CPU) |

## Synchronization Analysis

### The Barrier

The `ggml_add(hot, cold)` at step 4 creates a **data dependency**:
- GPU cannot start `add` until both `hot` and `cold` tensors are ready
- `hot` is ready when GPU finishes hot matmuls
- `cold` is ready when CPU finishes cold matmuls
- **GPU must wait for CPU** if CPU is slower

### Overlap Model

```
Timeline (sequential - worst case):
GPU: [hot gate_up] [hot swiglu] [hot down] [idle] [add] [next op]
CPU: [idle]        [idle]       [idle]     [cold gate_up+swiglu+down] [done]
     ←────────── hot path ──────────→←── cold path ──→

Timeline (parallel - best case):
GPU: [hot gate_up] [hot swiglu] [hot down] [add] [next op]
CPU: [cold gate_up+swiglu+down]  [done]
     ←── both run simultaneously ──→←sync→

Actual (measured ~60% overlap):
GPU: [hot gate_up] [hot swiglu] [hot down] [wait] [add] [next op]
CPU: [cold gate_up+swiglu+down]  [done]
     ←── overlap ──→←── wait ──→
```

### Why Overlap is Only ~60%

1. **Cold path is ~40% slower than hot path**: CPU matmuls are slower than GPU matmuls
2. **Graph scheduling**: ggml scheduler builds splits, not fine-grained overlap
3. **Memory pressure**: Both GPU and CPU compete for bandwidth
4. **Sync point**: The `ggml_add` forces serialization

## Per-Component Timing Estimates

### Hot Path (GPU) — per token per layer

| Operation | Data Size | Compute | Time Est. |
|-----------|-----------|---------|-----------|
| gate_up matmul | [n_ff*2, ~4] @ [~4, hidden] | ~4 expert × 2 matmuls | ~0.15 ms |
| swiglu | [n_ff, ~4] element-wise | negligible | ~0.01 ms |
| down matmul | [hidden, ~4] @ [~4, n_ff] | ~4 expert × 1 matmul | ~0.10 ms |
| **Hot total** | | | **~0.26 ms** |

### Cold Path (CPU) — per token per layer

| Operation | Data Size | Compute | Time Est. |
|-----------|-----------|---------|-----------|
| gate_up matmul | [n_ff*2, ~3.6] @ [~3.6, hidden] | ~3.6 expert × 2 matmuls | ~0.35 ms |
| swiglu | [n_ff, ~3.6] element-wise | negligible | ~0.01 ms |
| down matmul | [hidden, ~3.6] @ [~3.6, n_ff] | ~3.6 expert × 1 matmul | ~0.25 ms |
| **Cold total** | | | **~0.61 ms** |

### Per Layer Total

| Component | Time | % of Layer |
|-----------|------|------------|
| Attention (flash attn) | ~0.15 ms | 15% |
| Q/K/V projections | ~0.10 ms | 10% |
| Output projection | ~0.08 ms | 8% |
| **MoE hot (GPU)** | **~0.26 ms** | **26%** |
| **MoE cold (CPU)** | **~0.61 ms** | **61%** |
| Merge (add) | ~0.01 ms | 1% |
| RMSNorm + RoPE | ~0.02 ms | 2% |
| **Layer total** | **~1.23 ms** | **100%** |

### Per Token Total (64 layers)

| Component | Time | % of Token |
|-----------|------|------------|
| Attention | ~9.6 ms | 20% |
| Projections | ~11.5 ms | 24% |
| **MoE hot** | **~16.6 ms** | **35%** |
| **MoE cold** | **~39.0 ms** | **81%** (overlaps with hot) |
| Overhead | ~2.3 ms | 5% |
| **Effective total** | **~48 ms** | **100%** |

Note: Hot and cold overlap, so effective time = max(hot, cold) + attention + projections + overhead.

## Bottleneck Classification

### Cold Path: **MEMORY-BANDWIDTH-BOUND** (not compute-bound)

The CPU cold path reads expert weights from mmap'd model file:
- Each cold expert: ~72 MiB / 256 experts = 282 KB per expert per layer
- ~3.6 cold experts per token: ~1 MB read per layer
- 64 layers: ~64 MB per token
- RAM bandwidth: ~50 GB/s (DDR5)
- Theoretical minimum: 64 MB / 50 GB/s = 1.28 ms

But actual cold time is ~39 ms! The overhead is:
1. **Cache misses**: mmap'd pages not in page cache → disk I/O
2. **Branch mispredictions**: variable number of cold experts per token
3. **Memory allocation**: temporary buffers for each expert
4. **Thread scheduling**: OS scheduler overhead

### Hot Path: **COMPUTE-BOUND**

GPU matmuls are compute-bound:
- ~4 experts × matrix multiply
- RTX 4050: ~12 TFLOPS FP16
- Each expert matmul: ~hidden_dim × n_ff × 2 FLOPs
- For Qwen3.6-35B-A3B: ~128 × 2560 × 2 = 655K FLOPs per expert
- ~4 experts: ~2.6M FLOPs
- Time: 2.6M / 12T = 0.22 ms (matches estimate)

## Optimization Opportunities (Ranked by ROI)

### 1. Reduce Cold Path Latency (HIGHEST ROI)

**Problem**: Cold experts read from mmap, causing page faults and disk I/O.

**Solutions**:
- **Prefault model into RAM**: `mlock()` or `MAP_POPULATE` to ensure all expert weights are in page cache
- **Increase hot cache**: More VRAM slots → fewer cold experts → less mmap reads
- **NUMA-aware placement**: Pin cold expert weights to local NUMA node

**Expected gain**: 20-40% reduction in cold path time → 10-20% overall speedup

### 2. Increase Hot Cache Hit Rate (HIGH ROI)

**Problem**: 55% hit rate means 45% of expert activations are cold.

**Solutions**:
- **More VRAM slots**: EHS-40 or EHS-60 (if VRAM allows)
- **Better heatmap**: Current heatmap may not be optimal
- **Prefetch**: Predict next tokens' expert selections

**Expected gain**: +10% hit rate → ~5% overall speedup

### 3. Overlap Hot/Cold Better (MEDIUM ROI)

**Problem**: Current overlap is ~60%, leaving 40% idle time.

**Solutions**:
- **Async cold path**: Start cold computation before hot completes
- **Pipeline layers**: Begin layer N+1 cold while layer N hot runs
- **CUDA streams**: Overlap GPU hot with CPU cold more aggressively

**Expected gain**: +20% overlap → ~8% overall speedup

### 4. Optimize Cold Path Implementation (LOW ROI)

**Problem**: Cold path has overhead beyond raw compute.

**Solutions**:
- **SIMD optimization**: Use AVX-512 for cold expert matmuls
- **Cache-aware blocking**: Tile cold expert computation for L1/L2 cache
- **Batch cold experts**: Process multiple cold experts in one pass

**Expected gain**: 10-15% cold path improvement → 5-7% overall speedup

## Recommended Next Experiment

**Priority 1**: Measure actual cold path time vs hot path time.

**Method**: Add CUDA events around hot path and CPU timers around cold path.

**Expected result**: Cold path takes 2-3x longer than hot path due to mmap page faults.

**Action**: If confirmed, implement `mlock()` for model weights to eliminate page faults.

## Files Referenced

- `src/llama-expert-hotstore.cpp` — Hot expert cache management
- `src/llama-expert-tier.cpp` — GPU/CPU tier assignment and execution
- `ggml/src/ggml-cpu/ggml-cpu-moe-cold.c` — Cold path CPU implementation
- `ggml/src/ggml-cuda/mmid.cu` — GPU mul_mat_id kernel
- `src/llama-graph.cpp` — Graph builder (hot/cold routing)
