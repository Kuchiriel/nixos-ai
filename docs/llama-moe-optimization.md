# MoE Expert Cache Optimization Analysis

## Hardware Profile

| Component | Specification |
|-----------|---------------|
| GPU | NVIDIA RTX 4050 Laptop (6GB VRAM, sm_89) |
| CPU | Intel i7-13620H (14 cores, 6P+8E) |
| RAM | 32GB DDR5 |
| PCIe | 4.0 x8 (laptop) |
| Backend | CUDA 13.2, Driver 595.71 |

## Model Profile

| Parameter | Value |
|-----------|-------|
| Model | Qwen3.6-35B-A3B Q4_K_M |
| Total Size | 20.6 GiB |
| Total Params | 34.66 B |
| Active Params | ~3 B per token |
| Layers | 48 |
| Experts per Layer | 64 (3B active = ~3 experts used) |
| Expert Weight per Layer | ~430 MB (Q4_K_M) |
| Total Expert Weights | ~20 GB |
| Dense Weights (attn+ffn) | ~0.6 GB |

## Current Configuration

```nix
# modules/ai/models.nix → profiles.host
{
  gpuLayers = 45;        # 45/48 layers on GPU
  moeFlags = "--n-cpu-moe 99 --split-mode layer --poll 50 --poll-batch 50";
  kvCache = "-ctk q4_0 -ctv q4_0";
  ctxSize = 196608;
  threads = 12;
  batchSize = 1024;
  ubatch = 1024;
}
```

## Baseline Performance

| Metric | Value |
|--------|-------|
| PP (prompt processing) | 206-207 tok/s |
| TG (text generation) | 15-16 tok/s |
| VRAM Used | ~3 GB (dense layers + KV cache + compute) |
| RAM Used | ~20 GB (expert weights) |

## Architecture Analysis

### How MoE Expert Offloading Works

1. **Tensor Buffer Overrides**: `--n-cpu-moe N` forces N expert layers to CPU via regex pattern matching:
   ```
   blk\.\d+\.ffn_(up|down|gate_up|gate)_exps
   ```

2. **MUL_MAT_ID**: The core operation that:
   - Takes expert weights (src0), activations (src1), and expert IDs (ids)
   - Selects which experts to compute
   - Performs batched matrix multiplication per expert

3. **Split Mode**: `--split-mode layer` assigns entire layers to GPU or CPU. Expert weights within a layer go together.

4. **Execution Flow**:
   ```
   Token → Attention (GPU) → Router (GPU) → Expert Selection (GPU)
   → MUL_MAT_ID (CPU for offloaded experts) → Output
   ```

### VRAM Budget Analysis

```
Total VRAM:           6,141 MiB
─────────────────────────────────
Dense layers (45):    ~2,000 MiB
KV cache (q4_0):      ~  800 MiB
Compute buffer:       ~  500 MiB
CUDA overhead:        ~  200 MiB
─────────────────────────────────
Used:                 ~3,500 MiB
Available:            ~2,641 MiB

Expert cache budget:  ~1,000-1,500 MiB (20-30% of expert weights)
```

### Expert Weight Calculation

```
Expert weights per layer:
  ffn_up_exps:   n_embd × n_ff_exp × n_expert × Q4_K_M_size
  ffn_gate_exps: n_embd × n_ff_exp × n_expert × Q4_K_M_size
  ffn_down_exps: n_ff_exp × n_embd × n_expert × Q4_K_M_size

For Qwen3.6-35B-A3B:
  n_embd = 4096
  n_ff_exp = 1024 (estimated)
  n_expert = 64
  Q4_K_M byte per param ≈ 0.5 bytes

  Per layer ≈ 3 × 4096 × 1024 × 64 × 0.5 ≈ 400 MB
  Total (48 layers) ≈ 19.2 GB
```

## Optimization Opportunities

### 1. Expert Cache (RFC #24528)

**Concept**: Keep "hot" experts in VRAM, compute misses on CPU.

**Feasibility on RTX 4050**: BORDERLINE
- Can fit ~1-1.5 GB of expert cache
- Need ~20-30% of expert weights for meaningful hit rate
- RFC shows 7-57% improvement on 4× RTX 3090
- Single GPU with limited VRAM: may regress (see GTX 1080 Ti results)

**Key Insight from RFC**:
> "You want enough VRAM spare for cache (after placing ALL dense layers on a GPU), that you can fit experts working set there (so around 20%-30% of MoE expert weights)."

**Our situation**: 
- 2.6 GB available VRAM
- 20-30% of expert weights = 3.8-5.7 GB
- **Cannot fit the required working set**

### 2. Thread Count Optimization

**Finding**: Fewer threads = better TG on this hardware

| Threads | TG (tok/s) | Notes |
|---------|------------|-------|
| 6 | 16.77 | Best |
| 8 | 15.13 | |
| 10 | 14.88 | |
| 12 | 14.75 | Current config |
| 14 | 14.57 | |

**Why**: E-core threads on i7-13620H may cause contention. The 6 P-cores are faster than 8 E-cores for memory-bound MoE workloads.

### 3. Poll Settings

`--poll` controls CPU-GPU synchronization frequency:
- `--poll 50` (current): 50% of iterations check for GPU completion
- `--poll 0`: Never poll (maximize CPU parallelism)
- `--poll 100`: Always poll (minimize latency)

For MoE decode (CPU-heavy), lower poll may help by reducing synchronization overhead.

### 4. KV Cache Quantization

Already optimal: `q4_0` for both K and V caches. Further reduction would hurt quality.

### 5. Batch Size for Prompt Processing

Current: `-b 1024 -ub 1024`
- Higher batch = faster PP but more VRAM for compute buffer
- Sweet spot depends on prompt length distribution

### 6. Speculative Decoding

llama.cpp supports speculative decoding via:
- MTP (Multi-Token Prediction) draft heads
- Eagle3 draft models
- DFlash draft models

**Benefit for MoE**: Draft model runs entirely on CPU (small, fast), reducing the frequency of expensive MoE forward passes.

### 7. CPU Expert Kernel Optimization

The CPU MUL_MAT_ID kernel in `repack.cpp` could be optimized:
- Better SIMD utilization (AVX-512 on i7-13620H)
- Cache-friendly memory access patterns
- Prefetch expert weights before computation

## Recommended Strategy

Given the 6GB VRAM constraint, the expert cache approach is NOT recommended for this hardware. Instead:

### Priority 1: Thread Optimization (Immediate)
```nix
threads = 6;  # Instead of 12
```
Expected improvement: ~10-15% TG

### Priority 2: Poll Optimization (Immediate)
```nix
moeFlags = "--n-cpu-moe 99 --split-mode layer --poll 25 --poll-batch 25";
```
Expected improvement: ~5-10% TG

### Priority 3: Speculative Decoding (Medium-term)
- Use MTP draft head if available in the GGUF
- Or use a small draft model (Qwen3-4B) for speculative decoding
- Expected improvement: ~20-50% TG (if draft model is accurate)

### Priority 4: Expert Cache (Research Only)
- Only if VRAM increases (e.g., external GPU)
- Or if a smaller model with fewer experts is used
- Current hardware is at the feasibility boundary

## Benchmark Commands

### Baseline
```bash
llama-bench \
  -m Qwen3.6-35B-A3B-UD-Q4_K_M.gguf \
  -ngl 45 -ncmoe 99 -sm layer \
  -t 6 -p 512 -n 128 -r 3 \
  -fa on -ctk q4_0 -ctv q4_0
```

### With Thread Optimization
```bash
llama-bench \
  -m Qwen3.6-35B-A3B-UD-Q4_K_M.gguf \
  -ngl 45 -ncmoe 99 -sm layer \
  -t 6 -p 512 -n 128 -r 3 \
  -fa on -ctk q4_0 -ctv q4_0 \
  --poll 25 --poll-batch 25
```

### Expert Cache (Experimental - Not Recommended for This Hardware)
```bash
# Requires custom build with moe-cache patch
llama-bench \
  -m Qwen3.6-35B-A3B-UD-Q4_K_M.gguf \
  -ngl 45 -ncmoe 99 -sm layer \
  -t 6 -p 512 -n 128 -r 3 \
  -fa on -ctk q4_0 -ctv q4_0 \
  --moe-cache 1024  # 1GB cache budget
```

## References

1. [RFC: MoE expert cache](https://github.com/ggml-org/llama.cpp/discussions/24528)
2. [Lidenburg fork: MoE expert caching](https://github.com/Lidenburg/llama.cpp)
3. [HuggingFace MoE offload guide](https://huggingface.co/blog/Doctor-Shotgun/llamacpp-moe-offload-guide)
4. [llama.cpp MoE discussions](https://github.com/ggml-org/llama.cpp/discussions/12781)
5. [CPU-MoE and Qwen3-Coder](https://llmkube.com/blog/hybrid-moe-offloading-qwen-36-deltanet)

## Conclusion

With 6GB VRAM on RTX 4050, the expert cache optimization is at the feasibility boundary. The recommended approach is:

1. **Thread optimization** (immediate, ~10-15% improvement)
2. **Poll tuning** (immediate, ~5-10% improvement)
3. **Speculative decoding** (medium-term, ~20-50% improvement)
4. **Expert cache** (research only, requires more VRAM)

The current configuration (ngl=45, ncmoe=99) is already near-optimal for this hardware. Further gains require either:
- More VRAM (external GPU, RTX 4060+ with 8GB)
- Speculative decoding with accurate draft model
- Model quantization improvements (smaller expert weights)
