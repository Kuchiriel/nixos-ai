#!/usr/bin/env bash
# systematic-benchmark.sh — Test multiple configurations to find optimal tok/s
# Each config: warmup 30s, then measure 5 runs of 100 tokens
set -euo pipefail

LLAMA_BIN="/home/nixos/projects/llama-wackmall/build/bin/llama-server"
MODEL="/nix/store/in9pq5ak2mj5km4f6r87v295bfm53w6c-Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
PROMPT="Explain the concept of quantum entanglement in simple terms. Give a detailed technical explanation."
TOKENS=128
PORT=8080
RESULTS_DIR="/tmp/bench-results-$(date +%Y%m%d-%H%M%S)"
mkdir -p "$RESULTS_DIR"

# Ensure no other server is running
pkill -9 -f "llama-server" 2>/dev/null || true
sleep 2

run_bench() {
    local name="$1"
    shift
    local extra_args=("$@")
    
    echo ""
    echo "================================================================"
    echo "CONFIG: $name"
    echo "Args: ${extra_args[*]}"
    echo "================================================================"
    
    # Start server
    "$LLAMA_BIN" \
        -m "$MODEL" \
        --host 0.0.0.0 --port $PORT \
        "${extra_args[@]}" \
        </dev/null >/tmp/llama-${name}.log 2>&1 &
    local SERVER_PID=$!
    
    # Wait for server to be ready
    local ready=0
    for i in $(seq 1 60); do
        if curl -sf http://127.0.0.1:$PORT/health >/dev/null 2>&1; then
            ready=1
            break
        fi
        sleep 1
    done
    
    if [ $ready -eq 0 ]; then
        echo "FAILED: Server did not start in 60s"
        kill $SERVER_PID 2>/dev/null || true
        wait $SERVER_PID 2>/dev/null || true
        return 1
    fi
    
    echo "Server ready. Warming up for 30s..."
    
    # Warmup — send requests continuously for 30s
    for i in $(seq 1 15); do
        curl -sf http://127.0.0.1:$PORT/v1/chat/completions \
            -H "Content-Type: application/json" \
            -d "{\"model\":\"local\",\"messages\":[{\"role\":\"user\",\"content\":\"Say hello\"}],\"max_tokens\":20,\"temperature\":0}" \
            >/dev/null 2>&1 &
        sleep 2
    done
    wait
    
    echo "Measuring 5 runs..."
    
    # Get VRAM usage
    local vram=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader 2>/dev/null || echo "0")
    
    local total_tok=0
    local total_ms=0
    local run_times=""
    
    for run in 1 2 3 4 5; do
        local start_ms=$(date +%s%N)
        
        local response=$(curl -sf http://127.0.0.1:$PORT/v1/chat/completions \
            -H "Content-Type: application/json" \
            -d "{\"model\":\"local\",\"messages\":[{\"role\":\"user\",\"content\":\"${PROMPT}\"}],\"max_tokens\":${TOKENS},\"temperature\":0}" \
            2>/dev/null)
        
        local end_ms=$(date +%s%N)
        local elapsed_ms=$(( (end_ms - start_ms) / 1000000 ))
        
        # Extract tokens from response
        local completion_tokens=$(echo "$response" | python3 -c "
import sys,json
try:
    d=json.load(sys.stdin)
    print(d.get('usage',{}).get('completion_tokens',0))
except:
    print(0)
" 2>/dev/null || echo "0")
        
        local tok_per_sec="0"
        if [ "$elapsed_ms" -gt 0 ] && [ "$completion_tokens" -gt 0 ]; then
            tok_per_sec=$(echo "scale=2; $completion_tokens * 1000 / $elapsed_ms" | bc 2>/dev/null || echo "0")
        fi
        
        echo "  Run $run: ${completion_tokens} tokens in ${elapsed_ms}ms = ${tok_per_sec} tok/s"
        run_times="$run_times $tok_per_sec"
        total_tok=$((total_tok + completion_tokens))
        total_ms=$((total_ms + elapsed_ms))
    done
    
    local avg_tok_per_sec="0"
    if [ "$total_ms" -gt 0 ]; then
        avg_tok_per_sec=$(echo "scale=2; $total_tok * 1000 / $total_ms" | bc 2>/dev/null || echo "0")
    fi
    
    # Get server log timing
    local server_tg=$(grep "predicted_per_second" /tmp/llama-${name}.log 2>/dev/null | tail -1 | grep -oP '[\d.]+(?= tokens per second)' || echo "N/A")
    
    echo ""
    echo "RESULT: $name"
    echo "  Avg tok/s (wall): $avg_tok_per_sec"
    echo "  Server TG: $server_tg tok/s"
    echo "  VRAM: ${vram} MiB"
    echo "  Runs: $run_times"
    echo ""
    
    # Save results
    echo "$name|$avg_tok_per_sec|$server_tg|$vram|$run_times" >> "$RESULTS_DIR/results.csv"
    
    # Kill server
    kill $SERVER_PID 2>/dev/null || true
    wait $SERVER_PID 2>/dev/null || true
    sleep 3
}

# Common flags
COMMON="-t 8 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 --split-mode layer --parallel 1 --jinja --no-warmup"

echo "Systematic Benchmark — $(date)"
echo "Model: Qwen3.6-35B-A3B Q4_K_M"
echo "Hardware: RTX 4050 6GB"
echo ""

# ============================================================
# TEST 1: Baseline (current config, smaller context for fair comparison)
# ============================================================
run_bench "baseline-ctx4k" \
    -c 4096 $COMMON \
    --n-cpu-moe 99 -ngl 45

# ============================================================
# TEST 2: Baseline with more context
# ============================================================
run_bench "baseline-ctx32k" \
    -c 32768 $COMMON \
    --n-cpu-moe 99 -ngl 45

# ============================================================
# TEST 3: More GPU layers (ngl=55)
# ============================================================
run_bench "ngl55-ctx4k" \
    -c 4096 $COMMON \
    --n-cpu-moe 99 -ngl 55

# ============================================================
# TEST 4: Maximum GPU layers (ngl=60)
# ============================================================
run_bench "ngl60-ctx4k" \
    -c 4096 $COMMON \
    --n-cpu-moe 99 -ngl 60

# ============================================================
# TEST 5: EHS-25 (hot experts on GPU)
# ============================================================
run_bench "ehs25-ctx4k" \
    -c 4096 $COMMON \
    -ehs 25 -ngl 45

# ============================================================
# TEST 6: EHS with more slots
# ============================================================
run_bench "ehs40-ctx4k" \
    -c 4096 $COMMON \
    -ehs 40 -ngl 45

# ============================================================
# TEST 7: ncmoe=35 (video's approach)
# ============================================================
run_bench "ncmoe35-ctx4k" \
    -c 4096 $COMMON \
    --n-cpu-moe 35 -ngl 45

# ============================================================
# TEST 8: ncmoe=35 + more GPU layers
# ============================================================
run_bench "ncmoe35-ngl55-ctx4k" \
    -c 4096 $COMMON \
    --n-cpu-moe 35 -ngl 55

# ============================================================
# TEST 9: no-mmap (video's trick)
# ============================================================
run_bench "nommap-ctx4k" \
    -c 4096 $COMMON \
    --n-cpu-moe 99 -ngl 45 --no-mmap

# ============================================================
# TEST 10: no-mmap + ncmoe=35
# ============================================================
run_bench "nommap-ncmoe35-ctx4k" \
    -c 4096 $COMMON \
    --n-cpu-moe 35 -ngl 45 --no-mmap

# ============================================================
# TEST 11: More threads (t=12)
# ============================================================
run_bench "t12-ctx4k" \
    -c 4096 -fa on -ctk q4_0 -ctv q4_0 --split-mode layer --parallel 1 --jinja --no-warmup \
    --n-cpu-moe 99 -ngl 45 -t 12 -b 512 -ub 512

# ============================================================
# TEST 12: Max optimization (best of all)
# ============================================================
run_bench "maxopt-ctx4k" \
    -c 4096 -fa on -ctk q4_0 -ctv q4_0 --split-mode layer --parallel 1 --jinja --no-warmup \
    -ehs 30 -ngl 55 -t 12 -b 512 -ub 512 --no-mmap

echo ""
echo "================================================================"
echo "FINAL RESULTS"
echo "================================================================"
cat "$RESULTS_DIR/results.csv" | column -t -s '|'
echo ""
echo "Results saved to: $RESULTS_DIR/"
