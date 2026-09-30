#!/usr/bin/env python3
"""fast_tune.py — Busca binária direcional para tuning do llama.cpp.

Estratégia:
  1. Testa valores extremos de cada gene (0, 50, 99) → mapeia o landscape
  2. Divide o espaço pela metade → binary search até convergir
  3. Refina com +1/-1 no sweet spot
  4. Junta os melhores genes e testa a combinação final

Cada gene é otimizado INDEPENDENTENTE (assume fraca correlação).
A combinação final valida se a assumption holda.

~30 benchmarks totais × ~60s = ~30 minutos
"""
from __future__ import annotations
import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

from ga_engine import (
    GENES, FITNESS_WEIGHTS, PROMPT_SIZE, NORM_RANGES,
    build_full_command, build_server_args,
    run_single_benchmark, calculate_fitness,
)

# ══════════════════════════════════════════════════════════════════════════════
# GENE SEARCH SPACES
# ══════════════════════════════════════════════════════════════════════════════

# Genes to optimize, ordered by importance (weight)
GENE_SEARCH = [
    {
        "name": "nCpuMoe", "weight": 0.8,
        "type": "int", "min": 0, "max": 99, "step": 5,
        "probes": [0, 50, 99],  # Extreme values first
    },
    {
        "name": "gpuLayers", "weight": 0.9,
        "type": "int", "min": 30, "max": 50, "step": 1,
        "probes": [30, 40, 50],
    },
    {
        "name": "kvCacheType", "weight": 0.7,
        "type": "choice", "choices": ["q4_0", "q8_0"],
        "probes": ["q4_0", "q8_0"],
    },
    {
        "name": "threads", "weight": 0.6,
        "type": "int", "min": 6, "max": 20, "step": 1,
        "probes": [6, 12, 20],
    },
    {
        "name": "kvUnified", "weight": 0.5,
        "type": "choice", "choices": [True, False],
        "probes": [True, False],
    },
    {
        "name": "reasoningPreserve", "weight": 0.5,
        "type": "choice", "choices": [True, False],
        "probes": [True, False],
    },
    {
        "name": "noWarmup", "weight": 0.4,
        "type": "choice", "choices": [True, False],
        "probes": [True, False],
    },
    {
        "name": "parallel", "weight": 0.4,
        "type": "int", "min": 1, "max": 4, "step": 1,
        "probes": [1, 2, 4],
    },
]

BASELINE = {g["name"]: g["default"] for g in GENES}


# ══════════════════════════════════════════════════════════════════════════════
# BENCHMARK SINGLE CONFIG
# ══════════════════════════════════════════════════════════════════════════════

def bench(config: dict[str, Any], server_url: str, port: int,
          runs: int, ctx_size: int) -> dict[str, Any]:
    """Benchmark a config. Returns metrics dict."""
    args = build_server_args(config)
    cmd = build_full_command(args, ctx_size=ctx_size, port=port)
    if cmd[0] == "echo":
        return {"error": "not found", "fitness": 0}

    all_decode = []
    all_prefill = []
    last_vram = 0
    last_vram_total = 6144
    last_temp = 80

    for run_idx in range(runs):
        # Kill existing
        subprocess.run(["pkill", "-f", f"llama-server.*--port {port}"],
                       capture_output=True, timeout=5)
        time.sleep(3)

        # Start
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)

        # Health check
        ready = False
        wait = 2
        while wait <= 60:
            time.sleep(wait)
            try:
                r = subprocess.run(["curl", "-sf", f"{server_url}/health"],
                                   capture_output=True, timeout=2)
                if r.returncode == 0:
                    ready = True
                    break
            except Exception:
                pass
            wait = min(wait * 2, 60)

        if not ready:
            proc.kill()
            proc.wait()
            return {"error": "timeout", "fitness": 0}

        # Warmup (discard)
        run_single_benchmark(server_url=server_url)
        time.sleep(1)

        # Benchmark
        m = run_single_benchmark(server_url=server_url)
        all_decode.append(m.get("decode_tps", 0))
        all_prefill.append(m.get("prefill_tps", 0))
        last_vram = m.get("vram_used_mb", 0)
        last_vram_total = m.get("vram_total_mb", 6144)
        last_temp = m.get("temperature_c", 80)

        # Stop
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        if run_idx < runs - 1:
            time.sleep(3)

    if not all_decode:
        return {"error": "no data", "fitness": 0}

    avg_decode = sum(all_decode) / len(all_decode)
    avg_prefill = sum(all_prefill) / len(all_prefill)
    if len(all_decode) > 1 and avg_decode > 0:
        std = (sum((x - avg_decode)**2 for x in all_decode) / len(all_decode)) ** 0.5
        consistency = max(0, 1.0 - (std / avg_decode) * 10)
    else:
        consistency = 0.5

    metrics = {
        "decode_tps": avg_decode,
        "prefill_tps": avg_prefill,
        "consistency": consistency,
        "vram_headroom": max(0, 1.0 - (last_vram / last_vram_total)),
        "temperature": max(0, 1.0 - (last_temp - 40) / 60),
        "vram_used_mb": last_vram,
        "temp_c": last_temp,
    }
    metrics["fitness"] = calculate_fitness(metrics)
    return metrics


# ══════════════════════════════════════════════════════════════════════════════
# OPTIMIZE ONE GENE (binary search + fine-tune)
# ══════════════════════════════════════════════════════════════════════════════

def optimize_gene(gene_def: dict, best_genes: dict[str, Any],
                  server_url: str, port: int, runs: int,
                  ctx_size: int, log: list) -> Any:
    """Find optimal value for one gene using binary search."""
    name = gene_def["name"]
    current = best_genes[name]
    print(f"\n  ── Optimizing: {name} (current={current}, weight={gene_def['weight']}) ──")

    if gene_def["type"] == "choice":
        # Binary choice: just test both
        best_val = current
        best_fit = 0
        for val in gene_def["probes"]:
            test_genes = dict(best_genes)
            test_genes[name] = val
            m = bench(test_genes, server_url, port, runs, ctx_size)
            f = m.get("fitness", 0)
            decode = m.get("decode_tps", 0)
            log.append({"gene": name, "value": val, "fitness": f,
                        "decode_tps": decode, "type": "probe"})
            marker = " 👑" if f > best_fit else ""
            print(f"    {name}={val}: fitness={f:.4f} decode={decode:.1f}t/s{marker}")
            if f > best_fit:
                best_fit = f
                best_val = val
        print(f"    Best: {name}={best_val} (fitness={best_fit:.4f})")
        return best_val

    # Integer gene: binary search
    lo = gene_def["min"]
    hi = gene_def["max"]
    step = gene_def.get("step", 1)

    # Phase 1: Probe extreme values
    print(f"    Phase 1: Probing extremes {gene_def['probes']}")
    probe_results = {}
    for val in gene_def["probes"]:
        test_genes = dict(best_genes)
        test_genes[name] = val
        m = bench(test_genes, server_url, port, runs, ctx_size)
        f = m.get("fitness", 0)
        decode = m.get("decode_tps", 0)
        probe_results[val] = f
        log.append({"gene": name, "value": val, "fitness": f,
                    "decode_tps": decode, "type": "probe"})
        print(f"    {name}={val}: fitness={f:.4f} decode={decode:.1f}t/s")

    # Find which region is best
    sorted_probes = sorted(probe_results.items(), key=lambda x: x[1], reverse=True)
    best_probe = sorted_probes[0][0]
    print(f"    Best probe: {name}={best_probe}")

    # Phase 2: Binary search around best probe
    # Determine search window
    if best_probe <= gene_def["probes"][0]:
        # Best is at low end → search [min, mid]
        lo = gene_def["min"]
        hi = gene_def["probes"][1] if len(gene_def["probes"]) > 1 else (lo + hi) // 2
    elif best_probe >= gene_def["probes"][-1]:
        # Best is at high end → search [mid, max]
        lo = gene_def["probes"][-2] if len(gene_def["probes"]) > 1 else (lo + hi) // 2
        hi = gene_def["max"]
    else:
        # Best is in middle → search around it
        lo = max(gene_def["min"], best_probe - (hi - lo) // 4)
        hi = min(gene_def["max"], best_probe + (hi - lo) // 4)

    print(f"    Phase 2: Binary search [{lo}, {hi}]")
    best_val = best_probe
    best_fit = probe_results[best_probe]

    while (hi - lo) > step * 3:
        mid = ((lo + hi) // 2 // step) * step  # Snap to step
        if mid == lo or mid == hi:
            break
        test_genes = dict(best_genes)
        test_genes[name] = mid
        m = bench(test_genes, server_url, port, runs, ctx_size)
        f = m.get("fitness", 0)
        decode = m.get("decode_tps", 0)
        log.append({"gene": name, "value": mid, "fitness": f,
                    "decode_tps": decode, "type": "binary"})
        print(f"    {name}={mid}: fitness={f:.4f} decode={decode:.1f}t/s")

        if f > best_fit:
            best_fit = f
            best_val = mid

        # Decide direction
        if f > best_fit * 0.99:  # Close enough
            # Test both sides
            test_lo = dict(best_genes)
            test_lo[name] = max(lo, mid - step * 2)
            m_lo = bench(test_lo, server_url, port, runs, ctx_size)
            f_lo = m_lo.get("fitness", 0)

            test_hi = dict(best_genes)
            test_hi[name] = min(hi, mid + step * 2)
            m_hi = bench(test_hi, server_url, port, runs, ctx_size)
            f_hi = m_hi.get("fitness", 0)

            log.append({"gene": name, "value": test_lo[name], "fitness": f_lo,
                        "decode_tps": m_lo.get("decode_tps", 0), "type": "probe"})
            log.append({"gene": name, "value": test_hi[name], "fitness": f_hi,
                        "decode_tps": m_hi.get("decode_tps", 0), "type": "probe"})
            print(f"    {name}={test_lo[name]}: fitness={f_lo:.4f}")
            print(f"    {name}={test_hi[name]}: fitness={f_hi:.4f}")

            if f_lo > f_hi and f_lo > f:
                hi = mid
            elif f_hi > f_lo and f_hi > f:
                lo = mid
            else:
                break  # Both sides worse, we're at peak
        elif f > best_fit:
            # Improvement in this direction
            if mid > best_val:
                lo = mid
            else:
                hi = mid
        else:
            # Got worse, narrow from other side
            if mid > best_val:
                hi = mid
            else:
                lo = mid

    # Phase 3: Fine-tune ±step around best
    print(f"    Phase 3: Fine-tune around {best_val}")
    for delta in [-step, step]:
        test_val = best_val + delta
        if test_val < gene_def["min"] or test_val > gene_def["max"]:
            continue
        test_genes = dict(best_genes)
        test_genes[name] = test_val
        m = bench(test_genes, server_url, port, runs, ctx_size)
        f = m.get("fitness", 0)
        decode = m.get("decode_tps", 0)
        log.append({"gene": name, "value": test_val, "fitness": f,
                    "decode_tps": decode, "type": "fine"})
        print(f"    {name}={test_val}: fitness={f:.4f} decode={decode:.1f}t/s")
        if f > best_fit:
            best_fit = f
            best_val = test_val

    print(f"    ✅ Best: {name}={best_val} (fitness={best_fit:.4f})")
    return best_val


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Fast directional tuning")
    parser.add_argument("--runs", type=int, default=1,
                        help="Runs per benchmark (1=fast, 3=accurate)")
    parser.add_argument("--log-dir", type=str, required=True)
    parser.add_argument("--server", type=str, default="http://127.0.0.1:8080")
    parser.add_argument("--ctx-size", type=int, default=196608)
    args = parser.parse_args()

    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    server_url = args.server
    port = int(server_url.rsplit(":", 1)[-1])

    print("🚀 Fast Directional Tuning — llama.cpp")
    print(f"  Server:    {server_url}")
    print(f"  Context:   {args.ctx_size}")
    print(f"  Runs/test: {args.runs}")
    print(f"  Genes:     {len(GENE_SEARCH)}")
    print()

    log = []
    best_genes = dict(BASELINE)
    total_benchmarks = 0

    # Step 1: Baseline measurement
    print("═══ BASELINE ═══")
    m = bench(best_genes, server_url, port, args.runs, args.ctx_size)
    baseline_fitness = m.get("fitness", 0)
    baseline_decode = m.get("decode_tps", 0)
    print(f"  Fitness: {baseline_fitness:.4f}")
    print(f"  Decode:  {baseline_decode:.1f} t/s")
    print(f"  VRAM:    {m.get('vram_used_mb', '?')} MiB")
    print(f"  Temp:    {m.get('temp_c', '?')}C")
    log.append({"gene": "baseline", "value": "baseline",
                "fitness": baseline_fitness, "decode_tps": baseline_decode,
                "type": "baseline"})
    total_benchmarks += 1

    # Step 2: Optimize each gene independently
    print("\n═══ GENE OPTIMIZATION ═══")
    for gene_def in GENE_SEARCH:
        val = optimize_gene(gene_def, best_genes, server_url, port,
                           args.runs, args.ctx_size, log)
        best_genes[gene_def["name"]] = val
        total_benchmarks += 1  # rough count

    # Step 3: Test combination of all best genes
    print("\n═══ COMBINATION TEST ═══")
    changes = {k: v for k, v in best_genes.items() if v != BASELINE[k]}
    if changes:
        print(f"  Best genes differ from baseline:")
        for k, v in changes.items():
            print(f"    {k}: {BASELINE[k]} -> {v}")
        print(f"\n  Testing combination...")
        m = bench(best_genes, server_url, port, args.runs, args.ctx_size)
        combo_fitness = m.get("fitness", 0)
        combo_decode = m.get("decode_tps", 0)
        print(f"  Combination fitness: {combo_fitness:.4f}")
        print(f"  Combination decode:  {combo_decode:.1f} t/s")
        log.append({"gene": "combination", "value": "all_best",
                    "fitness": combo_fitness, "decode_tps": combo_decode,
                    "type": "combination"})
    else:
        combo_fitness = baseline_fitness
        combo_decode = baseline_decode
        print(f"  No changes from baseline — already optimal!")

    # Step 4: Summary
    print(f"\n{'='*60}")
    print(f"  RESULTS SUMMARY")
    print(f"{'='*60}")
    print(f"  Baseline fitness:  {baseline_fitness:.4f}")
    print(f"  Optimized fitness: {combo_fitness:.4f}")
    delta = combo_fitness - baseline_fitness
    print(f"  Improvement:       {delta:+.4f} ({delta/max(baseline_fitness,0.001)*100:+.1f}%)")
    print(f"  Baseline decode:   {baseline_decode:.1f} t/s")
    print(f"  Optimized decode:  {combo_decode:.1f} t/s")
    print(f"  Decode delta:      {combo_decode - baseline_decode:+.1f} t/s")

    if changes:
        print(f"\n  Optimal config:")
        for g in GENES:
            v = best_genes[g["name"]]
            d = g["default"]
            marker = " <-- CHANGED" if v != d else ""
            print(f"    {g['name']:20s}: {str(v):6s}  (was {d}){marker}")
    else:
        print(f"\n  Config is already optimal!")

    # Save results
    summary = {
        "baseline": {"fitness": baseline_fitness, "decode_tps": baseline_decode},
        "optimized": {"fitness": combo_fitness, "decode_tps": combo_decode},
        "improvement": {"fitness_delta": delta, "decode_delta": combo_decode - baseline_decode},
        "best_genes": best_genes,
        "changes_from_baseline": changes,
        "gene_log": log,
    }
    (log_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\n  Logs: {log_dir}/summary.json")


if __name__ == "__main__":
    main()
