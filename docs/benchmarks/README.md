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

| Date | Config | Sustained tok/s | Notes |
|------|--------|-----------------|-------|
| 2026-08-26 | EHS-25 | 18.6 | No external cooler, room temp ~25°C |

## Scripts

- `scripts/thermal-curve.sh` — Full thermal characterization
- `scripts/proper-benchmark.sh` — 10-run benchmark with stats
- `scripts/mlock-benchmark.sh` — mlock comparison test
