#!/usr/bin/env bash
# mlock-benchmark.sh — Compare EHS-25 baseline vs EHS-25 + --mlock
# Measures: TG tok/s, ms/token, minor/major page faults, disk I/O, RSS, VRAM
set -euo pipefail

LLAMA_BIN=/home/nixos/projects/llama-wackmall/build/bin/llama-server
MODEL=/nix/store/in9pq5ak2mj5km4f6r87v295bfm53w6c-Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
MMPROJ=/nix/store/fc4lc40lbcp1mi0vqq4d4780d8vf3w5p-mmproj-BF16.gguf
PORT=8080
RUNS=${1:-5}
WARMUP_TOKENS=200
GEN_TOKENS=200

export LD_LIBRARY_PATH="/run/opengl-driver/lib"

# ── helpers ──────────────────────────────────────────────────────────
get_pid_metrics() {
    local pid=$1
    local prefix=$2
    # /proc/<pid>/stat fields: index 10=minflt, 12=majflt (1-indexed after split)
    local stat=$(cat /proc/$pid/stat 2>/dev/null || echo "")
    if [ -n "$stat" ]; then
        local fields=($stat)
        echo "${prefix}_minfaults=${fields[9]}"
        echo "${prefix}_majfaults=${fields[11]}"
    fi
    # /proc/<pid>/status for RSS
    local rss=$(grep VmRSS /proc/$pid/status 2>/dev/null | awk '{print $2}' || echo "0")
    echo "${prefix}_rss_kb=${rss}"
}

get_vram() {
    nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1 || echo "0"
}

wait_server() {
    local max_wait=60
    local i=0
    while [ $i -lt $max_wait ]; do
        if curl -sf http://127.0.0.1:$PORT/health >/dev/null 2>&1; then
            return 0
        fi
        sleep 2
        i=$((i+2))
    done
    echo "TIMEOUT waiting for server"
    return 1
}

run_single_bench() {
    local label=$1
    local extra_args=$2
    local run_num=$3

    # Start server
    setsid $LLAMA_BIN \
        -m "$MODEL" --mmproj "$MMPROJ" \
        --host 0.0.0.0 --port $PORT \
        -c 8192 -t 8 -b 512 -ub 512 -ngl 45 \
        -fa on -ctk q4_0 -ctv q4_0 \
        -ehs 25 --split-mode layer \
        --parallel 1 --jinja \
        $extra_args \
        </dev/null >/tmp/llama-bench-${label}.log 2>&1 &

    local server_pid=$!
    echo "  [${label} run ${run_num}] Server PID: $server_pid"

    # Wait for server to be ready
    if ! wait_server; then
        kill -9 $server_pid 2>/dev/null || true
        echo "  [${label} run ${run_num}] FAILED: server didn't start"
        return 1
    fi

    # Record initial metrics
    local vram_before=$(get_vram)
    get_pid_metrics $server_pid "${label}_r${run_num}_start" > /tmp/metrics-${label}-r${run_num}.txt

    # Record initial disk I/O
    local io_before=$(cat /proc/$server_pid/io 2>/dev/null | grep read_bytes | awk '{print $2}' || echo "0")

    # Warmup: generate some tokens to fill cache
    curl -sf http://127.0.0.1:$PORT/v1/chat/completions \
        -H "Content-Type: application/json" \
        -d "{\"model\":\"qwen\",\"messages\":[{\"role\":\"user\",\"content\":\"Say OK\"}],\"max_tokens\":${WARMUP_TOKENS},\"temperature\":0}" \
        >/dev/null 2>&1

    # Actual benchmark: timed generation
    local start_ms=$(date +%s%N)
    local response=$(curl -sf http://127.0.0.1:$PORT/v1/chat/completions \
        -H "Content-Type: application/json" \
        -d "{\"model\":\"qwen\",\"messages\":[{\"role\":\"user\",\"content\":\"Write a detailed analysis of the properties of prime numbers, covering distribution, theorems, and applications in cryptography.\"}],\"max_tokens\":${GEN_TOKENS},\"temperature\":0}" 2>/dev/null)
    local end_ms=$(date +%s%N)

    local elapsed_ms=$(( (end_ms - start_ms) / 1000000 ))

    # Extract usage from response
    local usage=$(echo "$response" | grep -o '"usage":{[^}]*}' || echo "")
    local completion_tokens=$(echo "$usage" | grep -o '"completion_tokens":[0-9]*' | cut -d: -f2 || echo "$GEN_TOKENS")

    # Record final metrics
    local vram_after=$(get_vram)
    get_pid_metrics $server_pid "${label}_r${run_num}_end" >> /tmp/metrics-${label}-r${run_num}.txt
    local io_after=$(cat /proc/$server_pid/io 2>/dev/null | grep read_bytes | awk '{print $2}' || echo "0")

    # Kill server
    kill $server_pid 2>/dev/null || true
    wait $server_pid 2>/dev/null || true

    # Calculate tok/s
    local tok_per_sec=0
    if [ "$elapsed_ms" -gt 0 ] && [ -n "$completion_tokens" ] && [ "$completion_tokens" -gt 0 ] 2>/dev/null; then
        tok_per_sec=$(echo "scale=2; $completion_tokens * 1000 / $elapsed_ms" | bc 2>/dev/null || echo "0")
    fi

    local ms_per_token=0
    if [ "$completion_tokens" -gt 0 ] 2>/dev/null; then
        ms_per_token=$(echo "scale=2; $elapsed_ms / $completion_tokens" | bc 2>/dev/null || echo "0")
    fi

    local io_delta=0
    if [ -n "$io_before" ] && [ -n "$io_after" ]; then
        io_delta=$((io_after - io_before))
    fi

    echo "${label},run${run_num},${completion_tokens},${elapsed_ms},${ms_per_token},${tok_per_sec},${vram_after},${io_delta}" >> /tmp/bench-results.csv
    cat /tmp/metrics-${label}-r${run_num}.txt >> /tmp/bench-metrics.csv

    echo "  [${label} run ${run_num}] ${completion_tokens} tokens in ${elapsed_ms} ms = ${tok_per_sec} tok/s, ${ms_per_token} ms/tok, VRAM=${vram_after}MB, IO=${io_delta}B"
}

# ── main ─────────────────────────────────────────────────────────────
echo "=== MoE mlock Benchmark ==="
echo "Runs: $RUNS, Warmup: ${WARMUP_TOKENS} tokens, Generate: ${GEN_TOKENS} tokens"
echo ""

# Ensure port is free
sudo systemctl stop llama-cpp-server.service 2>/dev/null || true
sleep 3

# Initialize CSV
echo "label,run,tokens,elapsed_ms,ms_per_token,tok_per_sec,vram_mb,io_bytes" > /tmp/bench-results.csv
echo "metric,value" > /tmp/bench-metrics.csv

echo "=== BASELINE (no mlock) ==="
for i in $(seq 1 $RUNS); do
    run_single_bench "baseline" "" $i
    sleep 2
done

echo ""
echo "=== MLOCK (--mlock) ==="
for i in $(seq 1 $RUNS); do
    run_single_bench "mlock" "--mlock" $i
    sleep 2
done

echo ""
echo "=== RESULTS ==="
cat /tmp/bench-results.csv | column -t -s,

echo ""
echo "=== SUMMARY ==="
# Calculate averages
baseline_tps=$(grep "^baseline" /tmp/bench-results.csv | awk -F, '{sum+=$6; n++} END {if(n>0) printf "%.2f", sum/n; else print "0"}')
baseline_mpt=$(grep "^baseline" /tmp/bench-results.csv | awk -F, '{sum+=$5; n++} END {if(n>0) printf "%.2f", sum/n; else print "0"}')
baseline_io=$(grep "^baseline" /tmp/bench-results.csv | awk -F, '{sum+=$8; n++} END {if(n>0) printf "%.0f", sum/n; else print "0"}')
mlock_tps=$(grep "^mlock" /tmp/bench-results.csv | awk -F, '{sum+=$6; n++} END {if(n>0) printf "%.2f", sum/n; else print "0"}')
mlock_mpt=$(grep "^mlock" /tmp/bench-results.csv | awk -F, '{sum+=$5; n++} END {if(n>0) printf "%.2f", sum/n; else print "0"}')
mlock_io=$(grep "^mlock" /tmp/bench-results.csv | awk -F, '{sum+=$8; n++} END {if(n>0) printf "%.0f", sum/n; else print "0"}')

echo "Baseline:  ${baseline_tps} tok/s, ${baseline_mpt} ms/tok, IO=${baseline_io}B"
echo "Mlock:     ${mlock_tps} tok/s, ${mlock_mpt} ms/tok, IO=${mlock_io}B"

if [ "$(echo "$baseline_mpt > 0" | bc)" -eq 1 ] 2>/dev/null; then
    speedup=$(echo "scale=2; $baseline_mpt / $mlock_mpt" | bc 2>/dev/null || echo "N/A")
    pct=$(echo "scale=1; ($baseline_mpt - $mlock_mpt) * 100 / $baseline_mpt" | bc 2>/dev/null || echo "N/A")
    echo "Speedup:   ${speedup}x (${pct}% faster)"
fi

# Restart normal service
sudo systemctl start llama-cpp-server.service 2>/dev/null || true
echo ""
echo "=== DONE ==="
