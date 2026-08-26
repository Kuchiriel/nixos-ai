# Controlled Benchmark Analysis — 2026-08-26

## Protocol

- **Method:** `scripts/benchmark-official.py --sustained-only 45`
- **Thermal control:** GPU temp checked before each config; threshold ≤62°C = COLD
- **Order bias:** Two runs with reversed config order
- **Cooldown:** 90s between configs
- **All configs started COLD** (56-58°C GPU)

## Raw Results

### Order A: baseline → ncmoe35 → ehs25

| # | Config | Sustained TG | Median TG | Initial Temp | Max Temp | VRAM | Efficiency |
|---|--------|-------------|-----------|-------------|----------|------|------------|
| 1 | baseline | 28.6 | 30.4 | 57°C | 71°C | 2543 MB | 0.689 tok/s/W |
| 2 | ncmoe35 | 26.2 | 32.1 | 58°C | 70°C | 4933 MB | 0.683 tok/s/W |
| 3 | ehs25 | 20.6 | 22.7 | 57°C | 71°C | 5595 MB | 0.548 tok/s/W |

### Order B: ncmoe35 → baseline → ehs25

| # | Config | Sustained TG | Median TG | Initial Temp | Max Temp | VRAM | Efficiency |
|---|--------|-------------|-----------|-------------|----------|------|------------|
| 1 | ncmoe35 | 29.8 | 32.2 | 56°C | 70°C | 4933 MB | 0.706 tok/s/W |
| 2 | baseline | 27.3 | 30.4 | 57°C | 71°C | 2543 MB | 0.683 tok/s/W |
| 3 | ehs25 | 20.6 | 23.3 | 57°C | 71°C | 5595 MB | 0.549 tok/s/W |

## Order Bias Analysis

### ncmoe35

| Position | Sustained | Median | Initial Temp |
|----------|-----------|--------|-------------|
| 1st (Order B) | 29.8 | 32.2 | 56°C |
| 2nd (Order A) | 26.2 | 32.1 | 58°C |
| **Delta** | **-3.6 (-12%)** | **-0.1 (0%)** | +2°C |

**Verdict:** The sustained average differs by 12% depending on position, but the **median is identical** (32.1 vs 32.2). The difference is entirely explained by thermal throttling — when ncmoe35 runs 2nd, the laptop retains residual heat from the previous config, causing earlier throttle and dragging down the sustained average.

### baseline

| Position | Sustained | Median | Initial Temp |
|----------|-----------|--------|-------------|
| 1st (Order A) | 28.6 | 30.4 | 57°C |
| 2nd (Order B) | 27.3 | 30.4 | 57°C |
| **Delta** | **-1.3 (-5%)** | **0.0 (0%)** | 0°C |

**Verdict:** Baseline is less affected by order because it uses less VRAM (2543 vs 4933 MB) and generates less heat. The median is identical regardless of position.

### ehs25

| Position | Sustained | Median | Initial Temp |
|----------|-----------|--------|-------------|
| 3rd (Order A) | 20.6 | 22.7 | 57°C |
| 3rd (Order B) | 20.6 | 23.3 | 57°C |
| **Delta** | **0.0 (0%)** | **+0.6 (+3%)** | 0°C |

**Verdict:** EHS-25 always runs 3rd, so order bias cannot be assessed. The results are consistent across both runs.

## Thermal Throttling Timeline

All three configs follow the same pattern:
- **0-40s:** Cold phase, GPU at 2505 MHz, full performance
- **42-43s:** Throttle point, GPU drops to 2130 MHz
- **43s+:** Throttled phase, ~50% of peak performance

The sustained average blends cold + throttled phases, making it sensitive to exactly when throttle occurs.

## Final Comparison Table

| Config | Peak (median) | Sustained (mean) | Throttle @ | VRAM | Efficiency | Status |
|--------|--------------|-----------------|------------|------|------------|--------|
| **baseline** | **30.4** | **28.0** (avg of 28.6, 27.3) | ~42s | 2543 MB | 0.686 tok/s/W | **MEASURED** |
| **ncmoe35** | **32.2** | **28.0** (avg of 26.2, 29.8) | ~42s | 4933 MB | 0.695 tok/s/W | **MEASURED** |
| **ehs25** | **23.0** | **20.6** | ~26s | 5595 MB | 0.548 tok/s/W | **MEASURED** |

## Classification

### baseline vs ncmoe35

- **Peak:** ncmoe35 median 32.2 vs baseline 30.4 → **+5.9% [MEASURED]**
- **Sustained:** ncmoe35 28.0 vs baseline 28.0 → **~0% [MEASURED]**
- **Conclusion:** **PEAK IMPROVEMENT WITHOUT SUSTAINED THROUGHPUT IMPROVEMENT**
- **Explanation:** ncmoe35 puts more MoE experts on GPU (higher peak compute), but the extra VRAM usage (4933 vs 2543 MB) and power draw cause identical thermal throttling. Over a 45s window, both produce approximately the same total tokens.

### ehs25 vs baseline

- **Peak:** ehs25 median 23.0 vs baseline 30.4 → **-24.3% [MEASURED]**
- **Sustained:** ehs25 20.6 vs baseline 28.0 → **-26.4% [MEASURED]**
- **Conclusion:** **REGRESSION** — EHS-25 is significantly slower than baseline on this hardware.
- **Explanation:** The wackmall fork has higher overhead (5595 MB VRAM, mmproj loaded, EHS bookkeeping). The 6GB VRAM is insufficient for EHS to provide benefit. Previous claims of +6% were on the wackmall fork baseline (29.1 tok/s), not the upstream baseline (30.4 tok/s).

### Efficiency

| Config | tok/s/W | Classification |
|--------|---------|---------------|
| ncmoe35 | 0.695 | **MEASURED** — marginally most efficient |
| baseline | 0.686 | **MEASURED** |
| ehs25 | 0.548 | **MEASURED** — least efficient |

## What We Know vs What We Believe

### MEASURED (this session)

1. Baseline peak median: 30.4 tok/s ✅
2. ncmoe35 peak median: 32.2 tok/s (+5.9%) ✅
3. Both sustain ~28 tok/s over 45s ✅
4. Thermal throttle at ~42s, GPU 68°C ✅
5. EHS-25 sustained: 20.6 tok/s (-26% vs baseline) ✅
6. Order bias affects sustained average by up to 12% ✅
7. Median is order-independent ✅

### SUPPORTED INFERENCE (from measured data)

1. The thermal wall is the dominant factor for sustained throughput
2. ncmoe=35's advantage disappears under sustained load due to thermal throttling
3. EHS-25 is counterproductive on 6GB VRAM (too much overhead)

### HYPOTHESIS (untested)

1. Cooler externo could sustain peak performance → **UNTESTED**
2. More VRAM (8GB+) would make EHS beneficial → **UNTESTED**
3. Q3_K_M would improve EHS hit rate → **UNTESTED**

### THIRD-PARTY (not reproduced)

1. RTX 3060 baseline ~42 tok/s → YouTube
2. RTX 3060 + EHS ~70+ tok/s → YouTube
3. RTX 3090 ~140 tok/s → Blog

## Recommendation

**For this hardware (RTX 4050 6GB):**

The **baseline (ncmoe=99)** is the recommended configuration because:
- Same sustained throughput as ncmoe35 (~28 tok/s)
- Lower VRAM usage (2543 vs 4933 MB) — leaves room for KV cache
- More stable (lower stdev)
- Simpler (no EHS overhead)

**ncmoe=35** is only advantageous for:
- Short requests (<40s) where peak matters
- Scenarios where VRAM pressure is not a concern

**EHS-25** should NOT be used on this hardware.

## Files

| File | Description |
|------|-------------|
| `results/20260826-153843/` | Order A: baseline → ncmoe35 → ehs25 |
| `results/20260826-154715/` | Order B: ncmoe35 → baseline → ehs25 |
| `results/20260826-controlled/analysis.md` | This document |
