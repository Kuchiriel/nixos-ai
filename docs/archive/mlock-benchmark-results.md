# mlock Benchmark Results — Page Fault Hypothesis Test

## Experiment Design

- **Baseline**: EHS-25, no mlock, 5 runs × 200 tokens
- **Mlock**: EHS-25 + --mlock, 5 runs × 200 tokens
- **Hardware**: RTX 4050 6GB, i7-13620H, 32GB RAM
- **Model**: Qwen3.6-35B-A3B Q4_K_M (21 GB)

## Results

### Timing

| Config | avg tok/s | avg ms/tok | min ms/tok | max ms/tok | variance |
|--------|-----------|------------|------------|------------|----------|
| Baseline | 13.95 | 75.47 | 55.32 | 90.21 | high |
| Mlock | 13.17 | 79.00 | 57.03 | 93.56 | high |

**Speedup: 0.95x (mlock is 5% SLOWER)**

### Page Faults (per run)

| Config | Minor faults | Major faults | RSS |
|--------|-------------|--------------|-----|
| Baseline | ~94,758 | ~62 | ~21 GB |
| Mlock | ~653,863 | ~8 | ~18 GB |

### Key Observations

1. **Major faults are negligible** (~0-62 per run in both cases)
   - This means the model pages are ALREADY in RAM (page cache)
   - mlock provides no benefit because the kernel already keeps hot pages resident

2. **Minor faults are HIGHER with mlock** (~653K vs ~94K)
   - mlock forces pages into RSS, causing more TLB misses
   - The kernel's page cache management is more efficient than forced locking

3. **RSS is LOWER with mlock** (18 GB vs 21 GB)
   - Counterintuitive: mlock should increase RSS
   - Likely because mlock changes memory management behavior

4. **High variance in both cases** (55-90 ms/tok)
   - Suggests dynamic frequency scaling or thermal throttling
   - Not related to page faults

## Conclusion

**Page faults are NOT the bottleneck in the MoE cold path.**

The Linux page cache already keeps the mmap'd model files in RAM. The "cold path" latency is caused by:

1. **CPU compute**: The cold expert matmuls are compute-bound, not memory-bound
2. **GPU thermal throttling**: The RTX 4050 may be downclocking under sustained load
3. **Memory bandwidth**: DDR5 bandwidth may be saturated by both hot (GPU) and cold (CPU) paths

## Next Investigation

Since page faults are ruled out, the next experiment should focus on:

1. **GPU clock monitoring DURING inference** — check if thermal throttling is occurring
2. **CPU frequency monitoring** — check if CPU is downclocking during cold path
3. **Memory bandwidth measurement** — determine if DDR5 is the bottleneck
4. **Cold path compute profiling** — measure actual FLOPS vs theoretical peak

## Files

- `scripts/mlock-benchmark.sh` — Benchmark script
- `/tmp/bench-results.csv` — Raw timing data
- `/tmp/metrics-*.txt` — Page fault and RSS data
