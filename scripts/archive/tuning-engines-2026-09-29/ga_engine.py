#!/usr/bin/env python3
"""ga_engine.py — Genetic Algorithm Engine for llama.cpp tuning.

Optimizes llama-server flags by evolving configurations through
selection, crossover, and mutation. Fitness is weighted with
decode_tokens_per_second as the dominant metric.

Usage:
    python3 ga_engine.py --dry-run          # Show gene space
    python3 ga_engine.py --baseline-only    # Test current config
    python3 ga_engine.py --gens 5 --pop 6   # Run GA
"""
from __future__ import annotations
import argparse
import json
import math
import os
import random
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

# ══════════════════════════════════════════════════════════════════════════════
# GENE DEFINITIONS
# ══════════════════════════════════════════════════════════════════════════════
# weight: 0-1, higher = more important = less mutation
GENES: list[dict[str, Any]] = [
    {"name": "gpuLayers", "type": "int", "min": 30, "max": 50,
     "default": 45, "weight": 0.9, "step": 1,
     "desc": "Layers on GPU (VRAM budget critical)"},
    {"name": "kvCacheType", "type": "choice", "choices": ["q4_0", "q8_0"],
     "default": "q4_0", "weight": 0.7,
     "desc": "KV cache quantization (VRAM vs precision)"},
    {"name": "kvUnified", "type": "choice", "choices": [True, False],
     "default": True, "weight": 0.5,
     "desc": "Unified KV cache"},
    {"name": "threads", "type": "int", "min": 6, "max": 20,
     "default": 12, "weight": 0.6, "step": 1,
     "desc": "CPU threads (i7-13620H: 20 cores)"},
    {"name": "nCpuMoe", "type": "int", "min": 0, "max": 99,
     "default": 99, "weight": 0.8, "step": 5,
     "desc": "MoE experts on CPU (0=all GPU, 99=all CPU)"},
    {"name": "batchSize", "type": "choice", "choices": [512, 1024, 2048],
     "default": 1024, "weight": 0.3,
     "desc": "Batch size (prefill throughput)"},
    {"name": "ubatch", "type": "choice", "choices": [512, 1024, 2048],
     "default": 1024, "weight": 0.3,
     "desc": "Micro-batch size"},
    {"name": "parallel", "type": "int", "min": 1, "max": 4,
     "default": 2, "weight": 0.4, "step": 1,
     "desc": "Concurrent slots (tool calls)"},
    {"name": "prio", "type": "int", "min": 0, "max": 3,
     "default": 2, "weight": 0.3, "step": 1,
     "desc": "CPU scheduling priority"},
    {"name": "prioBatch", "type": "int", "min": 0, "max": 3,
     "default": 3, "weight": 0.3, "step": 1,
     "desc": "Batch scheduling priority"},
    {"name": "reasoningPreserve", "type": "choice", "choices": [True, False],
     "default": True, "weight": 0.5,
     "desc": "Preserve thinking trace (Qwen3)"},
    {"name": "noWarmup", "type": "choice", "choices": [True, False],
     "default": True, "weight": 0.4,
     "desc": "Skip warmup (+2% throughput)"},
]

# ══════════════════════════════════════════════════════════════════════════════
# FITNESS WEIGHTS
# ══════════════════════════════════════════════════════════════════════════════
FITNESS_WEIGHTS = {
    "decode_tps": 0.40,
    "consistency": 0.25,
    "prefill_tps": 0.15,
    "vram_headroom": 0.10,
    "temperature": 0.10,
}

PROMPT_SIZE = 60


# ══════════════════════════════════════════════════════════════════════════════
# INDIVIDUAL MANAGEMENT
# ══════════════════════════════════════════════════════════════════════════════

def create_random_individual():
    genes = {}
    for g in GENES:
        if g["type"] == "int":
            values = list(range(g["min"], g["max"] + 1, g["step"]))
            genes[g["name"]] = random.choice(values)
        elif g["type"] == "choice":
            genes[g["name"]] = random.choice(g["choices"])
    return {"genes": genes, "fitness": None, "metrics": None}


def create_initial_population(size):
    population = []
    baseline = {g["name"]: g["default"] for g in GENES}
    population.append({"genes": baseline, "fitness": None, "metrics": None})
    while len(population) < size:
        population.append(create_random_individual())
    return population


# ══════════════════════════════════════════════════════════════════════════════
# MUTATION
# ══════════════════════════════════════════════════════════════════════════════

def mutate_gene(genes, gene_def, mutation_rate):
    current = genes[gene_def["name"]]
    adjusted_rate = mutation_rate * (1.0 - gene_def["weight"] * 0.5)
    if random.random() > adjusted_rate:
        return current
    if gene_def["type"] == "int":
        max_step = max(1, gene_def["step"] * int(3 * (1 - gene_def["weight"])))
        step = random.randint(-max_step, max_step)
        new_val = current + step
        new_val = max(gene_def["min"], min(gene_def["max"], new_val))
        new_val = round(new_val / gene_def["step"]) * gene_def["step"]
        return new_val
    elif gene_def["type"] == "choice":
        if random.random() < gene_def["weight"]:
            return current
        return random.choice(gene_def["choices"])
    return current


def mutate_individual(individual, mutation_rate):
    new_genes = dict(individual["genes"])
    for g in GENES:
        new_genes[g["name"]] = mutate_gene(new_genes, g, mutation_rate)
    return {"genes": new_genes, "fitness": None, "metrics": None}


# ══════════════════════════════════════════════════════════════════════════════
# CROSSOVER (uniform)
# ══════════════════════════════════════════════════════════════════════════════

def crossover(parent1, parent2):
    child_genes = {}
    for g in GENES:
        child_genes[g["name"]] = (parent1["genes"][g["name"]]
                                  if random.random() < 0.5
                                  else parent2["genes"][g["name"]])
    return {"genes": child_genes, "fitness": None, "metrics": None}


# ══════════════════════════════════════════════════════════════════════════════
# SELECTION (tournament)
# ══════════════════════════════════════════════════════════════════════════════

def tournament_select(population, tournament_size=3):
    candidates = random.sample(population, min(tournament_size, len(population)))
    return max(candidates, key=lambda x: x["fitness"] or -1)


# ══════════════════════════════════════════════════════════════════════════════
# SERVER ARGS
# ══════════════════════════════════════════════════════════════════════════════

def build_server_args(genes):
    args = []
    args.extend(["-ngl", str(genes["gpuLayers"])])
    args.extend(["-t", str(genes["threads"])])
    args.extend(["-b", str(genes["batchSize"])])
    args.extend(["-ub", str(genes["ubatch"])])
    args.extend(["--parallel", str(genes["parallel"])])
    args.extend(["--n-cpu-moe", str(genes["nCpuMoe"])])
    args.extend(["--split-mode", "layer"])
    args.extend(["--poll", "50"])
    args.extend(["--poll-batch", "50"])
    args.extend(["--prio", str(genes["prio"])])
    args.extend(["--prio-batch", str(genes["prioBatch"])])
    args.extend(["-ctk", str(genes["kvCacheType"])])
    args.extend(["-ctv", str(genes["kvCacheType"])])
    args.extend(["-fa", "on"])
    if genes["kvUnified"]:
        args.append("--kv-unified")
    if genes["reasoningPreserve"]:
        args.append("--reasoning-preserve")
    if genes["noWarmup"]:
        args.append("--no-warmup")
    args.extend(["--no-mmproj-offload"])
    args.extend(["--cont-batching"])
    return args


def _find_server_and_model() -> tuple[str, str]:
    """Extract llama-server binary path and model path from systemd wrapper."""
    server_bin = os.environ.get("LLAMA_SERVER_BIN", "")
    model_path = os.environ.get("LLAMA_MODEL_PATH", "")
    if server_bin and model_path:
        return server_bin, model_path
    try:
        result = subprocess.run(
            ["systemctl", "cat", "llama-cpp-server"],
            capture_output=True, text=True, timeout=5)
        for line in result.stdout.splitlines():
            if "ExecStart=" in line:
                wrapper = line.split("=", 1)[1].strip()
                wr = subprocess.run(["cat", wrapper],
                                   capture_output=True, text=True, timeout=5)
                for wline in wr.stdout.splitlines():
                    wline = wline.strip()
                    if wline.startswith("exec ") and "llama-server" in wline:
                        # exec /nix/store/.../bin/llama-server ...
                        server_bin = wline.split()[1]
                    if "-m " in wline and '"' in wline and not wline.startswith("exec"):
                        s = wline.find('"') + 1
                        e = wline.rfind('"')
                        if s > 0 and e > s:
                            model_path = wline[s:e]
                break
    except Exception:
        pass
    # Fallback: try which/nix-store
    if not server_bin:
        try:
            r = subprocess.run(["bash", "-c",
                "systemctl cat llama-cpp-server | grep 'exec ' | awk '{print $2}'"],
                capture_output=True, text=True, timeout=5)
            server_bin = r.stdout.strip()
        except Exception:
            pass
    return server_bin, model_path


def build_full_command(args, ctx_size=196608, port=8080):
    """Build llama-server command on the same port as production."""
    server_bin, model_path = _find_server_and_model()
    if not server_bin or not model_path:
        return ["echo", "Model or server not found"]
    cmd = [server_bin, "-m", model_path,
           "--host", "0.0.0.0", "--port", str(port),
           "-c", str(ctx_size)]
    cmd.extend(args)
    return cmd


# ══════════════════════════════════════════════════════════════════════════════
# BENCHMARK
# ══════════════════════════════════════════════════════════════════════════════

def run_single_benchmark(server_url="http://127.0.0.1:8080", prompt_size=PROMPT_SIZE):
    prompt = "O rapido raposa marrom pula sobre o cao preguicoso. " * prompt_size
    payload = {
        "prompt": prompt + "\n\nResuma o texto acima em uma frase.",
        "n_predict": 128, "cache_prompt": False,
        "temperature": 0, "seed": 42, "ignore_eos": True,
    }
    start_ns = time.time_ns()
    try:
        result = subprocess.run(
            ["curl", "-s", f"{server_url}/completion",
             "-H", "Content-Type: application/json",
             "-d", json.dumps(payload)],
            capture_output=True, text=True, timeout=120)
        end_ns = time.time_ns()
        wall_ms = (end_ns - start_ns) // 1_000_000
        data = json.loads(result.stdout)
        timings = data.get("timings", {})
        metrics = {
            "wall_ms": wall_ms,
            "prompt_n": timings.get("prompt_n", 0),
            "prompt_ms": timings.get("prompt_ms", 0),
            "prefill_tps": timings.get("prompt_per_second", 0),
            "predicted_n": timings.get("predicted_n", 0),
            "predicted_ms": timings.get("predicted_ms", 0),
            "decode_tps": timings.get("predicted_per_second", 0),
        }
    except Exception as e:
        metrics = {"error": str(e), "wall_ms": 0,
                   "prefill_tps": 0, "decode_tps": 0}
    try:
        smi = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=memory.used,memory.total,temperature.gpu,utilization.gpu",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5)
        if smi.returncode == 0:
            parts = smi.stdout.strip().split(", ")
            metrics["vram_used_mb"] = int(parts[0])
            metrics["vram_total_mb"] = int(parts[1])
            metrics["temperature_c"] = int(parts[2])
            metrics["gpu_util_pct"] = int(parts[3])
    except Exception:
        pass
    return metrics


def benchmark_individual(individual, server_url, runs, ctx_size=196608):
    """Benchmark an individual. Starts a test server, runs benchmarks, stops it.
    
    Each run restarts the server on port 8080 to ensure consistent startup
    state (no stale KV cache, no warm GPU state leaking between configs).
    The user stops Roo Dev before running the GA.
    
    Args:
        ctx_size: Context size for test server. Use smaller (32768) for fast
                  triage, full (196608) for final validation.
    """
    all_metrics = []
    # Extract port from server_url (e.g. http://127.0.0.1:8080 -> 8080)
    port = int(server_url.rsplit(":", 1)[-1])
    args = build_server_args(individual["genes"])
    cmd = build_full_command(args, ctx_size=ctx_size, port=port)
    if cmd[0] == "echo":
        return {"error": "model not found", "decode_tps": 0,
                "prefill_tps": 0, "consistency": 0,
                "vram_headroom": 0, "temperature": 100}
    for run_idx in range(runs):
        # Kill any existing llama-server on this port
        subprocess.run(["pkill", "-f", f"llama-server.*--port {port}"],
                       capture_output=True, timeout=5)
        time.sleep(3)  # Let port release + GPU cool
        # Start server with this individual's config
        proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL,
                                stderr=subprocess.DEVNULL)
        # Exponential backoff health check (2s, 4s, 8s, ... up to 60s)
        ready = False
        wait = 2
        max_wait = 60
        while wait <= max_wait:
            time.sleep(wait)
            try:
                resp = subprocess.run(
                    ["curl", "-sf", f"{server_url}/health"],
                    capture_output=True, timeout=2)
                if resp.returncode == 0:
                    ready = True
                    break
            except Exception:
                pass
            wait = min(wait * 2, max_wait)
        if not ready:
            proc.kill()
            proc.wait()
            return {"error": "server timeout", "decode_tps": 0,
                    "prefill_tps": 0, "consistency": 0,
                    "vram_headroom": 0, "temperature": 100}
        # Warmup request (lets CUDA kernels compile, KV cache allocate)
        run_single_benchmark(server_url=server_url)
        time.sleep(2)
        # Actual benchmark
        m = run_single_benchmark(server_url=server_url)
        all_metrics.append(m)
        # Stop server
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        # Cool down between runs
        if run_idx < runs - 1:
            time.sleep(5)
    # Compute averaged metrics
    decode_vals = [m.get("decode_tps", 0) for m in all_metrics if "error" not in m]
    prefill_vals = [m.get("prefill_tps", 0) for m in all_metrics if "error" not in m]
    if not decode_vals:
        return {"error": "all runs failed", "decode_tps": 0,
                "prefill_tps": 0, "consistency": 0,
                "vram_headroom": 0, "temperature": 100}
    avg_decode = sum(decode_vals) / len(decode_vals)
    avg_prefill = sum(prefill_vals) / len(prefill_vals)
    # Consistency: coefficient of variation (lower = more stable)
    if len(decode_vals) > 1 and avg_decode > 0:
        std_dev = (sum((x - avg_decode)**2 for x in decode_vals) / len(decode_vals)) ** 0.5
        consistency = max(0, 1.0 - (std_dev / avg_decode) * 10)
    else:
        consistency = 0.5
    vram = all_metrics[-1].get("vram_used_mb", 0)
    vram_total = all_metrics[-1].get("vram_total_mb", 6144)
    vram_headroom = max(0, 1.0 - (vram / vram_total))
    temp = all_metrics[-1].get("temperature_c", 80)
    temperature_score = max(0, 1.0 - (temp - 40) / 60)
    return {
        "decode_tps": avg_decode, "prefill_tps": avg_prefill,
        "consistency": consistency, "vram_headroom": vram_headroom,
        "temperature": temperature_score, "vram_used_mb": vram,
        "vram_total_mb": vram_total, "temp_c": temp, "raw_runs": all_metrics,
    }


# ══════════════════════════════════════════════════════════════════════════════
# FITNESS
# ══════════════════════════════════════════════════════════════════════════════

NORM_RANGES = {
    "decode_tps": (0, 50), "prefill_tps": (0, 500),
    "consistency": (0, 1), "vram_headroom": (0, 1), "temperature": (0, 1),
}


def calculate_fitness(metrics):
    if metrics.get("error"):
        return 0.0
    total = 0.0
    for name, weight in FITNESS_WEIGHTS.items():
        raw = metrics.get(name, 0)
        lo, hi = NORM_RANGES[name]
        norm = max(0, min(1, (raw - lo) / (hi - lo))) if hi > lo else 0
        total += weight * norm
    return round(total, 6)


# ══════════════════════════════════════════════════════════════════════════════
# BREEDING
# ══════════════════════════════════════════════════════════════════════════════

def breed_next_generation(population, pop_size, elitism,
                          mutation_rate, crossover_rate):
    next_gen = [{"genes": dict(ind["genes"]),
                 "fitness": None, "metrics": None}
                for ind in population[:elitism]]
    while len(next_gen) < pop_size:
        p1 = tournament_select(population)
        p2 = tournament_select(population)
        if random.random() < crossover_rate:
            child = crossover(p1, p2)
        else:
            child = {"genes": dict(p1["genes"]),
                     "fitness": None, "metrics": None}
        child = mutate_individual(child, mutation_rate)
        next_gen.append(child)
    return next_gen


# ══════════════════════════════════════════════════════════════════════════════
# LOGGING
# ══════════════════════════════════════════════════════════════════════════════

def format_individual(ind):
    parts = []
    for g in GENES:
        v = ind["genes"][g["name"]]
        if v != g["default"]:
            parts.append(f"{g['name']}={v}")
    return " ".join(parts) if parts else "(baseline)"


def log_generation(gen, population, log_dir):
    (log_dir / f"generation_{gen:03d}.json").write_text(json.dumps({
        "generation": gen,
        "timestamp": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "individuals": [{
            "genes": ind["genes"], "fitness": ind["fitness"],
            "metrics": {k: v for k, v in (ind["metrics"] or {}).items()
                        if k != "raw_runs"},
        } for ind in population]
    }, indent=2))


def append_convergence(log_dir, gen, best, avg, worst, best_tps):
    csv_file = log_dir / "convergence.csv"
    if not csv_file.exists():
        csv_file.write_text(
            "generation,best_fitness,avg_fitness,"
            "worst_fitness,best_decode_tps\n")
    with open(csv_file, "a") as f:
        f.write(f"{gen},{best:.6f},{avg:.6f},{worst:.6f},{best_tps:.1f}\n")


# ══════════════════════════════════════════════════════════════════════════════
# BASELINE & DRY RUN
# ══════════════════════════════════════════════════════════════════════════════

def run_baseline(log_dir, server_url, runs, ctx_size=196608, port=8080):
    print("\n=== BASELINE MODE ===")
    print(f"Port: {port}, Context: {ctx_size}")
    baseline = {g["name"]: g["default"] for g in GENES}
    ind = {"genes": baseline, "fitness": None, "metrics": None}
    print(f"Testing: {format_individual(ind)}")
    metrics = benchmark_individual(ind, server_url, runs,
                                  ctx_size=ctx_size)
    fitness = calculate_fitness(metrics)
    ind["metrics"] = metrics
    ind["fitness"] = fitness
    print(f"  Fitness:     {fitness:.4f}")
    print(f"  Decode:      {metrics.get('decode_tps', 0):.1f} t/s")
    print(f"  Prefill:     {metrics.get('prefill_tps', 0):.0f} t/s")
    print(f"  Consistency: {metrics.get('consistency', 0):.2f}")
    print(f"  VRAM:        {metrics.get('vram_used_mb', '?')}/{metrics.get('vram_total_mb', '?')} MiB")
    print(f"  Temp:        {metrics.get('temp_c', '?')}C")
    (log_dir / "summary.json").write_text(json.dumps({
        "baseline": {"genes": baseline, "fitness": fitness,
                     "metrics": {k: v for k, v in metrics.items()
                                 if k != "raw_runs"}}
    }, indent=2))


def show_dry_run():
    print("DRY RUN - Gene space:")
    print()
    for g in GENES:
        if g["type"] == "choice":
            print(f"  {g['name']:20s}: {str(g['choices']):30s}  "
                  f"default={g['default']}  weight={g['weight']}")
        else:
            print(f"  {g['name']:20s}: {g['min']:3d}-{g['max']:<3d}  "
                  f"default={g['default']}  weight={g['weight']}  "
                  f"step={g['step']}")
        print(f"    {g['desc']}")
    print()
    print("Fitness weights:")
    for name, weight in FITNESS_WEIGHTS.items():
        print(f"  {name:20s}: {weight:.0%}")


# ══════════════════════════════════════════════════════════════════════════════
# MAIN
# ══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="GA Benchmark for llama.cpp")
    parser.add_argument("--gens", type=int, default=5)
    parser.add_argument("--pop", type=int, default=6)
    parser.add_argument("--runs", type=int, default=3)
    parser.add_argument("--mutation-rate", type=float, default=0.3)
    parser.add_argument("--crossover-rate", type=float, default=0.7)
    parser.add_argument("--elitism", type=int, default=2)
    parser.add_argument("--resume", type=int, default=0)
    parser.add_argument("--server", type=str, default="http://127.0.0.1:8080")
    parser.add_argument("--port", type=int, default=8080,
                        help="Port for test server (same as production)")
    parser.add_argument("--log-dir", type=str, required=True)
    parser.add_argument("--ctx-size", type=int, default=196608,
                        help="Context size for test server (smaller = faster init)")
    parser.add_argument("--fast", action="store_true",
                        help="Fast mode: 1 run, 32K ctx")
    parser.add_argument("--baseline-only", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    # Sync server URL with port
    args.server = f"http://127.0.0.1:{args.port}"
    # Fast mode overrides
    if args.fast:
        args.runs = 1
        args.ctx_size = 32768
        print("FAST MODE: 1 run, 32K context")
    log_dir = Path(args.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)
    if args.dry_run:
        show_dry_run()
        return
    if args.baseline_only:
        run_baseline(log_dir, args.server, args.runs,
                    ctx_size=args.ctx_size, port=args.port)
        return
    population = create_initial_population(args.pop)
    print(f"Initial population: {len(population)} individuals")
    print(f"  (individual 1 = baseline)")
    best_ever = None
    convergence = []
    for gen in range(args.resume, args.gens):
        gen_start = time.time()
        print(f"\n{'='*60}")
        print(f"  GENERATION {gen+1}/{args.gens}")
        print(f"{'='*60}")
        for i, ind in enumerate(population):
            if ind.get("fitness") is not None:
                print(f"  [{i+1}/{len(population)}] cached "
                      f"fitness={ind['fitness']:.4f}")
                continue
            label = format_individual(ind)
            print(f"  [{i+1}/{len(population)}] {label}")
            metrics = benchmark_individual(ind, args.server, args.runs,
                                         ctx_size=args.ctx_size)
            fitness = calculate_fitness(metrics)
            ind["metrics"] = metrics
            ind["fitness"] = fitness
            print(f"    -> fitness={fitness:.4f} "
                  f"decode={metrics.get('decode_tps', 0):.1f}t/s "
                  f"prefill={metrics.get('prefill_tps', 0):.0f}t/s")
        population.sort(key=lambda x: x["fitness"] or 0, reverse=True)
        if best_ever is None or (population[0]["fitness"] or 0) > (best_ever["fitness"] or 0):
            best_ever = {"genes": dict(population[0]["genes"]),
                         "fitness": population[0]["fitness"],
                         "metrics": dict(population[0]["metrics"] or {})}
        log_generation(gen + 1, population, log_dir)
        fitnesses = [ind["fitness"] or 0 for ind in population]
        best_f = fitnesses[0]
        avg_f = sum(fitnesses) / len(fitnesses)
        worst_f = fitnesses[-1]
        best_tps = population[0]["metrics"].get("decode_tps", 0) if population[0]["metrics"] else 0
        append_convergence(log_dir, gen + 1, best_f, avg_f, worst_f, best_tps)
        gen_time = time.time() - gen_start
        print(f"\n  Gen {gen+1} done ({gen_time:.1f}s)")
        print(f"  Best:  fitness={best_f:.4f}  decode={best_tps:.1f}t/s")
        print(f"  Avg:   fitness={avg_f:.4f}")
        print(f"  Worst: fitness={worst_f:.4f}")
        convergence.append(best_f)
        if len(convergence) >= 3:
            recent = convergence[-3:]
            if all(abs(recent[i+1] - recent[i]) < 0.005 for i in range(2)):
                print(f"\n  Converged! Stable for 3 generations.")
                break
        if gen < args.gens - 1:
            population = breed_next_generation(
                population, args.pop, args.elitism,
                args.mutation_rate, args.crossover_rate)
    print(f"\n{'='*60}")
    print(f"  FINAL RESULTS")
    print(f"{'='*60}")
    print(f"  Best fitness: {best_ever['fitness']:.4f}")
    print(f"  Best decode:  {best_ever['metrics'].get('decode_tps', 0):.1f} t/s")
    print(f"  Best prefill: {best_ever['metrics'].get('prefill_tps', 0):.0f} t/s")
    print(f"\n  Optimal config:")
    for g in GENES:
        v = best_ever["genes"][g["name"]]
        d = g["default"]
        marker = " <-- CHANGED" if v != d else ""
        print(f"    {g['name']:20s}: {str(v):6s}  (was {d}){marker}")
    summary = {
        "best_ever": {
            "genes": best_ever["genes"],
            "fitness": best_ever["fitness"],
            "metrics": {k: v for k, v in best_ever["metrics"].items()
                        if k != "raw_runs"},
            "server_args": build_server_args(best_ever["genes"]),
        },
        "generations_run": len(convergence),
        "convergence": convergence,
        "weights": {
            "fitness": FITNESS_WEIGHTS,
            "genes": {g["name"]: g["weight"] for g in GENES},
        },
    }
    (log_dir / "summary.json").write_text(json.dumps(summary, indent=2))
    print(f"\n  Logs: {log_dir}/summary.json")
    print(f"  To apply: edit modules/ai/models.nix with values above")


if __name__ == "__main__":
    main()
