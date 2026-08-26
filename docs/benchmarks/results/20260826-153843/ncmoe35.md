# Benchmark Report: ncmoe35

**Timestamp:** 2026-08-26 15:44:45
**Config:** MoE layers 0-34 on CPU, 35-44 on GPU
**Classification:** INCOMPLETE
**Cold start:** YES
**Initial GPU temp:** 58°C
**Initial GPU clock:** 2520 MHz

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
llama-server -m MODEL --mmproj MMPROJ -ngl 45 -t 8 -c 4096 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 --n-cpu-moe 35 --split-mode layer --no-mmproj-offload --parallel 1 --jinja --no-warmup
```

## SUSTAINED Performance (39s continuous load)

| Metric | Value |
|--------|-------|
| **TG tok/s** | **26.2** (median 32.1) |
| TG range | 15.2 – 32.7 |
| TG stdev | 7.90 |
| GPU clock | 2364 MHz |
| GPU temp | 66.5°C (max 70°C) |
| GPU power | 38.3 W |
| GPU util | 39% |
| VRAM | 4933 MB |
| CPU P-core | 3990 MHz |
| RAM | 7158 MB |
| Efficiency | 0.6825 tok/s/W |
