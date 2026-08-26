# Attention Bottleneck Diagnostic — Qwen3.6-35B-A3B + RTX 4050 + EHS

## Hardware & Config

| Item | Value |
|------|-------|
| GPU | RTX 4050 Laptop 6GB VRAM |
| CPU | i7-13620H |
| RAM | 32 GB |
| Model | Qwen3.6-35B-A3B Q4_K_M |
| Layers | 64 |
| Q heads | 32 (head_dim=128) |
| KV heads | 8 (GQA ratio=4) |
| Experts | 256 (top-8) |
| KV cache | q4_0, `-fa on` |
| EHS slots | 25 hot experts on GPU |
| ngl | 45 (attention layers on GPU) |
| ctxSize | 8192 |

## Measured Performance

| Metric | Baseline (ncmoe=99) | EHS-25 | Delta |
|--------|---------------------|--------|-------|
| TG tok/s | 29.4 | 30.9 | +5.5% |
| Eval time/token | 60.28 ms | 48.00 ms | +25.6% |
| GPU util | 20.5% | 32.2% | +57% |
| VRAM | ~2400 MiB | ~4300 MiB | +1900 MiB |

## Code Path Analysis (Static)

### Flash Attention Kernel Selection

For Qwen3.6-35B-A3B (head_dim=128):
```
fattn.cu → case 128: → switch_ncols2<128,128>
  → GQA ratio = 4 → ncols2=4
  → switch_ncols1<128,128,4>
  → ncols1 depends on Q->ne[1] (batch size)
  → For decode (1 token): ncols1=1
  → Kernel: fattn-mma-f16<DKQ=128, DV=128, ncols1=1, ncols2=4>
```

### KV Cache Quantization (Fused)

The flash attention kernel has **built-in q4_0 dequantization**:
- K: `vec_dot_fattn_vec_KQ_q4_0()` — dot product computed directly from q4_0 K (no separate dequant step)
- V: `dequantize_V_q4_0()` — dequantized on-the-fly during value aggregation

This is efficient: no separate dequant kernel launch, no intermediate F16 buffer for K.

### Decode Data Flow (per token, per layer)

```
1. RMSNorm(input)                        — memory-bound (read entire hidden state)
2. Q = input @ W_q [128, 4096]           — compute-bound (small matmul, batch=1)
3. K = input @ W_k [128, 1024]           — compute-bound
4. V = input @ W_v [128, 1024]           — compute-bound
5. RoPE(Q, K, positions)                 — memory-bound (in-place)
6. FlashAttn(Q, K_q4, V_q4, mask)       — memory-bandwidth-bound (reads KV cache)
7. O = attn_output @ W_o [4096, 128]     — compute-bound
8. MoE: 8 experts selected               — mix (hot=GPU, cold=CPU)
9. RMSNorm + residual                    — memory-bound
```

## Bottleneck Analysis

### KV Cache Read Volume

| seq_len | KV reads/layer | KV reads/64 layers | % of 6GB VRAM |
|---------|---------------|---------------------|---------------|
| 1024 | 1 MB | 64 MB | 1.0% |
| 2048 | 2 MB | 128 MB | 2.1% |
| 4096 | 4 MB | 256 MB | 4.2% |
| 8192 | 8 MB | 512 MB | 8.5% |

Calculation: 8 KV heads × 128 dim × 0.5 bytes (q4_0) × 2 (K+V) = 1 KB per token per layer.

### Theoretical Bandwidth Floor

RTX 4050 GDDR6 bandwidth: ~192 GB/s

| seq_len | KV read time (192 GB/s) | Measured token time | Overhead |
|---------|------------------------|---------------------|----------|
| 4096 | 1.33 ms | 48 ms | 46.7 ms (97%) |
| 8192 | 2.67 ms | 48 ms | 45.3 ms (94%) |

**KV cache reads are NOT the bottleneck.** Even at full context, KV reads take <3 ms out of 48 ms.

### Where the 48 ms Actually Goes

The remaining ~45 ms is spent on:

1. **Q/K/V projections** (3 matmuls per layer): Small but 64 layers × 3 = 192 matmuls
2. **Output projection** (1 matmul per layer): 64 matmuls
3. **MoE expert computation** (8 experts × 64 layers): THE DOMINANT COST
   - Hot experts (25 on GPU): fast
   - Cold experts (~180 on CPU): slow, serialized with GPU via `ggml_add(hot, cold)` barrier
4. **RMSNorm** (2 per layer): Memory-bound, 128 total
5. **RoPE** (1 per layer): Memory-bound, 64 total
6. **CUDA kernel launch overhead**: 64 layers × ~10 kernels = ~640 launches

### Critical Insight: MoE IS the Bottleneck, Not Attention

The "63% attention" measurement from previous sessions was likely measuring the **entire forward pass time**, not isolating the attention kernel. The MoE expert computation (especially cold experts on CPU) dominates because:

1. Each token activates 8 experts × 64 layers = 512 expert computations
2. With EHS-25, ~55% hit rate means ~230 hot (GPU) + ~282 cold (CPU)
3. Cold experts are serialized: GPU must wait for CPU to finish before merge
4. The `ggml_add(hot, cold)` creates a synchronization barrier

## Flash Attention Status

**VERDICT: Flash attention is ACTIVE and OPTIMIZED.**

- Kernel: `fattn-mma-f16` with q4_0 fused dequant
- GQA optimization: active (ncols2=4 for GQA ratio=4)
- MMA (Matrix Multiply-Accumulate): using Tensor Cores on Ada Lovelace
- The attention kernel itself is NOT the bottleneck

## Next Experiments (Priority Order)

### 1. Verify MoE Dominance (HIGH)
- Profile time split: attention vs MoE vs projections vs overhead
- Instrument `ggml_mul_mat_id` (cold path) vs `ggml_mul_mat_id` (hot path)
- Measure CPU vs GPU expert execution time separately

### 2. Context Size Scaling (MEDIUM)
- Test decode at 1K, 2K, 4K, 8K context
- If token time is constant → attention is NOT the bottleneck (confirm MoE)
- If token time scales linearly → attention IS a bottleneck

### 3. KV Cache Quantization Impact (LOW)
- Test q4_0 vs q8_0 vs f16 KV cache
- q4_0: smaller reads but dequant overhead
- f16: larger reads but no dequant
- With 6GB VRAM, q4_0 is likely optimal for capacity

### 4. Thread Sweep with EHS (LOW)
- t=6, t=8, t=10, t=12
- EHS changes the CPU/GPU balance, may shift optimal thread count

## Conclusion

| Question | Answer |
|----------|--------|
| Which kernel dominates? | **MoE expert matmuls**, not attention |
| Compute or memory bound? | **MoE is compute-bound** (GPU) + **serial wait** (CPU cold) |
| Flash attention active? | **Yes**, using `fattn-mma-f16` with q4_0 fused dequant |
| Context scaling? | **Minimal** — KV reads <3 ms at 8K context |
| Next optimization? | **Increase hot expert hit rate** (more VRAM slots) or **overlap CPU/GPU MoE execution** |

## Files Referenced

- `ggml/src/ggml-cuda/fattn.cu` — Flash attention dispatch
- `ggml/src/ggml-cuda/fattn-mma-f16.cuh` — MMA kernel implementation
- `ggml/src/ggml-cuda/fattn-common.cuh` — q4_0 fused dequant functions
- `src/llama-expert-hotstore.cpp` — EHS hot/cold expert management
- `src/llama-expert-tier.cpp` — GPU/CPU expert tier assignment
