#!/usr/bin/env python3
"""grid_engine.py — Focused grid search for llama.cpp tuning.

Instead of random GA mutations, tests specific configurations
in a structured way based on domain knowledge.
"""
from __future__ import annotations
import argparse
import json
import time
from pathlib import Path
from typing import Any

from ga_engine import (
    GENES, FITNESS_WEIGHTS, PROMPT_SIZE, NORM_RANGES,
    build_full_command, build_server_args,
    run_single_benchmark, calculate_fitness,
)

# Baseline config (current production)
BASELINE = {g["name"]: g["default"] for g in GENES}

# ══════════════════════════════════════════════════════════════════════════════
# GRID CONFIGURATIONS
# ══════════════════════════════════════════════════════════════════════════════

# Phase 1: nCpuMoe sweep (most sensitive gene)
# Controls how many MoE experts are routed to CPU vs GPU
# Current: 99 (all CPU). Lower = more on GPU = faster but more VRAM
PHASE_1_NCPCMoe = []
for val in [0, 25, 50, 75, 85, 90, 95, 97, 99]:
    cfg = dict(BASELINE)
    cfg["nCpuMoe"] = val
    PHASE_1_NCPCMoe.append({
        "name": f"nCpuMoe={val}",
        "desc": f"MoE routing: {val} experts on CPU",
        "genes": cfg,
    })

# Phase 2: gpuLayers sweep (VRAM budget)
# Current: 45. Higher = more GPU compute but less VRAM headroom
PHASE_2_GPULAYERS = []
for val in [38, 40, 42, 44, 45, 46, 48]:
    cfg = dict(BASELINE)
    cfg["gpuLayers"] = val
    PHASE_2_GPULAYERS.append({
        "name": f"gpuLayers={val}",
        "desc": f"{val} layers on GPU",
        "genes": cfg,
    })

# Phase 3: Best combinations
# Based on domain knowledge + Phase 1-2 results
PHASE_3_COMBOS = [
    {
        "name": "baseline",
        "desc": "Current production config",
        "genes": dict(BASELINE),
    },
    {
        "name": "more-gpu-experts",
        "desc": "50 experts on GPU (high VRAM, high bandwidth)",
        "genes": {**BASELINE, "nCpuMoe": 50},
    },
    {
        "name": "conservative-gpu",
        "desc": "85 experts on CPU, 42 layers GPU",
        "genes": {**BASELINE, "nCpuMoe": 85, "gpuLayers": 42},
    },
    {
        "name": "aggressive-gpu",
        "desc": "75 experts CPU, 46 layers GPU, q8_0 KV",
        "genes": {**BASELINE, "nCpuMoe": 75, "gpuLayers": 46,
                  "kvCacheType": "q8_0"},
    },
    {
        "name": "max-gpu-layers",
        "desc": "48 layers GPU, nCpuMoe=90",
        "genes": {**BASELINE, "gpuLayers": 48, "nCpuMoe": 90},
    },
]


# ══════════════════════════════════════════════════════════════════════════════
# BENCHMARK RUNNER
# ══════════════════════════════════════════════════════════════════════════════

def run_config(config: dict[str, Any], server_url: str,
               runs: int, ctx_size: int = 196608) -> dict[str, Any]:
    """Run a single configuration and return averaged results."""
    import subprocess
    port = int(server_url.rsplit(":", 1)[-1])
    args = build_server_args(config["genes"])
    cmd = build_full_command(args, ctx_size=ctx_size, port=port)
    if cmd[0] == "echo":
        return {"error": "model not found"}

    all_metrics = []
    for run_idx in range(runs):
        # Kill existing
        subprocess.run(["pkill", "-f", f"llama-server.*--port {port}"],
                       capture_output=True, timeout=5)
        time.sleep(3)

        # Start server
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)

        # Health check with backoff
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
            return {"error": "timeout"}

        # Warmup
        run_single_benchmark(server_url=server_url)
        time.sleep(2)

        # Benchmark
        m = run_single_benchmark(server_url=server_url)
        all_metrics.append(m)

        # Stop
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()

        if run_idx < runs - 1:
            time.sleep(5)

    # Average
    decode_vals = [m.get("decode_tps", 0) for m in all_metrics if "error" not in m]
    prefill_vals = [m.get("prefill_tps", 0) for m in all_metrics if "error" not in m]
    if not decode_vals:
        return {"error": "all runs failed"}

    avg_decode = sum(decode_vals) / len(decode_vals)
    avg_prefill = sum(prefill_vals) / len(prefill_vals)
    if len(decode_vals) > 1 and avg_decode > 0:
        std_dev = (sum((x - avg_decode)**2 for x in decode_vals) / len(decode_vals)) ** 0.5
        consistency = max(0, 1.0 - (std_dev / avg_decode) * 10)
    else:
        consistency = 0.5

    vram = all_metrics[-1].get("vram_used_mb", 0)
    vram_total = all_metrics[-1].get("vram_total_mb", 6144)
    temp = all_metrics[-1].get("temperature_c", 80)

    metrics = {
        "decode_tps": avg_decode,
        "prefill_tps": avg_prefill,
        "consistency": consistency,
        "vram_headroom": max(0, 1.0 - (vram / vram_total)),
        "temperature": max(0, 1.0 - (temp - 40) / 60),
        "vram_used_mb": vram,
        "vram_total_mb": vram_total,
        "temp_c": temp,
        "raw_decode_values": decode_vals,
    }
    metrics["fitness"] = calculate_fitness(metrics)
    return metrics


def run_phase(name: str, configs: list[dict], server_url: str,
              runs: int, log_dir: Path, ctx_size: int = 196608) -> list[dict]:
    """Run a phase of the grid search."""
    print(f"\n{'='*60}")
    print(f"  PHASE: {name}")
    print(f"  {len(configs)} configs × {runs} runs = {len(configs)*runs} benchmarks")
    print(f"{'='*60}\n")

    results = []
    for i, config in enumerate(configs):
        print(f"  [{i+1}/{len(configs)}] {config['name']}: {config['desc']}")
        metrics = run_config(config, server_url, runs, ctx_size=ctx_size)
        result = {
            "name": config["name"],
            "desc": config["desc"],
            "genes": config["genes"],
            "metrics": {k: v for k, v in metrics.items() if k != "raw_decode_values"},
            "raw_decode": metrics.get("raw_decode_values", []),
        }
        results.append(result)

        fitness = metrics.get("fitness", 0)
        decode = metrics.get("decode_tps", 0)
        prefill = metrics.get("prefill_tps", 0)
        vram = metrics.get("vram_used_mb", "?")
        temp = metrics.get("temp_c", "?")
        raw = metrics.get("raw_decode_values", [])
        print(f"    -> fitness={fitness:.4f} decode={decode:.1f}t/s "
              f"prefill={prefill:.0f}t/s VRAM={vram}MiB temp={temp}C")
        if len(raw) > 1:
            print(f"       raw decode values: {', '.join(f'{v:.1f}' for v in raw)}")
        print()

    # Save phase results
    phase_file = log_dir / f"phase_{name.replace(' ', '_').lower()}.json"
    phase_file.write_text(json.dumps(results, indent=2))
    print(f"  Saved: {phase_file}")

    # Rank by fitness
    results.sort(key=lambda x: x["metrics"].get("fitness", 0), reverse=True)
    print(f"\n  Phase {name} — Rankings:")
    for i, r in enumerate(results):
        m = r["metrics"]
        marker = " 👑" if i == 0 else ""
        print(f"    #{i+1}: {r['name']:30s} "
              f"fitness={m.get('fitness',0):.4f} "
              f"decode={m.get('decode_tps',0):.1f}t/s "
              f"VRAM={m.get('vram_used_mb','?')}MiB{marker}")

    return results


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="Grid Search for llama.cpp")
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--phase", type=str, default="all",
                        choices=["1", "2", "3", "all"])
    parser.add_argument("--log-dir", type=str, required=True)
    parser.add_argument("--server", type=str, default="http://127.0.0.1:8080")
    parser.add_argument("--ctx-size", type=int, default=196608)
    args = parser.parse_args()

    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    server_url = args.server
    runs = args.runs
    total_configs = 0
    if args.phase in ("1", "all"):
        total_configs += len(PHASE_1_NCPCMoe)
    if args.phase in ("2", "all"):
        total_configs += len(PHASE_2_GPULAYERS)
    if args.phase in ("3", "all"):
        total_configs += len(PHASE_3_COMBOS)

    est_minutes = (total_configs * runs * 60) / 60  # rough: ~60s per benchmark
    print(f"🔬 Grid Search Benchmark")
    print(f"  Total configs: {total_configs}")
    print(f"  Runs/config:   {runs}")
    print(f"  Est. time:     ~{est_minutes:.0f} min")
    print(f"  Server:        {server_url}")
    print(f"  Context:       {args.ctx_size}")
    print()

    all_results = {}

    # Phase 1: nCpuMoe sweep
    if args.phase in ("1", "all"):
        r = run_phase("nCpuMoe Sweep", PHASE_1_NCPCMoe,
                      server_url, runs, log_dir, args.ctx_size)
        all_results["phase1"] = r

    # Phase 2: gpuLayers sweep
    if args.phase in ("2", "all"):
        r = run_phase("gpuLayers Sweep", PHASE_2_GPULAYERS,
                      server_url, runs, log_dir, args.ctx_size)
        all_results["phase2"] = r

    # Phase 3: Combinations
    if args.phase in ("3", "all"):
        r = run_phase("Best Combos", PHASE_3_COMBOS,
                      server_url, runs, log_dir, args.ctx_size)
        all_results["phase3"] = r

    # Final summary
    print(f"\n{'='*60}")
    print(f"  FINAL SUMMARY")
    print(f"{'='*60}")

    # Find best across all phases
    best_overall = None
    for phase_results in all_results.values():
        for r in phase_results:
            f = r["metrics"].get("fitness", 0)
            if best_overall is None or f > best_overall["metrics"].get("fitness", 0):
                best_overall = r

    if best_overall:
        m = best_overall["metrics"]
        print(f"\n  🏆 BEST CONFIG: {best_overall['name']}")
        print(f"     {best_overall['desc']}")
        print(f"     Fitness:  {m.get('fitness',0):.4f}")
        print(f"     Decode:   {m.get('decode_tps',0):.1f} t/s")
        print(f"     Prefill:  {m.get('prefill_tps',0):.0f} t/s")
        print(f"     VRAM:     {m.get('vram_used_mb','?')}/{m.get('vram_total_mb','?')} MiB")
        print(f"     Temp:     {m.get('temp_c','?')}C")

        # Compare with baseline
        base_fitness = 0.5949  # from earlier baseline run
        best_fitness = m.get("fitness", 0)
        delta = best_fitness - base_fitness
        print(f"\n     vs baseline: {delta:+.4f} ({delta/base_fitness*100:+.1f}%)")

        # Show changed genes
        changes = {k: v for k, v in best_overall["genes"].items()
                   if v != BASELINE[k]}
        if changes:
            print(f"\n     Changed genes:")
            for k, v in changes.items():
                print(f"       {k}: {BASELINE[k]} -> {v}")
        else:
            print(f"\n     No changes from baseline (already optimal!)")

    # Save full summary
    summary = {
        "best_overall": best_overall,
        "phases": all_results,
        "baseline": BASELINE,
    }
    (log_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str))
    print(f"\n  Logs: {log_dir}/summary.json")


if __name__ == "__main__":
    main()
