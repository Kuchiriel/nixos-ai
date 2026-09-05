# GPU Activation Fix — --cpu-moe Benchmark Results

**Contexto:** [[llama-cpp-tuning]] | [[slm-techniques]]
**Hardware:** [[system-overview]]
**Sweep relacionado:** [[ncmoe-sweep]]

**Date:** 2026-08-28
**Hardware:** RTX 4050 Laptop 6GB, i7-13620H, 32GB RAM
**Model:** Qwen3.6-35B-A3B Q4_K_M

## Problem Identified

With `--n-cpu-moe 99` and `ngl=45`, the GPU was at **0-5% utilization**.
The flag `--n-cpu-moe 99` puts 99 of 100 MoE layers' routed experts on CPU.
Only layer 0's experts ran on GPU. Attention was on GPU but the GPU was
effectively idle because the MoE compute (the bulk of the model) was all CPU.

## Fix Applied

Changed from:
```
gpuLayers = 45
moeFlags = "--n-cpu-moe 99 --split-mode layer --poll 50 --poll-batch 50"
```

To:
```
gpuLayers = 999
moeFlags = "--cpu-moe --split-mode layer --poll 50 --poll-batch 50"
```

Per HuggingFace MoE offload guide: `-ngl 999` puts everything on GPU first,
then `--cpu-moe` moves ONLY routed experts to CPU. Attention + Dense FFN
stay on GPU.

## Results

### TG Throughput (from server logs)

| Config | TG (tok/s) | GPU Util | GPU Clock | GPU Power |
|--------|-----------|----------|-----------|-----------|
| --n-cpu-moe 99 (BEFORE) | 2.4 | 0-5% | 2130 MHz | 15W |
| --cpu-moe peak (AFTER) | 12.3 | 72-95% | 2490 MHz | 34-38W |
| --cpu-moe sustained | 4.2-7.4 | 22-37% | 2130-2490 MHz | 30-32W |

**Peak improvement: 5.1x (2.4 → 12.3 tok/s)**

### Thermal Degradation

The TG degrades over time due to thermal throttling:
- 12.3 tok/s (fresh, 65°C)
- 9.1 tok/s (warming, 68°C)
- 7.4 tok/s (warm, 70°C)
- 4.2 tok/s (hot, 71°C+)

This is expected on a laptop without external cooling.

### Hardware State Comparison

| Metric | BEFORE (ncmoe=99) | AFTER (--cpu-moe) |
|--------|-------------------|---------------------|
| GPU utilization | 0-5% | 22-95% |
| GPU clock | 2130 MHz (P3) | 2130-2490 MHz |
| GPU power | 15W | 30-38W |
| GPU temp | 62°C | 65-71°C |
| CPU temp | 69°C | 72-77°C |
| Fan speed |不可读 | 4000-4400 RPM |
| TG throughput | 2.4 tok/s | 4.2-12.3 tok/s |

### Additional Changes

1. **acer_wmi.predator_v4=1** kernel parameter
   - Enables fan speed readout via /sys/class/hwmon/hwmon6/
   - Fan RPM: CPU ~4400, GPU ~4000
   - No PWM control (EC manages autonomously)

2. **llama-fan-control.service** — monitors fan speed and temperatures

3. **Stale VSCode cleanup** — removed code.desktop and code-wrapper

## Key Insight

The original `--n-cpu-moe 99` was architecturally wrong for this hardware.
It left the GPU idle while the CPU did all MoE work. The `--cpu-moe` flag
correctly keeps attention on GPU (where it benefits most from parallelism)
and only offloads routed experts to CPU.

## Remaining Issues

1. Thermal throttling still causes TG degradation over time
2. Fan control daemon needs rebuild to pick up new monitoring code
3. Sustained TG (~4-7 tok/s) is still below the theoretical maximum
4. Embeddings server required manual restart after reboot

## Commits

- `d700168` — fix: use --cpu-moe instead of --n-cpu-moe 99
- `489b40b` — feat: fan control service
- `8cd9c88` — fix: escape ${} in Nix strings
- `e65b8ea` — fix: handle read-only fan monitoring
