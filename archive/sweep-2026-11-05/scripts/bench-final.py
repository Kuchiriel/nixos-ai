#!/usr/bin/env python3
"""Benchmark multiple llama.cpp configurations systematically."""
import subprocess, time, json, os, signal, sys

UPSTREAM = "/nix/store/n7n3jfqfxdbb74kzqk2bhjdgs56byirv-llama-cpp-10273/bin/llama-server"
MODEL = "/nix/store/in9pq5ak2mj5km4f6r87v295bfm53w6c-Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
PROMPT = "Explain quantum entanglement in simple terms."
PORT = 8080

def start_server(name, extra_args):
    """Start llama-server with given args."""
    subprocess.run(["pkill", "-9", "-f", "llama-server"], capture_output=True)
    time.sleep(3)
    
    cmd = [
        UPSTREAM, "-m", MODEL,
        "--host", "0.0.0.0", "--port", str(PORT),
        "-c", "4096", "-t", "8", "-b", "512", "-ub", "512",
        "-fa", "on", "-ctk", "q4_0", "-ctv", "q4_0",
        "--split-mode", "layer", "--parallel", "1",
        "--jinja", "--no-warmup",
    ] + extra_args
    
    log_path = f"/tmp/srv-{name}.log"
    with open(log_path, "w") as f:
        proc = subprocess.Popen(cmd, stdout=f, stderr=subprocess.STDOUT, 
                               stdin=subprocess.DEVNULL, start_new_session=True)
    
    # Wait for ready
    for i in range(60):
        try:
            r = subprocess.run(["curl", "-sf", f"http://127.0.0.1:{PORT}/health"], 
                             capture_output=True, timeout=5)
            if r.returncode == 0:
                print(f"  Server UP after {i+1}s (PID {proc.pid})")
                return proc
        except:
            pass
        time.sleep(1)
    
    print(f"  FAILED to start server")
    proc.kill()
    return None

def benchmark(proc, warmup=5, runs=5):
    """Warmup and measure TG/PP."""
    import urllib.request
    
    # Warmup
    for _ in range(warmup):
        try:
            data = json.dumps({"model":"local","messages":[{"role":"user","content":"Hi"}],"max_tokens":20,"temperature":0}).encode()
            req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", data=data, 
                                       headers={"Content-Type":"application/json"})
            urllib.request.urlopen(req, timeout=60)
        except:
            pass
        time.sleep(1)
    
    # Measure
    results = []
    for run in range(1, runs+1):
        try:
            data = json.dumps({"model":"local","messages":[{"role":"user","content":PROMPT}],
                              "max_tokens":128,"temperature":0}).encode()
            req = urllib.request.Request(f"http://127.0.0.1:{PORT}/v1/chat/completions", data=data,
                                       headers={"Content-Type":"application/json"})
            resp = urllib.request.urlopen(req, timeout=120)
            d = json.loads(resp.read())
            t = d["timings"]
            tg = t["predicted_per_second"]
            pp = t["prompt_per_second"]
            tokens = t["predicted_n"]
            results.append({"run": run, "tg": tg, "pp": pp, "tokens": tokens})
            print(f"    Run {run}: TG={tg:.1f} PP={pp:.1f} tokens={tokens}")
        except Exception as e:
            print(f"    Run {run}: ERROR {e}")
    
    # VRAM
    try:
        vram = subprocess.run(["nvidia-smi", "--query-gpu=memory.used", "--format=csv,noheader"],
                            capture_output=True, text=True, timeout=5).stdout.strip()
    except:
        vram = "?"
    
    return results, vram

def stop_server():
    subprocess.run(["pkill", "-9", "-f", "llama-server"], capture_output=True)
    time.sleep(3)

# ============================================================
# Configs to test
# ============================================================
configs = [
    ("baseline", ["--n-cpu-moe", "99", "-ngl", "45"]),
    ("ncmoe35", ["--n-cpu-moe", "35", "-ngl", "45"]),
    ("ngl55", ["--n-cpu-moe", "99", "-ngl", "55"]),
    ("t12", ["--n-cpu-moe", "99", "-ngl", "45", "-t", "12"]),
    ("ngl60", ["--n-cpu-moe", "99", "-ngl", "60"]),
    ("ncmoe35-ngl55", ["--n-cpu-moe", "35", "-ngl", "55"]),
]

print(f"=== Systematic Benchmark {time.strftime('%Y-%m-%d %H:%M')} ===")
print(f"Hardware: RTX 4050 6GB\n")

all_results = []

for name, args in configs:
    print(f"\n{'='*50}")
    print(f"CONFIG: {name}")
    print(f"  Args: {' '.join(args)}")
    
    proc = start_server(name, args)
    if proc is None:
        print(f"  SKIPPED (server failed to start)")
        all_results.append({"config": name, "status": "FAILED"})
        continue
    
    results, vram = benchmark(proc)
    
    if results:
        tgs = [r["tg"] for r in results]
        avg_tg = sum(tgs) / len(tgs)
        min_tg = min(tgs)
        max_tg = max(tgs)
        print(f"  >>> AVG TG={avg_tg:.1f} (min={min_tg:.1f} max={max_tg:.1f}) VRAM={vram}")
        all_results.append({
            "config": name, "status": "OK",
            "avg_tg": avg_tg, "min_tg": min_tg, "max_tg": max_tg,
            "vram": vram, "runs": results
        })
    else:
        all_results.append({"config": name, "status": "NO_DATA"})
    
    stop_server()

# ============================================================
# Summary
# ============================================================
print(f"\n{'='*50}")
print(f"FINAL RESULTS")
print(f"{'='*50}")
print(f"{'Config':<20} {'Avg TG':>8} {'Min TG':>8} {'Max TG':>8} {'VRAM':>10}")
print(f"{'-'*56}")
for r in all_results:
    if r["status"] == "OK":
        print(f"{r['config']:<20} {r['avg_tg']:>7.1f} {r['min_tg']:>7.1f} {r['max_tg']:>7.1f} {r['vram']:>10}")
    else:
        print(f"{r['config']:<20} {'FAILED':>8}")

# Save results
with open("/tmp/benchmark-results.json", "w") as f:
    json.dump(all_results, f, indent=2)
print(f"\nResults saved to /tmp/benchmark-results.json")
