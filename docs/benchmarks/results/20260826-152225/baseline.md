# Benchmark Report: baseline

**Timestamp:** 2026-08-26 15:23:32
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

## SUSTAINED Performance (90s continuous load)

| Metric | Value |
|--------|-------|
| **TG tok/s** | **28.0** (median 30.2) |
| TG range | 14.3 – 30.8 |
| TG stdev | 5.15 |
| GPU clock | 2430 MHz |
| GPU temp | 67.4°C (max 71°C) |
| GPU power | 40.2 W |
| GPU util | 40% |
| VRAM | 2543 MB |
| CPU P-core | 4226 MHz |
| RAM | 7039 MB |
| Efficiency | 0.6959 tok/s/W |
