# Thermal Curve Analysis — 5-Minute Continuous Inference

## Experiment

- Duration: 300 seconds (5 minutes)
- Config: EHS-25, continuous inference
- Sampling: every 2 seconds (clocks, temps, power) + per-request timing

## Three Phases Observed

### Phase 1: COLD (0-52s) — Peak Performance

| Metric | Value |
|--------|-------|
| tok/s | 24.3-24.8 |
| ms/token | 40.4-43.3 |
| CPU P-core | 4.0-4.6 GHz |
| GPU SM clock | 2505 MHz |
| GPU Power | 42-44W |
| GPU Temp | 58-68°C |

### Phase 2: THROTTLED (57-222s) — Degraded Performance

| Metric | Value |
|--------|-------|
| tok/s | 16.4-17.9 |
| ms/token | 55.6-60.9 |
| CPU P-core | 2.7-3.0 GHz (**-37%**) |
| GPU SM clock | 2130 MHz (**-15%**) |
| GPU Power | 27-34W (**-35%**) |
| GPU Temp | 61-64°C (lower than peak!) |

### Phase 3: RECOVERY (229-300s) — Partial Recovery

| Metric | Value |
|--------|-------|
| tok/s | 18.7-19.2 |
| ms/token | 52.0-53.5 |
| CPU P-core | 2.5-3.0 GHz (still throttled) |
| GPU SM clock | 2505 MHz (recovered!) |
| GPU Power | 37-38W (partially recovered) |
| GPU Temp | 63-65°C |

## Throttling Sequence

```
Time  Event
───── ─────────────────────────────────────────
0s    Cold start, full clocks
57s   GPU hits 68°C → GPU throttles to 2130 MHz
57s   CPU simultaneously drops to 2.9 GHz
57s   GPU power drops from 44W to 28W
229s  GPU recovers to 2505 MHz (temp dropped to 62°C)
229s  CPU stays at 2.9 GHz (different thermal zone?)
```

## Key Findings

1. **GPU throttles first** at 68°C GPU edge temperature
2. **CPU throttles simultaneously** — likely shared thermal solution
3. **Temperature DROPS during throttle** — throttling is effective at cooling
4. **GPU recovers faster than CPU** — GPU has better thermal mass/cooling
5. **GPU power limit is the primary mechanism**: 44W → 28W → 38W

## Degradation Curve

```
Time(s)  tok/s   CPU(GHz)  GPU(MHz)  GPU(W)  GPU(°C)
0        23.1    2.7       2505      42.6    58
10       24.7    2.5       2505      43.6    62
20       24.7    3.8       2505      43.7    62
30       24.6    4.4       2505      44.6    66
40       24.5    4.0       2505      44.6    67
50       24.6    4.4       2505      44.5    68  ← THROTTLE POINT
60       17.5    2.9       2130      28.4    64
90       17.4    2.9       2130      28.7    62
120      17.4    3.0       2130      28.7    63
150      17.4    2.2       2235      30.0    63
180      16.6    2.5       2130      27.9    63
210      17.5    3.2       2130      31.4    63
240      18.9    2.6       2505      37.5    63  ← GPU RECOVERS
270      18.9    2.8       2505      37.6    65
300      19.2    2.9       2505      38.4    64
```

## Sustained Performance

| Phase | Duration | avg tok/s | avg ms/tok |
|-------|----------|-----------|------------|
| COLD (0-52s) | 52s | 24.3 | 41.1 |
| THROTTLED (57-222s) | 165s | 17.4 | 57.5 |
| RECOVERY (229-300s) | 71s | 18.9 | 52.9 |
| **Overall** | **300s** | **18.6** | **53.7** |

**Sustained throughput: ~18.6 tok/s (53.7 ms/tok)**

## Implications for Benchmarking

1. **Never use first-run numbers** — they represent peak, not sustained
2. **Allow 60s warmup** before measuring
3. **Report sustained throughput** (after 60s), not peak
4. **Control thermal state** — or at least report GPU temp
5. **Cooler external could help** — if it prevents 68°C threshold

## Tokens per Joule Efficiency

| Phase | tok/s | GPU Power | tokens/joule |
|-------|-------|-----------|--------------|
| COLD | 24.3 | 43W | 0.565 |
| THROTTLED | 17.4 | 29W | 0.600 |
| RECOVERY | 18.9 | 38W | 0.497 |

**Throttled state is actually MORE efficient per joule!** The GPU uses less power per token when throttled, even though it's slower.

## Recommended Benchmark Protocol

1. **Warmup**: 60 seconds of continuous inference
2. **Measurement**: 120 seconds of continuous inference
3. **Report**: median tok/s during measurement phase
4. **Record**: GPU temp at start and end
5. **Condition**: laptop must be at thermal equilibrium

## Files

- `scripts/thermal-curve.sh` — Thermal curve measurement script
- `/tmp/thermal-curve.csv` — Raw data
