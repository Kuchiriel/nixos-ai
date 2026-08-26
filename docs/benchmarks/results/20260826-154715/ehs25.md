# Benchmark Report: ehs25

**Timestamp:** 2026-08-26 15:53:22
**Config:** Expert Hot Store 25 slots (wackmall fork)
**Classification:** INCOMPLETE
**Cold start:** YES
**Initial GPU temp:** 57°C
**Initial GPU clock:** 2505 MHz

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
| llama.cpp binary | llama-wackmall-wrapper.sh |
| llama.cpp commit | 7141f05 |
| nixos-ai commit | 7141f05 |

## Configuration

```
llama-wackmall-wrapper.sh -m MODEL --mmproj MMPROJ -ngl 45 -t 8 -c 8192 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 -ehs 25 --split-mode layer --parallel 1 --jinja
```

## SUSTAINED Performance (40s continuous load)

| Metric | Value |
|--------|-------|
| **TG tok/s** | **20.6** (median 22.9) |
| TG range | 15.7 – 23.3 |
| TG stdev | 3.25 |
| GPU clock | 2387 MHz |
| GPU temp | 67.4°C (max 71°C) |
| GPU power | 37.5 W |
| GPU util | 37% |
| VRAM | 5595 MB |
| CPU P-core | 4050 MHz |
| RAM | 7157 MB |
| Efficiency | 0.5484 tok/s/W |
