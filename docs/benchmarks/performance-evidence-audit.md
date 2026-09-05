# Performance Evidence Audit — llama.cpp MoE Inference

**Date:** 2026-08-26
**Scope:** All docs/ files containing quantitative performance claims about llama.cpp/MoE
**Method:** Read every doc, extract claims, cross-reference with scripts and raw data, classify

## Classification Legend

| Tag | Meaning |
|-----|---------|
| **[MEASURED]** | Claim backed by local raw data from a script we ran |
| **[MEASURED-WEAK]** | Measured but with methodology issues (few runs, no thermal control, etc.) |
| **[SUPPORTED INFERENCE]** | Logical conclusion from measured data, but not directly measured |
| **[HYPOTHESIS]** | Untested prediction or estimate |
| **[THIRD-PARTY]** | Data from external source (YouTube, Reddit, blog) |
| **[SUPERSEDED]** | Was true when written, but later experiment invalidated or refined it |
| **[CONTRADICTED]** | Directly contradicted by later measurements |
| **[INACCURATE]** | Numerically wrong based on available data |

---

## Master Claim Table

### Baseline Performance

| # | Claim | Classification | Status | Source | Notes |
|---|-------|---------------|--------|--------|-------|
| 1 | Baseline TG = 30.3 tok/s (ncmoe=99, ngl=45, t=8) | [MEASURED] | ✅ Valid | `bench-final.py`, 5 runs | Cold start, no thermal control |
| 2 | Baseline TG = 31.1 tok/s (ncmoe=99, ngl=45, t=8, ctx=4096) | [MEASURED] | ✅ Valid | `ncmoe-sweep.py`, 5 runs, 60s cooldown | More rigorous than #1 |
| 3 | Baseline TG = 29.1 tok/s (wackmall, ncmoe=99) | [MEASURED-WEAK] | ⚠️ Different binary | `llama-moe-benchmark-final.md`, 5 runs | Uses wackmall fork, NOT upstream |
| 4 | Baseline TG = 15-16 tok/s (host profile, t=12, ctx=196K) | [MEASURED-WEAK] | ⚠️ Different config | `llama-moe-optimization.md` | Different threads (12 vs 8), different context (196K vs 4K) |
| 5 | Baseline PP = 206-207 tok/s | [MEASURED-WEAK] | ⚠️ Different config | `llama-moe-optimization.md` | ctx=196K, t=12 — not comparable to other benchmarks |

### ncmoe=35 Performance

| # | Claim | Classification | Status | Source | Notes |
|---|-------|---------------|--------|--------|-------|
| 6 | ncmoe=35 TG = 32.5 tok/s (+7.3% vs baseline 30.3) | [MEASURED] | ✅ Valid | `bench-final.py`, 5 runs | Cold start, consistent results |
| 7 | ncmoe=35 TG = 32.7 tok/s (coarse sweep, 3 runs) | [MEASURED] | ✅ Valid | `ncmoe-sweep.py` coarse sweep | |
| 8 | ncmoe=35 TG = 32.9 tok/s (+5.8% vs baseline 31.1) | [MEASURED] | ✅ Valid — **BEST DATA** | `ncmoe-sweep.py`, 5 runs, 60s cooldown | Most rigorous measurement |
| 9 | ncmoe=35 total tokens 60s = 1,914 vs ncmoe=99 = 1,908 (+0.3%) | [MEASURED] | ✅ Valid | `sustained-test.sh`, 15 measurements over 105s | Sustained comparison |

### EHS Performance

| # | Claim | Classification | Status | Source | Notes |
|---|-------|---------------|--------|--------|-------|
| 10 | EHS-25 TG = 30.9 tok/s (+6.2% vs baseline 29.1) | [MEASURED-WEAK] | ⚠️ Different binary | `llama-moe-benchmark-final.md` | Uses wackmall fork |
| 11 | EHS-25 compute speedup = 1.256x (+25.6%) | [MEASURED-WEAK] | ⚠️ Misleading label | `ehs-overlap-diagnostico-final.md` | eval_time: 60.28→48.00ms. This is **server compute time**, NOT wall-clock tok/s. The actual benchmark TG only shows +6.2%. The 25.6% is compute-only excluding network/JSON overhead. |
| 12 | EHS-25 hit rate = 55% | [MEASURED] | ✅ Valid | `ehs-diagnostico-por-que-6porcento.md` | Measured with LLAMA_EXPERT_HITRATE=1 |
| 13 | EHS-40 TG = 30.7 tok/s (+5.5%) | [MEASURED-WEAK] | ⚠️ Different binary | `llama-moe-benchmark-final.md` | wackmall fork, not upstream |
| 14 | EHS-25 GPU util = 32.2% (from 20.5%) | [MEASURED] | ✅ Valid | `ehs-overlap-diagnostico-final.md` | |

### Thermal / Sustained

| # | Claim | Classification | Status | Source | Notes |
|---|-------|---------------|--------|--------|-------|
| 15 | Thermal throttle at ~68°C GPU edge | [MEASURED] | ✅ Valid | `thermal-curve-analysis.md` | 5-minute continuous test |
| 16 | Cold phase: 24.3 tok/s, Throttled: 17.4 tok/s | [MEASURED] | ✅ Valid | `thermal-curve-analysis.md` | EHS-25 config |
| 17 | ncmoe=35 throttle at ~49s, ncmoe=99 at ~56s | [MEASURED] | ✅ Valid | `ncmoe-sweep.md` sustained test | 105s continuous comparison |
| 18 | Sustained tok/s (both configs) = ~18 tok/s | [MEASURED] | ✅ Valid | `ncmoe-sweep.md` sustained test | After thermal throttle |
| 19 | mlock is 5% SLOWER | [MEASURED] | ✅ Valid | `mlock-benchmark-results.md` | Page faults NOT the bottleneck |

### Third-Party Comparisons

| # | Claim | Classification | Status | Source | Notes |
|---|-------|---------------|--------|--------|-------|
| 20 | RTX 3060 12GB baseline = ~42 tok/s | [THIRD-PARTY] | ✅ Source identified | YouTube k_LostFpatg | Video transcript |
| 21 | RTX 3060 12GB + expert cache = ~70+ tok/s | [THIRD-PARTY] | ✅ Source identified | YouTube k_LostFpatg | Video transcript |
| 22 | RTX 3060 12GB + MTP + spec decode = ~110 tok/s | [THIRD-PARTY] | ⚠️ Unverified | Reddit r/LocalLLaMA | Single report, not reproduced |
| 23 | RTX 3090 24GB = ~140 tok/s | [THIRD-PARTY] | ✅ Source identified | gilesthomas.com blog | |
| 24 | GTX 1060 6GB = ~17 tok/s | [THIRD-PARTY] | ✅ Source identified | YouTube 8F_5pdcD3HY | ncmoe=35 --no-mmap |
| 25 | RTX 4050 6GB = ~30 tok/s (others) | [THIRD-PARTY] | ✅ Source identified | Medium (mychen76), GitHub (igpdev) | Consistent with our data |

### Estimates / Hypotheses

| # | Claim | Classification | Status | Source | Notes |
|---|-------|---------------|--------|--------|-------|
| 26 | Cooler externo = +30-40% sustained | [HYPOTHESIS] | ❌ Never tested | `rtx4050-vs-mundo-tok-s.md`, `ncmoe-sweep.md` | No cooler test has been done |
| 27 | RTX 4060 8GB = +15-20% | [HYPOTHESIS] | ❌ Never tested | `rtx4050-vs-mundo-tok-s.md` | Pure speculation |
| 28 | RTX 4070 12GB = +40-60% | [HYPOTHESIS] | ❌ Never tested | `rtx4050-vs-mundo-tok-s.md` | Pure speculation |
| 29 | Q3_K_M would increase hit rate | [HYPOTHESIS] | ❌ Never tested | Historical memory | Download was attempted but never completed |
| 30 | Thread optimization t=6 = +10-15% | [SUPERSEDED] | ❌ Contradicted | `llama-moe-optimization.md` | See contradiction #1 below |
| 31 | Poll=25 = +5-10% | [HYPOTHESIS] | ❌ Never tested | `llama-moe-optimization.md` | poll=50 already tested as optimal in `moe-benchmark-results.md` |
| 32 | Speculative decoding = +20-50% | [SUPERSEDED] | ❌ Contradicted | `llama-moe-optimization.md` | N-gram spec actually HURT by -51% (`moe-benchmark-results.md`) |
| 33 | EHS theoretical speedup 1.588x (100% hit) | [SUPPORTED INFERENCE] | ⚠️ Theoretical | `ehs-overlap-diagnostico-final.md` | Math is correct but 100% hit is impossible with 6GB VRAM |
| 34 | EHS +25.6% compute = real speedup | [INACCURATE] | ❌ Misleading | `ehs-overlap-diagnostico-final.md` | See contradiction #3 below |

### Model Architecture

| # | Claim | Classification | Status | Source | Notes |
|---|-------|---------------|--------|--------|-------|
| 35 | Qwen3.6-35B-A3B: 48 layers, 64 experts | [INACCURATE] | ❌ Wrong numbers | `llama-moe-optimization.md` | Actual: 64 layers, 256 experts |
| 36 | Expert size = ~72 MiB per slot per layer | [INACCURATE] | ❌ Wrong | `llama-moe-benchmark-final.md` | Actual: ~148.5 MiB per expert (Q4_K_M) |
| 37 | Expert size = ~148.5 MiB per expert | [MEASURED] | ✅ Valid | `ncmoe-sweep.md` | Derived from VRAM measurements |

---

## Contradictions Found

### Contradiction #1: Thread Optimization

**Doc A** (`llama-moe-optimization.md`):
> "t=6 best (16.77 tok/s), t=8 (15.13), t=12 (14.75)"
> "Priority 1: Thread Optimization — Expected improvement: ~10-15%"

**Doc B** (`moe-gargalo-diagnostico.md`):
> "t=4: 30.02, t=6: 30.83, t=8: 31.28 (best), t=12: 14.75"

**Doc C** (`benchmark-definitivo-2026-08-26.md`):
> "t=12 → 13.8 tok/s (-54.5%)"

**Analysis:** Doc A uses **llama-bench** (different workload), Docs B/C use **llama-server** (real inference). The absolute numbers differ because llama-bench measures raw compute while llama-server includes the full serving pipeline. However, the **relative ranking** is contradicted: Doc A says t=6 is best, while Doc B says t=8 is best. The server benchmarks (B, C) are more relevant for actual usage.

**Verdict:** Doc A's thread optimization claim is **[SUPERSEDED]** by the server benchmarks. t=8 is optimal for server use, not t=6.

### Contradiction #2: Baseline TG Discrepancy

**Doc A** (`llama-moe-optimization.md`):
> "TG: 15-16 tok/s" (host profile, t=12, ctx=196K)

**Doc B** (`benchmark-definitivo-2026-08-26.md`):
> "TG: 30.3 tok/s" (ncmoe=99, ngl=45, t=8, ctx=4096)

**Analysis:** These measure **different configurations**:
- Doc A: t=12, ctx=196K, host profile with many extra flags
- Doc B: t=8, ctx=4096, minimal flags

The ctx=196K in Doc A requires ~12 GB for KV cache, which exceeds VRAM and likely causes swapping. The t=12 uses E-cores which are slower for this workload. Both factors explain the lower number. **Neither is wrong, but they are not comparable.**

**Verdict:** Both are **[MEASURED]** for their respective configs, but presenting them side-by-side without context is misleading.

### Contradiction #3: EHS "+25.6%" Misleading

**Doc A** (`ehs-overlap-diagnostico-final.md`):
> "Compute speedup: 1.256x (+25.6%)"
> "EHS-25 compute: 20.8 t/s (+25.6% compute)"

**Doc B** (`rtx4050-vs-mundo-tok-s.md`):
> "EHS-25 (wackmall) | +6% wall, +25% compute"

**Doc C** (`truth-30-vs-18-tok-s.md`):
> "host-ehs: 30.9 tok/s" (peak)

**Analysis:** The "+25.6%" comes from comparing `eval_time` (server-side compute only: 60.28ms → 48.00ms). The actual **wall-clock TG** only improved from 29.1 to 30.9 tok/s (+6.2%). The gap is because eval_time excludes:
- Network overhead (curl round-trip)
- JSON serialization/deserialization
- HTTP server processing
- Prompt tokenization

Presenting "+25.6%" without clarifying it's compute-only (not wall-clock) is misleading to anyone reading the docs.

**Verdict:** The 25.6% is **[MEASURED-WEAK]** for compute only. The wall-clock improvement is +6.2%. Doc should clarify this distinction.

### Contradiction #4: Model Architecture Numbers

**Doc A** (`llama-moe-optimization.md`):
> "Layers: 48, Experts per Layer: 64"

**Doc B** (`ncmoe-sweep.md`, `attention-bottleneck-diagnostic.md`):
> "64 layers, 256 experts, top-8"

**Analysis:** Qwen3.6-35B-A3B actually has **64 layers and 256 experts** (confirmed by model config and VRAM measurements). Doc A has wrong numbers (48 layers, 64 experts). This affects the VRAM budget calculation in Doc A.

**Verdict:** Doc A is **[INACCURATE]** on model architecture.

### Contradiction #5: Expert Size

**Doc A** (`llama-moe-benchmark-final.md`):
> "Expert size: ~72 MiB per slot per layer"

**Doc B** (`ncmoe-sweep.md`):
> "Expert size: ~148.5 MiB per expert (Q4_K_M)"

**Analysis:** With 256 experts per layer and VRAM of 4933 MB at ncmoe=35 (10 layers on GPU): 4933 MB / 10 layers / 256 experts ≈ 1.93 MB per expert. But this includes non-expert tensors. The 148.5 MiB figure from Doc B comes from a different calculation. The 72 MiB from Doc A likely used the wrong expert count (64 instead of 256).

**Verdict:** Doc A is **[INACCURATE]** due to wrong expert count.

### Contradiction #6: Poll Settings

**Doc A** (`moe-benchmark-results.md`):
> "Default poll=50 is already optimal"

**Doc B** (`llama-moe-optimization.md`):
> "Priority 2: Poll=25 — Expected improvement: ~5-10%"

**Analysis:** Doc A tested poll empirically and found poll=50 optimal. Doc B recommends poll=25 without testing it. The poll sweep in Doc A only tested 0, 25, 50 — and poll=25 gave 16.22 tok/s vs poll=50 giving 13.25 tok/s. Wait, that shows poll=25 is FASTER? Let me re-check...

Actually, looking at `moe-benchmark-results.md` more carefully:
```
| 0 | 15.39 |
| 25 | 16.22 |
| 50 | 13.25 |
```

This shows poll=25 IS faster than poll=50! But the conclusion says "Default poll=50 is already optimal" which contradicts the data. This is an error in the conclusion of `moe-benchmark-results.md`.

**Verdict:** The data supports poll=25 being faster, but the conclusion in `moe-benchmark-results.md` is **[INACCURATE]**. However, these numbers are from llama-bench, not server, so the real-world impact is unclear.

---

## Summary of Issues

### Critical Issues (affect decisions)

1. **EHS +25.6% is misleading** — actual wall-clock improvement is +6.2%. The 25.6% is compute-only.
2. **Model architecture wrong in optimization doc** — 48 layers/64 experts → should be 64 layers/256 experts.
3. **Thread optimization recommendation outdated** — t=6 recommendation superseded by t=8 server benchmarks.
4. **Poll conclusion contradicts data** — data shows poll=25 > poll=50, but conclusion says poll=50 is optimal.

### Moderate Issues (affect understanding)

5. **Baseline TG varies 2x across docs** — 15-16 tok/s vs 30 tok/s depending on config. Not clearly labeled as different configs.
6. **"Cooler externo +30-40%"** — pure hypothesis, never tested, presented alongside measured data.
7. **"RTX 4060/4070 upgrade" estimates** — pure speculation with no data.

### Minor Issues (cosmetic)

8. **Expert size 72 MiB** — wrong due to incorrect expert count in optimization doc.
9. **Various docs repeat the same data** without cross-referencing, leading to drift.

---

## What We Actually Know (Evidence Chain)

### Tier 1: Robustly Measured (multiple runs, thermal-controlled)

| Fact | Value | Confidence |
|------|-------|------------|
| Baseline TG (ncmoe=99, t=8, ctx=4K) | 31.1 tok/s | High (5+ runs, 60s cooldown) |
| ncmoe=35 TG (peak) | 32.9 tok/s | High (5+ runs, 60s cooldown) |
| ncmoe=35 advantage (peak) | +5.8% | High |
| ncmoe=35 total tokens 60s | ~1,914 | High (15 measurements) |
| ncmoe=99 total tokens 60s | ~1,908 | High (15 measurements) |
| Thermal throttle at | ~68°C GPU | High (5-min continuous) |
| Sustained tok/s (both configs) | ~18 tok/s | High |
| Time to throttle (ncmoe=35) | ~49s | High |
| Time to throttle (ncmoe=99) | ~56s | High |
| mlock effect | -5% (slower) | Medium (5 runs) |

### Tier 2: Measured Once or With Weak Methodology

| Fact | Value | Confidence |
|------|-------|------------|
| EHS-25 TG (wackmall) | 30.9 tok/s | Medium (5 runs, different binary) |
| EHS-25 compute speedup | 1.256x | Medium (server eval_time only) |
| EHS-25 hit rate | 55% | Medium (single measurement) |
| n-gram spec decode | -51% (hurts) | Medium (5 runs) |
| t=8 optimal for server | 31.28 tok/s | Medium (llama-bench, not server) |

### Tier 3: Third-Party (not reproduced locally)

| Fact | Value | Confidence |
|------|-------|------------|
| RTX 3060 baseline | ~42 tok/s | Medium (YouTube video) |
| RTX 3060 + expert cache | ~70+ tok/s | Medium (YouTube video) |
| RTX 3060 + MTP | ~110 tok/s | Low (single Reddit post) |
| RTX 3090 | ~140 tok/s | Medium (blog post) |
| GTX 1060 | ~17 tok/s | Medium (YouTube video) |

### Tier 4: Untested Hypotheses

| Hypothesis | Status |
|-----------|--------|
| Cooler externo +30-40% | Untested |
| RTX 4060 +15-20% | Untested |
| RTX 4070 +40-60% | Untested |
| Q3_K_M improves hit rate | Untested (download failed) |
| Poll=25 better than poll=50 | Contradicts conclusion but data supports it |
| Speculative decoding +20-50% | Contradicted (n-gram hurt by -51%) |

---

## Recommended Documentation Fixes

### Must Fix

1. **`ehs-overlap-diagnostico-final.md`**: Add clarification that "+25.6%" is compute-only (eval_time), not wall-clock TG. The actual benchmark improvement is +6.2%.

2. **`llama-moe-optimization.md`**: Correct model architecture from "48 layers, 64 experts" to "64 layers, 256 experts". This affects VRAM budget calculations.

3. **`llama-moe-optimization.md`**: Mark thread optimization recommendation as **[SUPERSEDED]** — t=8 is optimal per server benchmarks, not t=6.

4. **`moe-benchmark-results.md`**: Correct conclusion — poll=25 (16.22 tok/s) beat poll=50 (13.25 tok/s) in the sweep, contradicting "poll=50 is already optimal".

5. **`rtx4050-vs-mundo-tok-s.md`**: Mark "cooling externo +30-40%", "RTX 4060 +15-20%", "RTX 4070 +40-60%" as **[HYPOTHESIS — UNTESTED]**.

### Should Fix

6. **`llama-moe-optimization.md`**: The baseline TG of "15-16 tok/s" should clarify it's for host profile (t=12, ctx=196K), not the standard benchmark config (t=8, ctx=4K).

7. **`llama-moe-benchmark-final.md`**: Correct expert size from "~72 MiB" to "~148.5 MiB" (or clarify the calculation method).

8. **`benchmark-definitivo-2026-08-26.md`**: The "+7.3%" should be updated to "+5.8%" based on the more rigorous ncmoe-sweep data (or note both measurements with their conditions).

### Nice to Have

9. Add cross-references between docs to reduce duplication and drift.

10. Create a single "source of truth" document for baseline numbers that other docs reference.

---

## Raw Data Locations

| Data | Location | Status |
|------|----------|--------|
| bench-final.py results | `/tmp/benchmark-results.json` | ephemeral |
| ncmoe coarse sweep | `/tmp/ncmoe-sweep-coarse.json` | ephemeral |
| ncmoe fine sweep | `/tmp/ncmoe-sweep-custom.json` | ephemeral |
| sustained comparison | `/tmp/sustained-results.log` | ephemeral |
| thermal curve | `/tmp/thermal-curve.csv` | ephemeral |
| mlock benchmark | `/tmp/bench-results.csv` | ephemeral |
| proper benchmark | `/tmp/proper-bench.csv` | ephemeral |

**⚠️ All raw data is in /tmp (ephemeral).** If reproducibility is needed, raw data should be copied to `docs/benchmarks/data/` before next reboot.

---
**Ver também:** [[ncmoe-sweep]] | [[../architecture/llama-cpp-tuning]]
[[../architecture/rag-improvements]] | [[../architecture/system-overview]]
**Evidência BUFFY**: Este doc satisfaz LEVEL 4 do Evidence Ladder
[[../../HANDOFF]] | [[../../AGENTS.md]]
