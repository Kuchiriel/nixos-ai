#!/usr/bin/env bash
# A/B comparison: baseline vs n-gram speculative decoding
set -euo pipefail

LLAMA_DIR=/nix/store/n7n3jfqfxdbb74kzqk2bhjdgs56byirv-llama-cpp-10273
MODEL=/nix/store/in9pq5ak2mj5km4f6r87v295bfm53w6c-Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
SCRIPT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

run_bench() {
    local label="$1"
    echo "=== $label ==="
    for i in 1 2 3 4 5; do
        result=$(curl -s http://127.0.0.1:8080/completion \
            -H "Content-Type: application/json" \
            -d '{"prompt":"Explain quantum computing in detail, covering superposition, entanglement, and quantum gates. This tests decode throughput.","n_predict":128,"temperature":0,"seed":42,"ignore_eos":true}')
        decode=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{d[\"timings\"][\"predicted_per_second\"]:.1f}')")
        pp=$(echo "$result" | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{d[\"timings\"][\"prompt_per_second\"]:.1f}')")
        gpu=$(echo "$result" | python3 -c "
import json,sys,subprocess
d=json.load(sys.stdin)
try:
    s=subprocess.run(['nvidia-smi','--query-gpu=memory.used,temperature.gpu','--format=csv,noheader,nounits'],capture_output=True,text=True,timeout=3)
    p=s.stdout.strip().split(', ')
    print(f'{p[0]}MB {p[1]}C')
except: print('?')
" 2>/dev/null || echo "?")
        echo "  Run $i: TG=${decode} t/s  PP=${pp} t/s  GPU=$gpu"
        sleep 3
    done
    echo ""
}

# --- BASELINE ---
echo "Starting baseline server..."
$LLAMA_DIR/bin/llama-server \
    -m "$MODEL" -ngl 45 -ncmoe 99 -sm layer -t 6 \
    -c 4096 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 \
    --host 0.0.0.0 --port 8080 --jinja --parallel 1 \
    </dev/null >/dev/null 2>&1 &
BASELINE_PID=$!

for i in $(seq 1 40); do
    curl -sf http://127.0.0.1:8080/health &>/dev/null && break
    sleep 1
done
curl -sf http://127.0.0.1:8080/health &>/dev/null || { echo "Baseline failed to start"; kill $BASELINE_PID 2>/dev/null; exit 1; }

run_bench "A: BASELINE (no spec)"
kill $BASELINE_PID 2>/dev/null; wait $BASELINE_PID 2>/dev/null; sleep 3

# --- N-GRAM SPEC ---
echo "Starting n-gram spec server..."
$LLAMA_DIR/bin/llama-server \
    -m "$MODEL" -ngl 45 -ncmoe 99 -sm layer -t 6 \
    -c 4096 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 \
    --host 0.0.0.0 --port 8080 --jinja --parallel 1 \
    --spec-type ngram-mod --spec-draft-n-max 64 \
    </dev/null >/dev/null 2>&1 &
SPEC_PID=$!

for i in $(seq 1 40); do
    curl -sf http://127.0.0.1:8080/health &>/dev/null && break
    sleep 1
done
curl -sf http://127.0.0.1:8080/health &>/dev/null || { echo "Spec server failed"; kill $SPEC_PID 2>/dev/null; exit 1; }

run_bench "B: N-GRAM SPEC (ngram-mod, n_max=64)"
kill $SPEC_PID 2>/dev/null; wait $SPEC_PID 2>/dev/null

echo "Done. Compare A vs B above."
