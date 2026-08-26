# Official Benchmark Protocol — llama.cpp MoE Inference

## Purpose

Establish a reproducible methodology for measuring llama.cpp performance on the Acer Nitro V15 (RTX 4050, i7-13620H, 32GB RAM).

**Critical insight**: Thermal throttling causes 40-60% performance variation. Any benchmark MUST account for thermal state.

## Hardware

| Component | Spec |
|-----------|------|
| CPU | Intel i7-13620H (6P+4E cores) |
| GPU | NVIDIA RTX 4050 Laptop (6GB VRAM) |
| RAM | 32 GB DDR5 |
| Storage | NVMe SSD |
| Cooling | Internal (no external cooler) |

## Thermal Characteristics

| Phase | Duration | tok/s | CPU GHz | GPU MHz | GPU Power |
|-------|----------|-------|---------|---------|-----------|
| COLD (first 50s) | ~50s | 24-25 | 4.0-4.6 | 2505 | 42-44W |
| THROTTLED (50-230s) | ~180s | 17-18 | 2.7-3.0 | 2130 | 27-34W |
| RECOVERY (>230s) | ongoing | 18-19 | 2.5-3.0 | 2505 | 37-38W |

**Throttle threshold**: GPU edge temperature ~68°C

## Benchmark Procedure

### Prerequisites

1. Laptop must be at room temperature (not running inference)
2. No other GPU-intensive tasks running
3. Battery plugged in (not on battery power)
4. Power profile: performance (not balanced/power-saver)

### Steps

1. **Cooldown**: Wait 5 minutes after any previous inference
2. **Start server**: Use the EHS-25 profile
3. **Warmup**: Run 60 seconds of continuous inference
4. **Measurement**: Run 120 seconds of continuous inference
5. **Record**: Report metrics from measurement phase only

### Measurement Metrics

| Metric | How to Measure |
|--------|----------------|
| **Sustained tok/s** | median tok/s during measurement phase |
| **P90 latency** | 90th percentile ms/token during measurement |
| **GPU temp start** | nvidia-smi at measurement start |
| **GPU temp end** | nvidia-smi at measurement end |
| **CPU frequency** | /sys/devices/system/cpu/cpu*/cpufreq/scaling_cur_freq |
| **GPU clock** | nvidia-smi clocks.current.sm |
| **GPU power** | nvidia-smi power.draw |
| **VRAM** | nvidia-smi memory.used |
| **RAM** | free -m |

### What NOT to Report

- First-run tok/s (peak, not sustained)
- Single-run measurements (too variable)
- tok/s without thermal context
- Prompt processing speed (different workload)

## Configuration Standard

```
Model: Qwen3.6-35B-A3B Q4_K_M
EHS slots: 25
GPU layers: 45
Context: 8192
Batch: 512
Ubatch: 512
KV cache: q4_0
Flash attention: on
Threads: 8
Parallel: 1
```

## Result Format

```yaml
benchmark: ehs25-sustained
date: YYYY-MM-DD
hardware: Acer Nitro V15, RTX 4050 6GB, i7-13620H, 32GB RAM
config: EHS-25, ngl=45, ctx=8192, t=8
warmup: 60s
measurement: 120s
results:
  sustained_tok_s: XX.X
  p90_ms_per_token: XX.X
  gpu_temp_start: XX°C
  gpu_temp_end: XX°C
  gpu_clock_avg: XXXX MHz
  gpu_power_avg: XX.X W
  vram_used: XXXX MB
notes: |
  Any additional context (external cooler, ambient temp, etc.)
```

## History

| Date | Config | Median TG (sustained) | Mean TG (sustained) | Classification | Notes |
|------|--------|----------------------|--------------------|----------------|-------|
| 2026-08-26 | baseline (ncmoe=99) | 30.4 | 28.0 | CONTROLLED | Order A+B averaged, COLD start, --sustained-only |
| 2026-08-26 | ncmoe=35 | 32.2 | 28.0 | CONTROLLED | Order A+B averaged, COLD start, --sustained-only |
| 2026-08-26 | EHS-25 (wackmall) | 23.0 | 20.6 | CONTROLLED | Wackmall fork, --sustained-only |
| 2026-08-26 | baseline (ncmoe=99) | — | 29.7 | EARLIER | No thermal control, --sustained-only |
| 2026-08-26 | ncmoe=35 | — | 29.4 | EARLIER | No thermal control, --sustained-only |

**⚠️ No true peak was measured.** All controlled runs used `--sustained-only 45`. The "Median TG" represents the median of the sustained window (cold + throttled phases mixed). Earlier results are less reliable (no thermal control).

## Current Known Performance Baseline

**Last updated:** 2026-08-26
**Measurement method:** `scripts/benchmark-official.py` (45s sustained, upstream llama.cpp)

### MEASURED (controlled benchmark, COLD start, order-bias tested, --sustained-only)

**⚠️ No true peak was measured.** All values below are from the sustained window.

| Metric | baseline (ncmoe=99) | ncmoe=35 | EHS-25 |
|--------|---------------------|----------|--------|
| Median TG (sustained window) | 30.4 tok/s | 32.2 tok/s (+5.9%) | 23.0 tok/s (-24%) |
| Mean TG (sustained window) | 28.0 tok/s | 28.0 tok/s (≈same) | 20.6 tok/s (-26%) |
| Time to throttle | ~42s | ~42s | ~26s |
| VRAM | 2,543 MB | 4,933 MB | 5,595 MB |
| Efficiency | 0.686 tok/s/W | 0.695 tok/s/W | 0.548 tok/s/W |

**Key finding:** ncmoe=35 shows higher cold-phase throughput (+5.9% median) but NO sustained advantage. Both configs produce ~28 tok/s mean over 45s because both hit the same thermal wall at ~68°C GPU.

**EHS-25 is counterproductive** on 6GB VRAM. The wackmall fork overhead (mmproj, EHS bookkeeping) outweighs any expert cache benefit.

### THIRD-PARTY (not reproduced locally)

| Metric | Value | Source |
|--------|-------|--------|
| RTX 3060 12GB baseline | ~42 tok/s | YouTube k_LostFpatg |
| RTX 3060 12GB + expert cache | ~70+ tok/s | YouTube k_LostFpatg |
| RTX 3090 24GB | ~140 tok/s | gilesthomas.com |

### HYPOTHESIS (untested)

- Cooler externo: +30-40% sustained (**UNTESTED**)
- RTX 4060 8GB: +15-20% (**UNTESTED**)
- Q3_K_M: improve hit rate (**UNTESTED**, download failed)
- Poll=25 better than poll=50 (**UNTESTED** in server context)

See `docs/benchmarks/performance-evidence-audit.md` for full classification.

## Scripts

- `scripts/thermal-curve.sh` — Full thermal characterization
- `scripts/proper-benchmark.sh` — 10-run benchmark with stats
- `scripts/mlock-benchmark.sh` — mlock comparison test
