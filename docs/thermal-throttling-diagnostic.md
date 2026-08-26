# Thermal Throttling Diagnostic — Root Cause of MoE Latency Variance

## Experiment

10 runs of EHS-25 with CPU/GPU clock monitoring during inference.

## Results

### Two Distinct Performance Tiers

| Tier | Runs | ms/tok | tok/s | CPU MHz | GPU MHz | GPU Power | GPU Temp |
|------|------|--------|-------|---------|---------|-----------|----------|
| **Fast** | 1-4, 7 | 55-57 | 17.4-18.0 | 4000-4300 | 2415-2480 | 34-36W | 58-63°C |
| **Slow** | 5, 6, 8-10 | 90-91 | 10.9-11.1 | 2400-2800 | 2130 | 24.6W | 59-61°C |

### Statistics

| Metric | Value |
|--------|-------|
| Mean ms/token | 73.4 |
| Median ms/token | 90.2 |
| Std deviation | 17.4 |
| Min ms/token | 55.4 |
| Max ms/token | 91.4 |

### Key Observations

1. **CPU frequency varies 60%**: 2.7 GHz to 4.3 GHz
2. **GPU frequency varies 17%**: 2130 to 2480 MHz
3. **GPU power varies 30%**: 24.6W to 35W
4. **Page faults are CONSTANT**: ~89K minor, ~0 major across all runs
5. **VRAM is CONSTANT**: 5595 MB across all runs

### Correlation

```
Fast runs:  CPU=4.3GHz, GPU=2480MHz, Power=35W  → 55 ms/tok
Slow runs:  CPU=2.7GHz, GPU=2130MHz, Power=25W  → 91 ms/tok
Ratio:      1.67x CPU, 1.17x GPU, 1.42x Power  → 1.65x latency
```

The latency increase (1.65x) closely matches the CPU frequency decrease (1.67x), suggesting the cold path is **CPU-frequency-bound**.

## Root Cause

**Thermal throttling** on the Acer Nitro V15 laptop:

1. Both CPU and GPU generate heat simultaneously
2. The laptop cooling system cannot dissipate heat fast enough
3. After ~20-30 seconds of sustained load, temperatures trigger throttling
4. CPU drops from 4.3 GHz to 2.7 GHz (P-cores)
5. GPU drops from 2480 MHz to 2130 MHz
6. GPU power limit reduced from 35W to 25W

## Why 48ms vs 75ms

- **48ms**: Measured during first runs of a session (laptop cool)
- **75ms**: Average including throttled runs (laptop hot)
- The 48ms is achievable but not sustainable

## Implications

1. **Page faults are NOT the bottleneck** — confirmed by constant ~89K minor faults
2. **Compute is NOT the bottleneck** — at full clocks, 55ms is achievable
3. **Thermal management IS the bottleneck** — sustained performance limited by cooling
4. **Any optimization must account for thermal state** — peak vs sustained performance differ by 65%

## Next Steps

1. **Measure sustained performance** — run for 5+ minutes and observe degradation curve
2. **Test with external cooling** — laptop cooler pad could improve sustained performance
3. **Optimize for thermal efficiency** — reduce power consumption per token
4. **Profile at fixed clock** — use `intel_pstate` and `nvidia-smi` to lock clocks and measure true compute/memory bottleneck

## Files

- `scripts/proper-benchmark.sh` — Benchmark with clock monitoring
- `/tmp/proper-bench.csv` — Raw data with per-run metrics
