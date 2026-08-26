# Benchmark Report: ncmoe35

**Timestamp:** 2026-08-26 15:20:03
**Config:** MoE layers 0-34 on CPU, 35-44 on GPU
**Classification:** INCOMPLETE

## Environment

| Item | Value |
|------|-------|
| GPU | NVIDIA RTX 4050 Laptop (6 GB VRAM) |
| GPU Driver | 595.71.05 |
| GPU Compute Cap | 8.9 (Ada Lovelace) |
| CPU | Intel i7-13620H (6P+4E cores) |
| RAM | 32 GB DDR5 |
| OS Kernel | 7.1.8-zen1 |
| Model | Qwen3.6-35B-A3B Q4_K_M (~21 GiB) |
| llama.cpp binary | llama-server |
| llama.cpp commit | unknown |
| nixos-ai commit | a7e56de |

## Configuration

```
llama-server -m MODEL --mmproj MMPROJ -ngl 45 -t 8 -c 4096 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 --n-cpu-moe 35 --split-mode layer --no-mmproj-offload --parallel 1 --jinja --no-warmup
```

## SUSTAINED Performance (90s continuous load)

| Metric | Value |
|--------|-------|
| **TG tok/s** | **15.0** (median 15.2) |
| TG range | 14.2 – 15.3 |
| TG stdev | 0.36 |
| GPU clock | 2130 MHz |
| GPU temp | 62.3°C (max 63°C) |
| GPU power | 25.5 W |
| GPU util | 23% |
| VRAM | 4933 MB |
| CPU P-core | 2929 MHz |
| RAM | 7052 MB |
| Efficiency | 0.5862 tok/s/W |
