# Benchmark Report: baseline

**Timestamp:** 2026-08-26 15:44:45
**Config:** All MoE on CPU (upstream default)
**Classification:** INCOMPLETE
**Cold start:** YES
**Initial GPU temp:** 57°C
**Initial GPU clock:** 2130 MHz

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
| llama.cpp commit | nix-10273 |
| nixos-ai commit | 7141f05 |

## Configuration

```
llama-server -m MODEL --mmproj MMPROJ -ngl 45 -t 8 -c 4096 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 --n-cpu-moe 99 --split-mode layer --no-mmproj-offload --parallel 1 --jinja --no-warmup
```

## SUSTAINED Performance (38s continuous load)

| Metric | Value |
|--------|-------|
| **TG tok/s** | **28.6** (median 30.4) |
| TG range | 14.7 – 30.5 |
| TG stdev | 4.94 |
| GPU clock | 2460 MHz |
| GPU temp | 67.3°C (max 71°C) |
| GPU power | 41.6 W |
| GPU util | 42% |
| VRAM | 2543 MB |
| CPU P-core | 4461 MHz |
| RAM | 7541 MB |
| Efficiency | 0.6887 tok/s/W |
