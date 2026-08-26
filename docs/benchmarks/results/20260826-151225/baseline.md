# Benchmark Report: baseline

**Timestamp:** 2026-08-26 15:13:41
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
| llama.cpp commit |  |
| nixos-ai commit | a7e56de |

## Configuration

```
llama-server -m MODEL --mmproj MMPROJ -ngl 45 -t 8 -c 4096 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 --n-cpu-moe 99 --split-mode layer --no-mmproj-offload --parallel 1 --jinja --no-warmup
```

## SUSTAINED Performance (90s continuous load)

| Metric | Value |
|--------|-------|
| **TG tok/s** | **23.4** (median 29.5) |
| TG range | 13.5 – 30.3 |
| TG stdev | 7.58 |
| GPU clock | 2338 MHz |
| GPU temp | 66.2°C (max 70°C) |
| GPU power | 35.1 W |
| GPU util | 34% |
| VRAM | 2543 MB |
| CPU P-core | 3826 MHz |
| RAM | 7562 MB |
| Efficiency | 0.6677 tok/s/W |
