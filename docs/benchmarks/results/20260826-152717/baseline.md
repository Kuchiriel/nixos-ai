# Benchmark Report: baseline

**Timestamp:** 2026-08-26 15:28:17
**Config:** All MoE on CPU (upstream default)
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
llama-server -m MODEL --mmproj MMPROJ -ngl 45 -t 8 -c 4096 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 --n-cpu-moe 99 --split-mode layer --no-mmproj-offload --parallel 1 --jinja --no-warmup
```

## SUSTAINED Performance (42s continuous load)

| Metric | Value |
|--------|-------|
| **TG tok/s** | **29.7** (median 31.0) |
| TG range | 18.6 – 31.0 |
| TG stdev | 3.70 |
| GPU clock | 2464 MHz |
| GPU temp | 67.0°C (max 71°C) |
| GPU power | 42.1 W |
| GPU util | 43% |
| VRAM | 2543 MB |
| CPU P-core | 4196 MHz |
| RAM | 6932 MB |
| Efficiency | 0.7053 tok/s/W |
