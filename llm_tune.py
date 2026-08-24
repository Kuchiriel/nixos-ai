#!/usr/bin/env python3
"""llm_tune.py — Tuning unificado do llama.cpp com resume.

3 fases progressivas:
  Phase 1 — Scan rápido: extremos de cada gene (1 run, 32K ctx)
  Phase 2 — Refina: binary search nos genes promissores
  Phase 3 — Valida: combinação final (3 runs, 192K ctx)
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

BASELINE = {g["name"]: g["default"] for g in GENES}

# ══════════════════════════════════════════════════════════════════════════════
# GENE DEFINITIONS (ordered by importance)
# ══════════════════════════════════════════════════════════════════════════════

GENES_TO_TUNE = [
    {"name": "nCpuMoe", "type": "int", "min": 0, "max": 99, "step": 5,
     "weight": 0.8, "probes": [0, 50, 99]},
    {"name": "gpuLayers", "type": "int", "min": 30, "max": 50, "step": 1,
     "weight": 0.9, "probes": [30, 40, 50]},
    {"name": "kvCacheType", "type": "choice", "choices": ["q4_0", "q8_0"],
     "weight": 0.7, "probes": ["q4_0", "q8_0"]},
    {"name": "threads", "type": "int", "min": 6, "max": 20, "step": 1,
     "weight": 0.6, "probes": [6, 12, 20]},
    {"name": "kvUnified", "type": "choice", "choices": [True, False],
     "weight": 0.5, "probes": [True, False]},
    {"name": "reasoningPreserve", "type": "choice", "choices": [True, False],
     "weight": 0.5, "probes": [True, False]},
    {"name": "noWarmup", "type": "choice", "choices": [True, False],
     "weight": 0.4, "probes": [True, False]},
    {"name": "parallel", "type": "int", "min": 1, "max": 4, "step": 1,
     "weight": 0.4, "probes": [1, 2, 4]},
]


# ══════════════════════════════════════════════════════════════════════════════
# BENCHMARK CORE
# ══════════════════════════════════════════════════════════════════════════════

def _get_vram_used() -> int:
    """Query current VRAM usage via nvidia-smi."""
    try:
        r = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
        if r.returncode == 0:
            return int(r.stdout.strip().split("\n")[0])
    except Exception:
        pass
    return -1


def _kill_server_and_wait_vram(port: int, target_vram: int = 200) -> None:
    """Kill server and wait until VRAM is released below target (MiB)."""
    # Kill
    subprocess.run(["pkill", "-9", "-f", f"llama-server.*--port {port}"],
                   capture_output=True, timeout=5)
    # Wait for VRAM to drop
    for i in range(30):
        time.sleep(1)
        vram = _get_vram_used()
        if 0 <= vram <= target_vram:
            return  # VRAM released
    # Fallback: wait extra
    time.sleep(5)


def bench_one(config: dict, server_url: str, port: int,
              runs: int, ctx_size: int) -> dict:
    """Benchmark a single config with clean GPU state between each run."""
    args = build_server_args(config)
    cmd = build_full_command(args, ctx_size=ctx_size, port=port)
    if cmd[0] == "echo":
        return {"error": "not found", "fitness": 0}

    decodes, prefills = [], []
    last_vram, last_vram_total, last_temp = 0, 6144, 80

    for i in range(runs):
        # Kill server + wait for VRAM release
        _kill_server_and_wait_vram(port, target_vram=200)
        time.sleep(2)  # Extra cooldown

        # Start server
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

        # 2 warmup requests (discard) — CUDA kernels compile lazily
        run_single_benchmark(server_url=server_url)
        time.sleep(1)
        run_single_benchmark(server_url=server_url)
        time.sleep(2)

        # Actual benchmark
        m = run_single_benchmark(server_url=server_url)
        decodes.append(m.get("decode_tps", 0))
        prefills.append(m.get("prefill_tps", 0))
        last_vram = m.get("vram_used_mb", 0)
        last_vram_total = m.get("vram_total_mb", 6144)
        last_temp = m.get("temperature_c", 80)

        # Stop server cleanly
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        if i < runs - 1:
            time.sleep(5)  # GPU cooldown between runs

    if not decodes:
        return {"error": "no data", "fitness": 0}

    avg_d = sum(decodes) / len(decodes)
    avg_p = sum(prefills) / len(prefills)
    if len(decodes) > 1 and avg_d > 0:
        std = (sum((x - avg_d)**2 for x in decodes) / len(decodes)) ** 0.5
        consistency = max(0, 1.0 - (std / avg_d) * 10)
    else:
        consistency = 0.5

    metrics = {
        "decode_tps": avg_d, "prefill_tps": avg_p,
        "consistency": consistency,
        "vram_headroom": max(0, 1.0 - (last_vram / last_vram_total)),
        "temperature": max(0, 1.0 - (last_temp - 40) / 60),
        "vram_used_mb": last_vram, "temp_c": last_temp,
        "raw_decodes": decodes,
    }
    metrics["fitness"] = calculate_fitness(metrics)
    return metrics


def test_config(config: dict, label: str, server_url: str, port: int,
                runs: int, ctx_size: int, log: list) -> float:
    """Test one config, print result, log it, return fitness."""
    m = bench_one(config, server_url, port, runs, ctx_size)
    f = m.get("fitness", 0)
    d = m.get("decode_tps", 0)
    vram = m.get("vram_used_mb", "?")
    temp = m.get("temp_c", "?")
    log.append({"label": label, "fitness": f, "decode_tps": d,
                "config": {k: config[k] for k in config if k in
                           [g["name"] for g in GENES_TO_TUNE]}})
    print(f"    {label:40s} fitness={f:.4f} decode={d:.1f}t/s "
          f"VRAM={vram}MiB temp={temp}C")
    return f


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 1: FAST SCAN (extreme values)
# ══════════════════════════════════════════════════════════════════════════════

def phase1_scan(best_genes: dict, server_url: str, port: int,
                log: list, ctx_size: int = 32768) -> dict:
    """Test extreme values of each gene. Returns best value per gene."""
    print(f"\n{'='*60}")
    print("  PHASE 1: Fast Scan (extreme values, 1 run, 32K ctx)")
    print(f"{'='*60}\n")

    # Baseline first
    print("  BASELINE:")
    bf = test_config(best_genes, "baseline", server_url, port, 1, ctx_size, log)
    print()

    results = {}
    for gene in GENES_TO_TUNE:
        name = gene["name"]
        print(f"  ── {name} (weight={gene['weight']}) ──")

        best_val = best_genes[name]
        best_fit = bf

        for probe in gene["probes"]:
            test = dict(best_genes)
            test[name] = probe
            f = test_config(test, f"{name}={probe}", server_url, port,
                           1, ctx_size, log)
            if f > best_fit:
                best_fit = f
                best_val = probe

        results[name] = {"best_val": best_val, "best_fit": best_fit,
                         "range_best": best_val}
        print(f"    → best {name}={best_val} (fitness={best_fit:.4f})\n")

    return results


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 2: BINARY SEARCH (refine winners)
# ══════════════════════════════════════════════════════════════════════════════

def phase2_refine(best_genes: dict, scan_results: dict,
                  server_url: str, port: int,
                  log: list, ctx_size: int = 65536) -> dict:
    """Binary search on genes that showed improvement in Phase 1."""
    print(f"\n{'='*60}")
    print("  PHASE 2: Binary Search (refine winners, 1 run, 64K ctx)")
    print(f"{'='*60}\n")

    refined = {}
    for gene in GENES_TO_TUNE:
        name = gene["name"]
        scan = scan_results.get(name, {})
        improved = scan.get("best_val") != best_genes.get(name, best_genes[name])

        if gene["type"] == "choice" or not improved:
            # Choice genes: already tested both in Phase 1
            # Integers that didn't improve: skip
            refined[name] = best_genes[name]
            status = "skip" if not improved else "already tested"
            print(f"  {name}: {status} (= {best_genes[name]})")
            continue

        # Binary search integer gene
        lo = gene["min"]
        hi = gene["max"]
        step = gene.get("step", 1)
        probe_best = scan.get("best_val", best_genes[name])

        # Narrow window around best probe
        span = (hi - lo) // 4
        lo = max(gene["min"], probe_best - span)
        hi = min(gene["max"], probe_best + span)

        print(f"  ── {name}: searching [{lo}, {hi}] ──")
        best_val = probe_best
        best_fit = 0

        # Test endpoints and midpoint
        test_points = sorted(set([lo, (lo+hi)//2, hi,
                                  probe_best - step, probe_best + step]))
        test_points = [p for p in test_points if lo <= p <= hi]

        for val in test_points:
            val = round(val / step) * step  # snap to step
            if val < gene["min"] or val > gene["max"]:
                continue
            test = dict(best_genes)
            test[name] = val
            f = test_config(test, f"{name}={val}", server_url, port,
                           1, ctx_size, log)
            if f > best_fit:
                best_fit = f
                best_val = val

        refined[name] = best_val
        print(f"    → refined {name}={best_val} (fitness={best_fit:.4f})\n")

    return refined


# ══════════════════════════════════════════════════════════════════════════════
# PHASE 3: VALIDATION (combination + full context)
# ══════════════════════════════════════════════════════════════════════════════

def phase3_validate(best_genes: dict, server_url: str, port: int,
                    log: list, ctx_size: int = 196608) -> dict:
    """Test the combination of all best genes with full context."""
    print(f"\n{'='*60}")
    print("  PHASE 3: Validation (combination, 3 runs, 192K ctx)")
    print(f"{'='*60}\n")

    changes = {k: v for k, v in best_genes.items() if v != BASELINE.get(k)}
    if not changes:
        print("  No changes from baseline — nothing to validate!")
        return best_genes

    print("  Changes from baseline:")
    for k, v in changes.items():
        print(f"    {k}: {BASELINE.get(k, '?')} → {v}")
    print()

    # Test combination
    print("  Testing optimized combination:")
    f_combo = test_config(best_genes, "optimized_combo", server_url, port,
                          3, ctx_size, log)
    print()

    # Test baseline for comparison
    print("  Testing baseline for comparison:")
    f_base = test_config(BASELINE, "baseline_comparison", server_url, port,
                         3, ctx_size, log)
    print()

    if f_combo > f_base:
        print(f"  ✅ Optimized WINS: {f_combo:.4f} vs {f_base:.4f} "
              f"(+{(f_combo - f_base):.4f})")
        return best_genes
    else:
        print(f"  ⚠️  Baseline still better: {f_base:.4f} vs {f_combo:.4f}")
        print(f"  Keeping baseline config.")
        return dict(BASELINE)


# ══════════════════════════════════════════════════════════════════════════════
# STATE MANAGEMENT (resume)
# ══════════════════════════════════════════════════════════════════════════════

def save_state(log_dir: Path, phase: int, best_genes: dict,
               scan_results: dict, log: list) -> None:
    state = {
        "phase": phase,
        "best_genes": best_genes,
        "scan_results": scan_results,
        "log": log,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (log_dir / f"phase{phase}.json").write_text(json.dumps(state, indent=2))

    # Also save current best
    m = bench_one(best_genes, "http://127.0.0.1:8080", 8080, 1, 32768)
    (log_dir / "best.json").write_text(json.dumps({
        "fitness": m.get("fitness", 0),
        "decode_tps": m.get("decode_tps", 0),
        "config": best_genes,
        "config_summary": ", ".join(
            f"{k}={v}" for k, v in best_genes.items()
            if v != BASELINE.get(k)) or "(baseline)",
    }, indent=2))


def load_state(log_dir: Path) -> dict:
    for phase in [3, 2, 1]:
        f = log_dir / f"phase{phase}.json"
        if f.exists():
            return json.loads(f.read_text())
    return {}


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="LLM Tune")
    parser.add_argument("--phase", default="all",
                        choices=["1", "2", "3", "all"])
    parser.add_argument("--resume", action="store_true")
    parser.add_argument("--log-dir", required=True)
    parser.add_argument("--server", default="http://127.0.0.1:8080")
    args = parser.parse_args()

    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    port = int(args.server.rsplit(":", 1)[-1])
    log = []

    # Load state if resuming
    state = load_state(log_dir) if args.resume else {}
    best_genes = state.get("best_genes", dict(BASELINE))
    scan_results = state.get("scan_results", {})
    completed_phases = set()
    for p in [1, 2, 3]:
        if (log_dir / f"phase{p}.json").exists():
            completed_phases.add(p)

    print("🔧 LLM Tune — Tuning unificado")
    print(f"  Server:    {args.server}")
    print(f"  Resume:    {args.resume}")
    print(f"  Done:      phases {completed_phases or 'none'}")
    print(f"  Best so far: fitness={calculate_fitness(bench_one(best_genes, args.server, port, 1, 32768)):.4f}")
    print()

    # Phase 1: Fast scan
    if args.phase in ("1", "all") and 1 not in completed_phases:
        scan_results = phase1_scan(best_genes, args.server, port, log)
        # Update best_genes with scan winners
        for name, result in scan_results.items():
            best_genes[name] = result["best_val"]
        save_state(log_dir, 1, best_genes, scan_results, log)
        print(f"\n  Phase 1 complete. Best genes saved.")
    elif 1 in completed_phases:
        print("  Phase 1: already done, loading results...")
        s = json.loads((log_dir / "phase1.json").read_text())
        scan_results = s.get("scan_results", scan_results)
        best_genes = s.get("best_genes", best_genes)

    # Phase 2: Refine
    if args.phase in ("2", "all") and 2 not in completed_phases:
        best_genes = phase2_refine(best_genes, scan_results,
                                   args.server, port, log)
        save_state(log_dir, 2, best_genes, scan_results, log)
        print(f"\n  Phase 2 complete. Refined genes saved.")
    elif 2 in completed_phases:
        print("  Phase 2: already done, loading results...")
        s = json.loads((log_dir / "phase2.json").read_text())
        best_genes = s.get("best_genes", best_genes)

    # Phase 3: Validate
    if args.phase in ("3", "all") and 3 not in completed_phases:
        best_genes = phase3_validate(best_genes, args.server, port, log)
        save_state(log_dir, 3, best_genes, scan_results, log)
        print(f"\n  Phase 3 complete.")
    elif 3 in completed_phases:
        print("  Phase 3: already done, loading results...")
        s = json.loads((log_dir / "phase3.json").read_text())
        best_genes = s.get("best_genes", best_genes)

    # Final summary
    print(f"\n{'='*60}")
    print("  FINAL RESULTS")
    print(f"{'='*60}")

    m = bench_one(best_genes, args.server, port, 1, 32768)
    m_base = bench_one(BASELINE, args.server, port, 1, 32768)
    f_opt = m.get("fitness", 0)
    f_base = m_base.get("fitness", 0)
    d_opt = m.get("decode_tps", 0)
    d_base = m_base.get("decode_tps", 0)

    print(f"  Baseline:  fitness={f_base:.4f}  decode={d_base:.1f} t/s")
    print(f"  Optimized: fitness={f_opt:.4f}  decode={d_opt:.1f} t/s")
    delta = f_opt - f_base
    print(f"  Delta:     {delta:+.4f} ({delta/max(f_base,0.001)*100:+.1f}%)")

    changes = {k: v for k, v in best_genes.items() if v != BASELINE.get(k)}
    if changes:
        print(f"\n  Optimal config:")
        for g in GENES:
            v = best_genes.get(g["name"], g["default"])
            d = g["default"]
            if v != d:
                print(f"    {g['name']:20s}: {str(v):6s}  (was {d})")
    else:
        print(f"\n  No changes — baseline is already optimal!")

    print(f"\n  Logs: {log_dir}/best.json")


if __name__ == "__main__":
    main()
