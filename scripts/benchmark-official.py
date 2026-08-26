#!/usr/bin/env python3
"""
benchmark-official.py — Official reproducible benchmark for llama.cpp MoE inference.

Measures peak AND sustained throughput with full hardware telemetry.
Distinguishes between thermal states to prevent misleading comparisons.

Usage:
  python3 benchmark-official.py                          # Run all configs
  python3 benchmark-official.py --config baseline         # Run one config
  python3 benchmark-official.py --sustained-only 120      # Sustained only, 120s
  python3 benchmark-official.py --peak-only               # Peak only (quick)

Protocol:
  1. Stop systemd service
  2. For each config:
     a. Start server, wait for health
     b. PEAK phase: 3 rapid requests (cold start)
     c. SUSTAINED phase: continuous requests for N seconds
     d. Record all metrics at each step
  3. Compute statistics (median, mean, stdev, P10, P90)
  4. Generate report with peak vs sustained distinction
  5. Save raw data to docs/benchmarks/results/<timestamp>/
  6. Restart systemd service
"""

import subprocess, time, json, os, sys, signal, argparse, hashlib
from urllib.request import Request, urlopen
from urllib.error import URLError
from datetime import datetime

# ── Paths ────────────────────────────────────────────────────────────
UPSTREAM = "/nix/store/n7n3jfqfxdbb74kzqk2bhjdgs56byirv-llama-cpp-10273/bin/llama-server"
WACKMALL_WRAPPER = "/home/nixos/projects/nixos-ai/modules/ai/llama-wackmall-wrapper.sh"
MODEL = "/nix/store/in9pq5ak2mj5km4f6r87v295bfm53w6c-Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
MMPROJ = "/nix/store/fc4lc40lbcp1mi0vqq4d4780d8vf3w5p-mmproj-BF16.gguf"
PORT = 18080
RESULTS_BASE = "docs/benchmarks/results"

# ── Benchmark Parameters ─────────────────────────────────────────────
PROMPT = "Explain quantum entanglement in simple terms."
WARMUP_TOKENS = 20
WARMUP_REQUESTS = 3
PEAK_RUNS = 3           # Rapid requests for peak measurement
SUSTAINED_SECONDS = 90  # Continuous inference for sustained measurement
COOLDOWN_SECONDS = 60   # Between configs for thermal recovery
THERMAL_COLD_MAX_C = 62  # GPU temp must be below this for a 'cold' run

# ── Configurations ───────────────────────────────────────────────────
CONFIGS = {
    "baseline": {
        "description": "All MoE on CPU (upstream default)",
        "binary": UPSTREAM,
        "args": [
            "-ngl", "45", "-t", "8", "-c", "4096",
            "-b", "512", "-ub", "512",
            "-fa", "on", "-ctk", "q4_0", "-ctv", "q4_0",
            "--n-cpu-moe", "99", "--split-mode", "layer",
            "--no-mmproj-offload", "--parallel", "1",
            "--jinja", "--no-warmup",
        ],
    },
    "ncmoe35": {
        "description": "MoE layers 0-34 on CPU, 35-44 on GPU",
        "binary": UPSTREAM,
        "args": [
            "-ngl", "45", "-t", "8", "-c", "4096",
            "-b", "512", "-ub", "512",
            "-fa", "on", "-ctk", "q4_0", "-ctv", "q4_0",
            "--n-cpu-moe", "35", "--split-mode", "layer",
            "--no-mmproj-offload", "--parallel", "1",
            "--jinja", "--no-warmup",
        ],
    },
    "ehs25": {
        "description": "Expert Hot Store 25 slots (wackmall fork)",
        "binary": WACKMALL_WRAPPER,
        "args": [
            "-ngl", "45", "-t", "8", "-c", "8192",
            "-b", "512", "-ub", "512",
            "-fa", "on", "-ctk", "q4_0", "-ctv", "q4_0",
            "-ehs", "25", "--split-mode", "layer",
            "--parallel", "1", "--jinja",
        ],
    },
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def check_thermal_state():
    """Check initial GPU thermal state. Returns (is_cold, gpu_temp, gpu_clock)."""
    gpu = get_gpu_stats()
    temp = gpu.get("gpu_temp_c", 0)
    clock = gpu.get("gpu_sm_mhz", 0)
    is_cold = temp <= THERMAL_COLD_MAX_C
    status = "COLD" if is_cold else "WARM"
    log(f"  Thermal state: {status} (GPU {temp}°C, {clock} MHz, threshold {THERMAL_COLD_MAX_C}°C)")
    return is_cold, temp, clock


def get_git_commit(path):
    # Try git first (works for project dirs)
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"],
                          capture_output=True, text=True, timeout=5, cwd=path)
        commit = r.stdout.strip()
        if commit and len(commit) >= 4:
            return commit
    except Exception:
        pass
    # Fallback: extract from nix store path (check dir, not file)
    # e.g. /nix/store/...-llama-cpp-10273/bin/llama-server -> 10273
    try:
        import re
        # Walk up to find a dir with numeric suffix
        check_path = path
        for _ in range(5):  # max 5 levels up
            check_path = os.path.dirname(check_path)
            if not check_path or check_path == "/":
                break
            basename = os.path.basename(check_path)
            match = re.search(r'-(\d{4,})$', basename)
            if match:
                return f"nix-{match.group(1)}"
    except Exception:
        pass
    return "unknown"


def get_gpu_stats():
    try:
        r = subprocess.run(
            ["nvidia-smi",
             "--query-gpu=clocks.current.sm,clocks.current.memory,"
             "temperature.gpu,power.draw,utilization.gpu,memory.used,memory.total",
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
            "vram_total_mb": int(parts[6]),
        }
    except Exception as e:
        return {"error": str(e)}


def get_cpu_freq_mhz():
    ecore_max, pcore_max = 0, 0
    try:
        for i in range(4):
            path = f"/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_cur_freq"
            if os.path.exists(path):
                with open(path) as f:
                    freq = int(f.read().strip()) // 1000
                    if freq > ecore_max: ecore_max = freq
        for i in range(4, 8):
            path = f"/sys/devices/system/cpu/cpu{i}/cpufreq/scaling_cur_freq"
            if os.path.exists(path):
                with open(path) as f:
                    freq = int(f.read().strip()) // 1000
                    if freq > pcore_max: pcore_max = freq
    except Exception:
        pass
    return ecore_max, pcore_max


def get_ram_used_mb():
    try:
        r = subprocess.run(["free", "-m"], capture_output=True, text=True, timeout=5)
        for line in r.stdout.split("\n"):
            if line.startswith("Mem:"):
                return int(line.split()[2])
    except Exception:
        pass
    return 0


def kill_server():
    subprocess.run(["pkill", "-9", "-f", "llama-server"], capture_output=True)
    try:
        r = subprocess.run(["lsof", "-ti", f":{PORT}"],
                          capture_output=True, text=True, timeout=5)
        for pid_str in r.stdout.strip().split():
            if pid_str.isdigit():
                os.kill(int(pid_str), signal.SIGKILL)
    except Exception:
        pass
    time.sleep(2)


def start_server(name, config):
    kill_server()
    binary = config["binary"]
    cmd = [binary, "-m", MODEL, "--mmproj", MMPROJ,
           "--host", "0.0.0.0", "--port", str(PORT)] + config["args"]

    log(f"  Starting: {name} ({os.path.basename(binary)})")
    log_path = f"/tmp/bench-{name}.log"
    with open(log_path, "w") as f:
        proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT,
                               stdin=subprocess.DEVNULL, start_new_session=True)
    for i in range(90):
        try:
            r = subprocess.run(["curl", "-sf", f"http://127.0.0.1:{PORT}/health"],
                              capture_output=True, timeout=5)
            if r.returncode == 0:
                log(f"  Server UP after {i+1}s (PID {proc.pid})")
                return proc.pid
        except Exception:
            pass
        time.sleep(1)
    log(f"  FAILED after 90s")
    proc.kill()
    return None


def do_request(max_tokens=128, prompt=PROMPT):
    data = json.dumps({
        "model": "local",
        "messages": [{"role": "user", "content": prompt}],
        "max_tokens": max_tokens,
        "temperature": 0,
    }).encode()
    req = Request(f"http://127.0.0.1:{PORT}/v1/chat/completions",
                  data=data, headers={"Content-Type": "application/json"})
    start_ns = time.time_ns()
    try:
        resp = urlopen(req, timeout=120)
        d = json.loads(resp.read())
        end_ns = time.time_ns()
        return end_ns - start_ns, d
    except Exception as e:
        return None, str(e)


def collect_snapshot(pid):
    """Collect all hardware metrics at current moment."""
    gpu = get_gpu_stats()
    ecore, pcore = get_cpu_freq_mhz()
    ram = get_ram_used_mb()
    return {
        "timestamp": time.time(),
        "gpu_sm_mhz": gpu.get("gpu_sm_mhz", 0),
        "gpu_mem_mhz": gpu.get("gpu_mem_mhz", 0),
        "gpu_temp_c": gpu.get("gpu_temp_c", 0),
        "gpu_power_w": gpu.get("gpu_power_w", 0),
        "gpu_util_pct": gpu.get("gpu_util_pct", 0),
        "vram_used_mb": gpu.get("vram_used_mb", 0),
        "vram_total_mb": gpu.get("vram_total_mb", 0),
        "ecore_mhz": ecore,
        "pcore_mhz": pcore,
        "ram_used_mb": ram,
    }


def run_request(pid, max_tokens=128, prompt=PROMPT):
    """Single request with full metrics snapshot."""
    snap_pre = collect_snapshot(pid)
    elapsed_ns, resp = do_request(max_tokens, prompt)
    snap_post = collect_snapshot(pid)

    if elapsed_ns is None:
        return None, snap_pre, snap_post

    timings = resp.get("timings", {})
    return {
        "tg_tok_s": timings.get("predicted_per_second", 0),
        "pp_tok_s": timings.get("prompt_per_second", 0),
        "predicted_tokens": timings.get("predicted_n", 0),
        "prompt_tokens": timings.get("prompt_n", 0),
        "wall_time_ms": elapsed_ns / 1e6,
        "eval_time_ms": timings.get("eval_time", 0) * 1000,
        "prompt_eval_time_ms": timings.get("prompt_eval_time", 0) * 1000,
    }, snap_pre, snap_post


def warmup(n=WARMUP_REQUESTS):
    log(f"  Warmup: {n} requests...")
    for i in range(n):
        do_request(max_tokens=WARMUP_TOKENS, prompt="Hi")
        time.sleep(0.5)


def measure_peak(pid, runs=PEAK_RUNS):
    """Peak measurement: rapid requests after warmup."""
    results = []
    for run in range(1, runs + 1):
        data, snap_pre, snap_post = run_request(pid)
        if data is None:
            log(f"    Peak run {run}: FAILED")
            continue
        data["run"] = run
        data["phase"] = "peak"
        data["snapshot"] = snap_post
        results.append(data)
        log(f"    Peak {run}: TG={data['tg_tok_s']:.1f} tok/s "
            f"GPU={snap_post['gpu_sm_mhz']}MHz {snap_post['gpu_temp_c']}°C "
            f"V={snap_post['vram_used_mb']}MB")
        time.sleep(0.5)
    return results


def measure_sustained(pid, duration=SUSTAINED_SECONDS):
    """Sustained measurement: continuous requests for N seconds."""
    results = []
    start_time = time.time()
    run = 0
    while True:
        elapsed = time.time() - start_time
        if elapsed >= duration:
            break
        run += 1
        data, snap_pre, snap_post = run_request(pid)
        if data is None:
            log(f"    Sustained run {run}: FAILED")
            continue
        data["run"] = run
        data["phase"] = "sustained"
        data["elapsed_s"] = round(elapsed, 1)
        data["snapshot"] = snap_post
        results.append(data)
        if run % 5 == 0 or run == 1:
            log(f"    Sustained {run} ({elapsed:.0f}s): TG={data['tg_tok_s']:.1f} "
                f"GPU={snap_post['gpu_sm_mhz']}MHz {snap_post['gpu_temp_c']}°C")
        time.sleep(0.3)
    return results


def compute_phase_stats(results, phase):
    """Compute statistics for a phase (peak or sustained)."""
    phase_runs = [r for r in results if r.get("phase") == phase]
    if not phase_runs:
        return None

    tgs = [r["tg_tok_s"] for r in phase_runs]
    gpu_temps = [r["snapshot"]["gpu_temp_c"] for r in phase_runs]
    gpu_powers = [r["snapshot"]["gpu_power_w"] for r in phase_runs]
    gpu_utils = [r["snapshot"]["gpu_util_pct"] for r in phase_runs]
    gpu_sm = [r["snapshot"]["gpu_sm_mhz"] for r in phase_runs]
    vrams = [r["snapshot"]["vram_used_mb"] for r in phase_runs]
    pcores = [r["snapshot"]["pcore_mhz"] for r in phase_runs]
    rams = [r["snapshot"]["ram_used_mb"] for r in phase_runs]

    tgs_sorted = sorted(tgs)
    n = len(tgs_sorted)
    mean_tg = sum(tgs) / n

    # Efficiency metrics
    avg_power = sum(gpu_powers) / n
    tokens_per_watt = mean_tg / avg_power if avg_power > 0 else 0
    avg_temp = sum(gpu_temps) / n
    max_temp = max(gpu_temps)

    return {
        "n_runs": n,
        "tg_mean": round(mean_tg, 2),
        "tg_median": round(tgs_sorted[n // 2], 2),
        "tg_min": round(min(tgs), 2),
        "tg_max": round(max(tgs), 2),
        "tg_p10": round(tgs_sorted[max(0, n // 10)], 2),
        "tg_p90": round(tgs_sorted[min(n - 1, int(n * 0.9))], 2),
        "tg_stdev": round((sum((x - mean_tg)**2 for x in tgs) / n) ** 0.5, 2),
        "gpu_temp_mean": round(avg_temp, 1),
        "gpu_temp_max": max_temp,
        "gpu_power_mean": round(avg_power, 1),
        "gpu_util_mean": round(sum(gpu_utils) / n, 1),
        "gpu_sm_mean": round(sum(gpu_sm) / n, 0),
        "vram_mean": round(sum(vrams) / n, 0),
        "pcore_mean": round(sum(pcores) / n, 0),
        "ram_mean": round(sum(rams) / n, 0),
        "tokens_per_watt": round(tokens_per_watt, 4),
        "tokens_per_joule": round(tokens_per_watt, 4),  # Same as tokens/watt for steady state
    }


def classify_result(peak_stats, sustained_stats):
    """Classify the result as PEAK_IMPROVEMENT, SUSTAINED_IMPROVEMENT, etc."""
    if not peak_stats or not sustained_stats:
        return "INCOMPLETE"

    peak_tg = peak_stats["tg_mean"]
    sustained_tg = sustained_stats["tg_mean"]
    degradation = sustained_tg / peak_tg if peak_tg > 0 else 0

    if degradation > 0.90:
        return "STABLE"
    elif degradation > 0.70:
        return "MODERATE_THROTTLING"
    elif degradation > 0.50:
        return "SEVERE_THROTTLING"
    else:
        return "EXTREME_THROTTLING"


def generate_report(config_name, config, peak_stats, sustained_stats, classification, raw_results, initial_temp_c=None, initial_gpu_clock_mhz=None, is_cold_start=None):
    """Generate human-readable report."""
    lines = []
    lines.append(f"# Benchmark Report: {config_name}")
    lines.append(f"")
    lines.append(f"**Timestamp:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    lines.append(f"**Config:** {config['description']}")
    lines.append(f"**Classification:** {classification}")
    if is_cold_start is not None:
        cold_str = "YES" if is_cold_start else "NO (WARM START — results may be affected by residual heat)"
        lines.append(f"**Cold start:** {cold_str}")
    if initial_temp_c is not None:
        lines.append(f"**Initial GPU temp:** {initial_temp_c}°C")
    if initial_gpu_clock_mhz is not None:
        lines.append(f"**Initial GPU clock:** {initial_gpu_clock_mhz} MHz")
    lines.append(f"")

    # Environment
    lines.append(f"## Environment")
    lines.append(f"")
    lines.append(f"| Item | Value |")
    lines.append(f"|------|-------|")
    lines.append(f"| GPU | NVIDIA RTX 4050 Laptop (6 GB VRAM) |")
    lines.append(f"| GPU Driver | 595.71.05 |")
    lines.append(f"| GPU Compute Cap | 8.9 (Ada Lovelace) |")
    lines.append(f"| CPU | Intel i7-13620H (6P+4E cores) |")
    lines.append(f"| RAM | 32 GB DDR5 |")
    lines.append(f"| OS Kernel | 7.1.8-zen1 |")
    lines.append(f"| Model | Qwen3.6-35B-A3B Q4_K_M (~21 GiB) |")
    lines.append(f"| llama.cpp binary | {os.path.basename(config['binary'])} |")
    lines.append(f"| llama.cpp commit | {get_git_commit(os.path.dirname(config['binary']))} |")
    lines.append(f"| nixos-ai commit | {get_git_commit('.')} |")
    lines.append(f"")

    # Configuration
    args_str = " ".join(config["args"])
    lines.append(f"## Configuration")
    lines.append(f"")
    lines.append(f"```")
    lines.append(f"{os.path.basename(config['binary'])} -m MODEL --mmproj MMPROJ {args_str}")
    lines.append(f"```")
    lines.append(f"")

    # Peak results
    if peak_stats:
        lines.append(f"## PEAK Performance (cold start, first {peak_stats['n_runs']} requests)")
        lines.append(f"")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| **TG tok/s** | **{peak_stats['tg_mean']:.1f}** (median {peak_stats['tg_median']:.1f}) |")
        lines.append(f"| TG range | {peak_stats['tg_min']:.1f} – {peak_stats['tg_max']:.1f} |")
        lines.append(f"| TG stdev | {peak_stats['tg_stdev']:.2f} |")
        lines.append(f"| GPU clock | {peak_stats['gpu_sm_mean']:.0f} MHz |")
        lines.append(f"| GPU temp | {peak_stats['gpu_temp_mean']:.1f}°C (max {peak_stats['gpu_temp_max']}°C) |")
        lines.append(f"| GPU power | {peak_stats['gpu_power_mean']:.1f} W |")
        lines.append(f"| GPU util | {peak_stats['gpu_util_mean']:.0f}% |")
        lines.append(f"| VRAM | {peak_stats['vram_mean']:.0f} MB |")
        lines.append(f"| CPU P-core | {peak_stats['pcore_mean']:.0f} MHz |")
        lines.append(f"| RAM | {peak_stats['ram_mean']:.0f} MB |")
        lines.append(f"| Efficiency | {peak_stats['tokens_per_watt']:.4f} tok/s/W |")
        lines.append(f"")

    # Sustained results
    if sustained_stats:
        # Calculate actual duration from data
        sus_runs = [r for r in raw_results if r.get("phase") == "sustained"]
        if sus_runs:
            actual_duration = max(r.get("elapsed_s", 0) for r in sus_runs)
        else:
            actual_duration = SUSTAINED_SECONDS
        lines.append(f"## SUSTAINED Performance ({actual_duration:.0f}s continuous load)")
        lines.append(f"")
        lines.append(f"| Metric | Value |")
        lines.append(f"|--------|-------|")
        lines.append(f"| **TG tok/s** | **{sustained_stats['tg_mean']:.1f}** (median {sustained_stats['tg_median']:.1f}) |")
        lines.append(f"| TG range | {sustained_stats['tg_min']:.1f} – {sustained_stats['tg_max']:.1f} |")
        lines.append(f"| TG stdev | {sustained_stats['tg_stdev']:.2f} |")
        lines.append(f"| GPU clock | {sustained_stats['gpu_sm_mean']:.0f} MHz |")
        lines.append(f"| GPU temp | {sustained_stats['gpu_temp_mean']:.1f}°C (max {sustained_stats['gpu_temp_max']}°C) |")
        lines.append(f"| GPU power | {sustained_stats['gpu_power_mean']:.1f} W |")
        lines.append(f"| GPU util | {sustained_stats['gpu_util_mean']:.0f}% |")
        lines.append(f"| VRAM | {sustained_stats['vram_mean']:.0f} MB |")
        lines.append(f"| CPU P-core | {sustained_stats['pcore_mean']:.0f} MHz |")
        lines.append(f"| RAM | {sustained_stats['ram_mean']:.0f} MB |")
        lines.append(f"| Efficiency | {sustained_stats['tokens_per_watt']:.4f} tok/s/W |")
        lines.append(f"")

    # Peak vs Sustained comparison
    if peak_stats and sustained_stats:
        peak_tg = peak_stats["tg_mean"]
        sus_tg = sustained_stats["tg_mean"]
        degradation_pct = (1 - sus_tg / peak_tg) * 100 if peak_tg > 0 else 0
        lines.append(f"## Peak vs Sustained")
        lines.append(f"")
        lines.append(f"| Metric | Peak | Sustained | Delta |")
        lines.append(f"|--------|------|-----------|-------|")
        lines.append(f"| TG tok/s | {peak_tg:.1f} | {sus_tg:.1f} | {degradation_pct:.1f}% degradation |")
        lines.append(f"| GPU clock | {peak_stats['gpu_sm_mean']:.0f} MHz | {sustained_stats['gpu_sm_mean']:.0f} MHz | |")
        lines.append(f"| GPU temp | {peak_stats['gpu_temp_mean']:.1f}°C | {sustained_stats['gpu_temp_mean']:.1f}°C | |")
        lines.append(f"| GPU power | {peak_stats['gpu_power_mean']:.1f} W | {sustained_stats['gpu_power_mean']:.1f} W | |")
        lines.append(f"| Efficiency | {peak_stats['tokens_per_watt']:.4f} | {sustained_stats['tokens_per_watt']:.4f} | |")
        lines.append(f"")
        lines.append(f"**Classification: {classification}**")
        if classification == "EXTREME_THROTTLING" or classification == "SEVERE_THROTTLING":
            lines.append(f"")
            lines.append(f"⚠️ **Peak improvement without sustained improvement.** The peak number "
                        f"({peak_tg:.1f} tok/s) is NOT representative of real-world usage.")
        lines.append(f"")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Official llama.cpp benchmark")
    parser.add_argument("--config", type=str, default=None,
                       help="Run single config (baseline/ncmoe35/ehs25)")
    parser.add_argument("--sustained-only", type=int, default=None,
                       help="Skip peak, run sustained for N seconds")
    parser.add_argument("--peak-only", action="store_true",
                       help="Skip sustained, run peak only")
    parser.add_argument("--cooldown", type=int, default=COOLDOWN_SECONDS,
                       help="Cooldown between configs")
    parser.add_argument("--order", type=str, default=None,
                       help="Comma-separated config order (e.g. 'baseline,ncmoe35' or 'ncmoe35,baseline')")
    args = parser.parse_args()

    if args.order:
        configs_to_run = [c.strip() for c in args.order.split(",")]
    elif args.config:
        configs_to_run = [args.config]
    else:
        configs_to_run = ["baseline", "ncmoe35"]
    # Add ehs25 only if wackmall binary exists
    if args.config == "ehs25" or (not args.config and os.path.exists(WACKMALL_WRAPPER)):
        if "ehs25" not in configs_to_run:
            configs_to_run.append("ehs25")

    log(f"{'='*60}")
    log(f"OFFICIAL BENCHMARK")
    log(f"Configs: {configs_to_run}")
    log(f"Peak runs: {PEAK_RUNS}, Sustained: {SUSTAINED_SECONDS}s")
    log(f"Cooldown: {args.cooldown}s between configs")
    log(f"{'='*60}")

    # Stop systemd service
    subprocess.run(["sudo", "systemctl", "stop", "llama-cpp-server.service"],
                    capture_output=True)
    time.sleep(3)

    all_results = {}
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")

    for i, config_name in enumerate(configs_to_run):
        config = CONFIGS.get(config_name)
        if config is None:
            log(f"Unknown config: {config_name}, skipping")
            continue

        log(f"\n{'─'*50}")
        log(f"Config {i+1}/{len(configs_to_run)}: {config_name} — {config['description']}")
        log(f"{'─'*50}")

        pid = start_server(config_name, config)
        if pid is None:
            all_results[config_name] = {"status": "FAILED"}
            continue

        # Check thermal state
        is_cold, initial_temp, initial_clock = check_thermal_state()

        # Warmup
        warmup(WARMUP_REQUESTS)

        # Peak measurement
        peak_results = []
        if not args.sustained_only:
            peak_results = measure_peak(pid, PEAK_RUNS)

        # Sustained measurement
        sus_results = []
        if not args.peak_only:
            sus_results = measure_sustained(pid, args.sustained_only or SUSTAINED_SECONDS)

        # Compute stats
        all_runs = peak_results + sus_results
        peak_stats = compute_phase_stats(all_runs, "peak")
        sustained_stats = compute_phase_stats(all_runs, "sustained")
        classification = classify_result(peak_stats, sustained_stats)

        # Store results
        all_results[config_name] = {
            "status": "OK",
            "initial_temp_c": initial_temp,
            "initial_gpu_clock_mhz": initial_clock,
            "is_cold_start": is_cold,
            "peak_stats": peak_stats,
            "sustained_stats": sustained_stats,
            "classification": classification,
            "raw_runs": all_runs,
        }

        # Print summary
        if peak_stats:
            log(f"  PEAK:    {peak_stats['tg_mean']:.1f} tok/s "
                f"(GPU {peak_stats['gpu_sm_mean']:.0f}MHz, "
                f"{peak_stats['gpu_temp_mean']:.1f}°C, "
                f"{peak_stats['gpu_power_mean']:.1f}W)")
        if sustained_stats:
            log(f"  SUSTAINED: {sustained_stats['tg_mean']:.1f} tok/s "
                f"(GPU {sustained_stats['gpu_sm_mean']:.0f}MHz, "
                f"{sustained_stats['gpu_temp_mean']:.1f}°C, "
                f"{sustained_stats['gpu_power_mean']:.1f}W)")
        cold_tag = "COLD" if is_cold else "WARM"
        log(f"  CLASSIFICATION: {classification} ({cold_tag} start @ {initial_temp}°C)")

        # Kill server + cooldown
        kill_server()
        if i < len(configs_to_run) - 1:
            log(f"  Cooling down {args.cooldown}s...")
            time.sleep(args.cooldown)

    # ── Generate reports ──────────────────────────────────────────────
    log(f"\n{'='*60}")
    log(f"GENERATING REPORTS")
    log(f"{'='*60}")

    # Create results directory
    results_dir = os.path.join(RESULTS_BASE, timestamp)
    os.makedirs(results_dir, exist_ok=True)

    for config_name, result in all_results.items():
        if result["status"] != "OK":
            continue

        config = CONFIGS[config_name]
        report = generate_report(
            config_name, config,
            result["peak_stats"], result["sustained_stats"],
            result["classification"], result["raw_runs"],
            result.get("initial_temp_c"), result.get("initial_gpu_clock_mhz"),
            result.get("is_cold_start")
        )

        # Write report
        report_path = os.path.join(results_dir, f"{config_name}.md")
        with open(report_path, "w") as f:
            f.write(report)
        log(f"  Report: {report_path}")

        # Write raw JSON
        json_path = os.path.join(results_dir, f"{config_name}.json")
        with open(json_path, "w") as f:
            json.dump({
                "config": config_name,
                "timestamp": timestamp,
                "initial_temp_c": result.get("initial_temp_c"),
                "initial_gpu_clock_mhz": result.get("initial_gpu_clock_mhz"),
                "is_cold_start": result.get("is_cold_start"),
                "peak_stats": result["peak_stats"],
                "sustained_stats": result["sustained_stats"],
                "classification": result["classification"],
                "raw_runs": result["raw_runs"],
            }, f, indent=2)
        log(f"  Raw: {json_path}")

    # Write comparison summary
    summary_path = os.path.join(results_dir, "summary.md")
    with open(summary_path, "w") as f:
        f.write(f"# Benchmark Summary — {timestamp}\n\n")
        f.write(f"| Config | Peak TG | Sustained TG | Degradation | Classification |\n")
        f.write(f"|--------|---------|-------------|-------------|----------------|\n")
        for name, result in all_results.items():
            if result["status"] != "OK":
                f.write(f"| {name} | FAILED | — | — | — |\n")
                continue
            ps = result["peak_stats"]
            ss = result["sustained_stats"]
            peak = f"{ps['tg_mean']:.1f}" if ps else "—"
            sus = f"{ss['tg_mean']:.1f}" if ss else "—"
            if ps and ss:
                deg = f"{(1 - ss['tg_mean']/ps['tg_mean'])*100:.1f}%"
            else:
                deg = "—"
            f.write(f"| {name} | {peak} | {sus} | {deg} | {result['classification']} |\n")
        f.write(f"\n**Legend:**\n")
        f.write(f"- **STABLE**: <10% degradation peak→sustained\n")
        f.write(f"- **MODERATE_THROTTLING**: 10-30% degradation\n")
        f.write(f"- **SEVERE_THROTTLING**: 30-50% degradation\n")
        f.write(f"- **EXTREME_THROTTLING**: >50% degradation\n")
    log(f"  Summary: {summary_path}")

    # ── Print final summary ───────────────────────────────────────────
    print(f"\n{'='*70}")
    print(f"BENCHMARK RESULTS — {timestamp}")
    print(f"{'='*70}")
    print(f"{'Config':<12} │ {'Peak':>8} │ {'Sustained':>10} │ {'Degrad':>8} │ {'Class'}")
    print(f"{'─'*12}─┼─{'─'*8}─┼─{'─'*10}─┼─{'─'*8}─┼─{'─'*20}")
    for name, result in all_results.items():
        if result["status"] != "OK":
            print(f"{name:<12} │ {'FAILED':>8}")
            continue
        ps = result["peak_stats"]
        ss = result["sustained_stats"]
        peak = f"{ps['tg_mean']:.1f}" if ps else "—"
        sus = f"{ss['tg_mean']:.1f}" if ss else "—"
        if ps and ss:
            deg = f"{(1 - ss['tg_mean']/ps['tg_mean'])*100:.1f}%"
        else:
            deg = "—"
        print(f"{name:<12} │ {peak:>8} │ {sus:>10} │ {deg:>8} │ {result['classification']}")

    # Restart systemd service
    subprocess.run(["sudo", "systemctl", "start", "llama-cpp-server.service"],
                    capture_output=True)
    log("\nSystemd service restarted.")
    log(f"Results saved to: {results_dir}/")


if __name__ == "__main__":
    main()
