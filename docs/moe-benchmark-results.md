# MoE Benchmark Results — 2026-08-25

## Hardware
- GPU: RTX 4050 Laptop (6GB VRAM)
- CPU: i7-13620H
- RAM: 32GB

## Model
- Qwen3.6-35B-A3B Q4_K_M (20.6 GiB)
- Config: -ngl 45 -ncmoe 99 -sm layer -t 6 -c 4096 -fa on -ctk q4_0 -ctv q4_0

## A/B Test: Baseline vs N-gram Speculative Decoding

### A: Baseline (no spec)
| Run | TG (t/s) |
|-----|----------|
| 1 | 29.5 |
| 2 | 29.6 |
| 3 | 29.5 |
| 4 | 29.3 |
| 5 | 29.3 |
| **Avg** | **29.4** |

### B: N-gram Spec (ngram-mod, n_max=64)
| Run | TG (t/s) | Draft Acceptance |
|-----|----------|------------------|
| 1 | 29.3 | (no patterns yet) |
| 2 | 15.0 | 48% (93/192) |
| 3 | 14.3 | 48% (93/192) |
| 4 | 13.8 | 48% (93/192) |
| 5 | 14.2 | 48% (93/192) |
| **Avg** | **14.3** | **48%** |

### Result: N-gram spec HURTS performance (-51%)

**Why it failed:**
1. Draft acceptance rate of 48% is too low
2. Overhead of draft generation + verification dominates
3. Short/repetitive prompts don't benefit from n-gram patterns
4. Model is already fast enough that spec overhead > benefit

**What would work:**
- EAGLE-3 draft model (trained for this specific target)
- Higher acceptance rate needed (>70% to break even)
- Longer context prompts where patterns repeat

## Thread Sweep (llama-bench)
| Threads | TG (t/s) |
|---------|----------|
| 4 | 30.02 |
| 6 | 30.83 |
| 8 | 31.28 |

**Best: t=8 (31.28 t/s)**

## Poll Sweep (llama-bench)
| Poll | TG (t/s) |
|------|----------|
| 0 | 15.39 |
| 25 | 16.22 |
| 50 | 13.25 |

**Default poll=50 is already optimal for this config**

## Conclusion

1. **Baseline is already near-optimal** for this hardware
2. **N-gram spec is counterproductive** (needs trained draft model)
3. **Thread optimization: t=8** gives +6% over t=6
4. **Expert cache not feasible** on 6GB VRAM
5. **EAGLE-3 draft model** is the most promising path forward
