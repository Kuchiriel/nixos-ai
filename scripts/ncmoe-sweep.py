#!/usr/bin/env python3
"""
ncmoe-sweep.py — Systematic sweep of --n-cpu-moe values for Qwen3.6-35B-A3B.

Protocol:
  1. Kill server + cooldown between configs (thermal recovery)
  2. Start server with specific ncmoe value
  3. Warmup (2 requests)
  4. Measure 3 runs (coarse) or 5 runs (fine) of 128 tokens
  5. Collect: TG tok/s, PP tok/s, VRAM, GPU clock/temp/power/util, CPU freq
  6. Save results to JSON + CSV

Usage:
  python3 ncmoe-sweep.py [--coarse] [--fine] [--configs N1,N2,...] [--runs N]
"""

import subprocess, time, json, os, sys, signal, argparse
from urllib.request import Request, urlopen
from urllib.error import URLError

# ── Config ───────────────────────────────────────────────────────────
UPSTREAM = "/nix/store/n7n3jfqfxdbb74kzqk2bhjdgs56byirv-llama-cpp-10273/bin/llama-server"
MODEL = "/nix/store/in9pq5ak2mj5km4f6r87v295bfm53w6c-Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
MMPROJ = "/nix/store/fc4lc40lbcp1mi0vqq4d4780d8vf3w5p-mmproj-BF16.gguf"
PORT = 18080  # Use non-standard port to avoid conflict with systemd service
PROMPT = "Explain quantum entanglement in simple terms."
GEN_TOKENS = 128
WARMUP_REQUESTS = 2

# ── Coarse sweep: 14 values ─────────────────────────────────────────
COARSE_CONFIGS = [0, 10, 20, 25, 30, 35, 40, 45, 50, 60, 70, 80, 90, 99]
COARSE_RUNS = 3
COARSE_COOLDOWN = 15  # seconds between configs

# ── Fine sweep: determined after coarse ──────────────────────────────
FINE_RUNS = 5
FINE_COOLDOWN = 20  # seconds between configs (more thermal recovery)


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def get_gpu_stats():
    """Return dict with GPU metrics from nvidia-smi."""
    try:
        r = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=clocks.current.sm,clocks.current.memory,"
             "temperature.gpu,power.draw,utilization.gpu,memory.used",
             "--format=csv,noheader,nounits"],
            capture_output=True, text=True, timeout=5
        )
        parts = r.stdout.strip().split(", ")
        return {
            "gpu_sm_mhz": int(parts[0]),
            "gpu_mem_mhz": int(parts[1]),
            "gpu_temp_c": int(parts[2]),
            "gpu_power_w": float(parts[3]),
            "gpu_util_pct": int(parts[4]),
            "vram_used_mb": int(parts[5]),
        }
    except Exception as e:
        return {"error": str(e)}


def get_cpu_freq_mhz():
    """Return (ecore_max, pcore_max) in MHz."""
    ecore_max = 0
    pcore_max = 0
    try:
        for i in range(4):  # E-cores 0-3
            path = f"/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_cur_freq"
            if os.path.exists(path):
                with open(path) as f:
                    freq = int(f.read().strip()) // 1000
                    if freq > ecore_max:
                        ecore_max = freq
        for i in range(4, 8):  # P-cores 4-7
            path = f"/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_cur_freq"
            if os.path.exists(path):
                with open(path) as f:
                    freq = int(f.read().strip()) // 1000
                    if freq > pcore_max:
                        pcore_max = freq
    except Exception:
        pass
    return ecore_max, pcore_max


def get_page_faults(pid):
    """Return (minflt, majflt) from /proc/pid/stat."""
    try:
        with open(f"/proc/{pid}/stat") as f:
            fields = f.read().split()
        return int(fields[9]), int(fields[11])
    except Exception:
        return 0, 0


def kill_server():
    subprocess.run(["pkill", "-9", "-f", f"llama-server"],
                    capture_output=True)
    # Also kill anything on our port via lsof
    try:
        r = subprocess.run(["lsof", "-ti", f":{PORT}"],
                          capture_output=True, text=True, timeout=5)
        for pid_str in r.stdout.strip().split():
            if pid_str.isdigit():
                os.kill(int(pid_str), signal.SIGKILL)
    except Exception:
        pass
    time.sleep(2)


def start_server(ncmoe, ngl=45, threads=8, ctx=4096):
    """Start llama-server and wait for health. Return PID or None."""
    kill_server()

    cmd = [
        UPSTREAM, "-m", MODEL, "--mmproj", MMPROJ,
        "--host", "0.0.0.0", "--port", str(PORT),
        "-c", str(ctx), "-t", str(threads),
        "-b", "512", "-ub", "512", "-ngl", str(ngl),
        "-fa", "on", "-ctk", "q4_0", "-ctv", "q4_0",
        "--n-cpu-moe", str(ncmoe),
        "--split-mode", "layer",
        "--no-mmproj-offload",
        "--parallel", "1",
        "--jinja", "--no-warmup",
    ]

    log(f"  Starting server: ncmoe={ncmoe} ngl={ngl} t={threads} ctx={ctx}")
    log(f"  CMD: {' '.join(cmd)}")

    log_path = f"/tmp/ncmoe-{ncmoe}.log"
    with open(log_path, "w") as f:
        proc = subprocess.Popen(
            cmd, stdout=f, stderr=subprocess.STDOUT,
            stdin=subprocess.DEVNULL, start_new_session=True
        )

    # Wait for health (up to 90s — model load can be slow)
    for i in range(90):
        try:
            r = subprocess.run(
                ["curl", "-sf", f"http://127.0.0.1:{PORT}/health"],
                capture_output=True, timeout=5
            )
            if r.returncode == 0:
                log(f"  Server UP after {i+1}s (PID {proc.pid})")
                return proc.pid
        except Exception:
            pass
        time.sleep(1)

    log(f"  FAILED to start server after 90s")
    # Check log for error
    try:
        with open(log_path) as f:
            lines = f.readlines()
            for line in lines[-10:]:
                log(f"    LOG: {line.rstrip()}")
    except Exception:
        pass
    proc.kill()
    return None


def do_request(max_tokens=GEN_TOKENS, prompt=PROMPT):
    """Send a chat completion request. Return (elapsed_ns, response_dict) or None."""
    data = json.dumps({
        "model": "local",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }).encode()

    req = Request(
        f"http://127.0.0.1:{PORT}/v1/chat/completions",
        data=data,
        headers={"Content-Type": "application/json"}
    )

    start_ns = time.time_ns()
    try:
        resp = urlopen(req, timeout=120)
        d = json.loads(resp.read())
        end_ns = time.time_ns()
        return end_ns - start_ns, d
    except Exception as e:
        return None, str(e)


def warmup(n=WARMUP_REQUESTS):
    log(f"  Warmup: {n} requests...")
    for i in range(n):
        elapsed, resp = do_request(max_tokens=20, prompt="Hi")
        if elapsed is None:
            log(f"    Warmup {i+1}: FAILED ({resp})")
        else:
            log(f"    Warmup {i+1}: {elapsed/1e6:.0f}ms")
        time.sleep(0.5)


def measure(pid, runs=3):
    """Run N measurements. Return list of result dicts."""
    results = []
    for run in range(1, runs + 1):
        # Collect pre-request metrics
        gpu_pre = get_gpu_stats()
        ecore_pre, pcore_pre = get_cpu_freq_mhz()
        minflt_pre, majflt_pre = get_page_faults(pid)

        # Make request
        elapsed_ns, resp = do_request()

        # Collect post-request metrics
        gpu_post = get_gpu_stats()
        ecore_post, pcore_post = get_cpu_freq_mhz()
        minflt_post, majflt_post = get_page_faults(pid)

        if elapsed_ns is None:
            log(f"    Run {run}: FAILED ({resp})")
            results.append({"run": run, "status": "FAILED", "error": str(resp)})
            continue

        # Extract timing from llama.cpp response
        timings = resp.get("timings", {})
        tg = timings.get("predicted_per_second", 0)
        pp = timings.get("prompt_per_second", 0)
        tokens = timings.get("predicted_n", 0)
        prompt_tokens = timings.get("prompt_n", 0)
        eval_time_ms = timings.get("eval_time", 0) * 1000  # seconds -> ms
        prompt_eval_time_ms = timings.get("prompt_eval_time", 0) * 1000

        result = {
            "run": run,
            "status": "OK",
            "tg_tok_s": tg,
            "pp_tok_s": pp,
            "predicted_tokens": tokens,
            "prompt_tokens": prompt_tokens,
            "wall_time_ms": elapsed_ns / 1e6,
            "eval_time_ms": eval_time_ms,
            "prompt_eval_time_ms": prompt_eval_time_ms,
            # GPU
            "gpu_sm_mhz": gpu_post.get("gpu_sm_mhz", 0),
            "gpu_temp_c": gpu_post.get("gpu_temp_c", 0),
            "gpu_power_w": gpu_post.get("gpu_power_w", 0),
            "gpu_util_pct": gpu_post.get("gpu_util_pct", 0),
            "vram_used_mb": gpu_post.get("vram_used_mb", 0),
            # CPU
            "ecore_mhz": ecore_post,
            "pcore_mhz": pcore_post,
            # Page faults
            "minfaults": minflt_post - minflt_pre,
            "majfaults": majflt_post - majflt_pre,
        }
        results.append(result)
        log(f"    Run {run}: TG={tg:.1f} tok/s PP={pp:.1f} tok/s "
            f"tokens={tokens} GPU={gpu_post.get('gpu_sm_mhz',0)}MHz "
            f"{gpu_post.get('gpu_temp_c',0)}°C "
            f"V={gpu_post.get('vram_used_mb',0)}MB "
            f"CPU={ecore_post}/{pcore_post}MHz")
        time.sleep(1)

    return results


def compute_stats(results):
    """Compute summary statistics from a list of run results."""
    ok_runs = [r for r in results if r.get("status") == "OK"]
    if not ok_runs:
        return {"status": "NO_DATA"}

    tgs = [r["tg_tok_s"] for r in ok_runs]
    pps = [r["pp_tok_s"] for r in ok_runs]
    vrams = [r["vram_used_mb"] for r in ok_runs]
    gpu_temps = [r["gpu_temp_c"] for r in ok_runs]
    gpu_powers = [r["gpu_power_w"] for r in ok_runs]
    gpu_utils = [r["gpu_util_pct"] for r in ok_runs]
    gpu_sm = [r["gpu_sm_mhz"] for r in ok_runs]
    pcores = [r["pcore_mhz"] for r in ok_runs]
    ecores = [r["ecore_mhz"] for r in ok_runs]
    minfaults = [r["minfaults"] for r in ok_runs]
    majfaults = [r["majfaults"] for r in ok_runs]

    tgs_sorted = sorted(tgs)
    n = len(tgs_sorted)

    return {
        "n_runs": n,
        "tg_mean": sum(tgs) / n,
        "tg_min": min(tgs),
        "tg_max": max(tgs),
        "tg_median": tgs_sorted[n // 2],
        "tg_p10": tgs_sorted[max(0, n // 10)],
        "tg_p90": tgs_sorted[min(n - 1, int(n * 0.9))],
        "tg_stdev": (sum((x - sum(tgs)/n)**2 for x in tgs) / n) ** 0.5,
        "pp_mean": sum(pps) / n,
        "vram_mean": sum(vrams) / n,
        "gpu_temp_mean": sum(gpu_temps) / n,
        "gpu_power_mean": sum(gpu_powers) / n,
        "gpu_util_mean": sum(gpu_utils) / n,
        "gpu_sm_mean": sum(gpu_sm) / n,
        "pcore_mean": sum(pcores) / n,
        "ecore_mean": sum(ecores) / n,
        "minfaults_mean": sum(minfaults) / n,
        "majfaults_mean": sum(majfaults) / n,
    }


def run_sweep(configs, runs, cooldown, tag="coarse"):
    """Run the full sweep."""
    log(f"{'='*60}")
    log(f"NCMOE SWEEP: {tag} ({len(configs)} configs, {runs} runs each)")
    log(f"Cooldown between configs: {cooldown}s")
    log(f"{'='*60}")

    # Stop systemd service to free port
    subprocess.run(["sudo", "systemctl", "stop", "llama-cpp-server.service"],
                    capture_output=True)
    time.sleep(3)

    all_results = []

    for i, ncmoe in enumerate(configs):
        log(f"\n{'─'*50}")
        log(f"Config {i+1}/{len(configs)}: ncmoe={ncmoe}")
        log(f"{'─'*50}")

        # Start server
        pid = start_server(ncmoe)
        if pid is None:
            all_results.append({
                "ncmoe": ncmoe,
                "status": "FAILED",
                "stats": {},
                "runs": []
            })
            continue

        # Warmup
        warmup(WARMUP_REQUESTS)

        # Measure
        runs_data = measure(pid, runs)

        # Stats
        stats = compute_stats(runs_data)

        all_results.append({
            "ncmoe": ncmoe,
            "status": "OK",
            "stats": stats,
            "runs": runs_data
        })

        if stats.get("tg_mean"):
            log(f"  >>> RESULT: ncmoe={ncmoe} TG={stats['tg_mean']:.1f} "
                f"(±{stats.get('tg_stdev', 0):.1f}) "
                f"VRAM={stats['vram_mean']:.0f}MB "
                f"GPU={stats['gpu_util_mean']:.0f}% "
                f"{stats['gpu_temp_mean']:.0f}°C "
                f"{stats['gpu_power_mean']:.0f}W")

        # Kill server + cooldown
        kill_server()
        if i < len(configs) - 1:  # Don't cooldown after last config
            log(f"  Cooling down {cooldown}s...")
            time.sleep(cooldown)

    return all_results


def print_summary(all_results, tag=""):
    """Print a formatted summary table."""
    print(f"\n{'='*80}")
    print(f"NCMOE SWEEP RESULTS {tag}")
    print(f"{'='*80}")
    print(f"{'ncmoe':>6} │ {'TG tok/s':>10} │ {'±stdev':>7} │ {'VRAM MB':>8} │ "
          f"{'GPU%':>5} │ {'Temp°C':>6} │ {'PowerW':>6} │ {'GPU MHz':>8} │ "
          f"{'Pcore':>6} │ {'Status'}")
    print(f"{'─'*6}─┼─{'─'*10}─┼─{'─'*7}─┼─{'─'*8}─┼─"
          f"{'─'*5}─┼─{'─'*6}─┼─{'─'*6}─┼─{'─'*8}─┼─"
          f"{'─'*6}─┼─{'─'*10}")

    for r in all_results:
        ncmoe = r["ncmoe"]
        if r["status"] == "FAILED":
            print(f"{ncmoe:>6} │ {'FAILED':>10}")
            continue
        s = r["stats"]
        if not s.get("tg_mean"):
            print(f"{ncmoe:>6} │ {'NO DATA':>10}")
            continue
        print(f"{ncmoe:>6} │ {s['tg_mean']:>10.1f} │ {s.get('tg_stdev', 0):>7.1f} │ "
              f"{s['vram_mean']:>8.0f} │ {s['gpu_util_mean']:>5.0f} │ "
              f"{s['gpu_temp_mean']:>6.0f} │ {s['gpu_power_mean']:>6.1f} │ "
              f"{s['gpu_sm_mean']:>8.0f} │ {s['pcore_mean']:>6.0f} │ OK")

    # Find best
    ok_results = [r for r in all_results if r["status"] == "OK" and r["stats"].get("tg_mean")]
    if ok_results:
        best = max(ok_results, key=lambda r: r["stats"]["tg_mean"])
        worst = min(ok_results, key=lambda r: r["stats"]["tg_mean"])
        baseline = next((r for r in ok_results if r["ncmoe"] == 99), None)
        current = next((r for r in ok_results if r["ncmoe"] == 35), None)

        print(f"\n{'─'*80}")
        print(f"BEST:   ncmoe={best['ncmoe']} → {best['stats']['tg_mean']:.1f} tok/s")
        print(f"WORST:  ncmoe={worst['ncmoe']} → {worst['stats']['tg_mean']:.1f} tok/s")
        if baseline:
            print(f"BASELINE (ncmoe=99): {baseline['stats']['tg_mean']:.1f} tok/s")
        if current and current['ncmoe'] != best['ncmoe']:
            print(f"CURRENT (ncmoe=35):  {current['stats']['tg_mean']:.1f} tok/s")
        if baseline:
            speedup = best['stats']['tg_mean'] / baseline['stats']['tg_mean']
            print(f"SPEEDUP vs baseline: {speedup:.3f}x ({(speedup-1)*100:+.1f}%)")


def main():
    parser = argparse.ArgumentParser(description="NCMOE sweep for llama.cpp")
    parser.add_argument("--coarse", action="store_true", default=True,
                       help="Run coarse sweep (default)")
    parser.add_argument("--fine", action="store_true",
                       help="Run fine sweep around optimal")
    parser.add_argument("--configs", type=str, default=None,
                       help="Comma-separated ncmoe values to test")
    parser.add_argument("--runs", type=int, default=None,
                       help="Number of runs per config")
    parser.add_argument("--cooldown", type=int, default=None,
                       help="Cooldown seconds between configs")
    args = parser.parse_args()

    if args.configs:
        configs = [int(x.strip()) for x in args.configs.split(",")]
        runs = args.runs or 3
        cooldown = args.cooldown or 15
        tag = "custom"
    elif args.fine:
        # Fine sweep — will be filled in after coarse
        configs = [28, 30, 32, 34, 36, 38]
        runs = args.runs or FINE_RUNS
        cooldown = args.cooldown or FINE_COOLDOWN
        tag = "fine"
    else:
        configs = COARSE_CONFIGS
        runs = args.runs or COARSE_RUNS
        cooldown = args.cooldown or COARSE_COOLDOWN
        tag = "coarse"

    # Run sweep
    all_results = run_sweep(configs, runs, cooldown, tag)

    # Print summary
    print_summary(all_results, tag.upper())

    # Save results
    output = {
        "tag": tag,
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "hardware": "RTX 4050 6GB, i7-13620H, 32GB DDR5",
        "model": "Qwen3.6-35B-A3B Q4_K_M",
        "upstream_llama_cpp": UPSTREAM,
        "config_base": {
            "ngl": 45, "threads": 8, "ctx": 4096,
            "batch": 512, "ubatch": 512,
            "kv_cache": "q4_0", "flash_attention": "on",
            "split_mode": "layer", "parallel": 1,
        },
        "results": all_results,
    }

    out_path = f"/tmp/ncmoe-sweep-{tag}.json"
    with open(out_path, "w") as f:
        json.dump(output, f, indent=2)
    log(f"\nResults saved to {out_path}")

    # Also save CSV
    csv_path = f"/tmp/ncmoe-sweep-{tag}.csv"
    with open(csv_path, "w") as f:
        f.write("ncmoe,tg_mean,tg_stdev,vram_mean,gpu_util_mean,gpu_temp_mean,"
                "gpu_power_mean,gpu_sm_mean,pcore_mean,ecore_mean,status\n")
        for r in all_results:
            if r["status"] == "OK" and r["stats"].get("tg_mean"):
                s = r["stats"]
                f.write(f"{r['ncmoe']},{s['tg_mean']:.2f},{s.get('tg_stdev',0):.2f},"
                        f"{s['vram_mean']:.0f},{s['gpu_util_mean']:.0f},"
                        f"{s['gpu_temp_mean']:.0f},{s['gpu_power_mean']:.1f},"
                        f"{s['gpu_sm_mean']:.0f},{s['pcore_mean']:.0f},"
                        f"{s['ecore_mean']:.0f},OK\n")
            else:
                f.write(f"{r['ncmoe']},,,,,,,,,-,{r['status']}\n")
    log(f"CSV saved to {csv_path}")

    # Restart systemd service
    subprocess.run(["sudo", "systemctl", "start", "llama-cpp-server.service"],
                    capture_output=True)
    log("Systemd service restarted.")


if __name__ == "__main__":
    main()
