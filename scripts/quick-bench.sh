#!/usr/bin/env bash
# quick-bench.sh — Fast A/B benchmark for different llama.cpp configs
# Each config: warmup 5 reqs, then 5 measured runs
set -uo pipefail

PYTHON="/nix/store/kxdkzc079hlg9ifg4lhjvyi2w7qwpshx-python3-3.13.14/bin/python3"
UPSTREAM="/nix/store/n7n3jfqfxdbb74kzqk2bhjdgs56byirv-llama-cpp-10273/bin/llama-server"
MODEL="/nix/store/in9pq5ak2mj5km4f6r87v295bfm53w6c-Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
PROMPT="Explain quantum entanglement in simple terms. Give a detailed technical explanation."
PORT=8080
RESULTS_FILE="/tmp/bench-results.txt"
echo "=== Systematic Benchmark $(date) ===" > "$RESULTS_FILE"
echo "" >> "$RESULTS_FILE"

start_server() {
    local name="$1"
    shift
    local args=("$@")
    
    pkill -9 -f llama-server 2>/dev/null || true
    sleep 3
    
    echo "Starting: $name"
    echo "  Args: ${args[*]}"
    
    "$UPSTREAM" -m "$MODEL" \
        --host 0.0.0.0 --port $PORT \
        "${args[@]}" \
        </dev/null >/tmp/llama-${name}.log 2>&1 &
    
    # Wait for ready
    for i in $(seq 1 60); do
        curl -sf http://127.0.0.1:$PORT/health >/dev/null 2>&1 && break
        sleep 1
    done
    
    # Check if GPU is being used
    local vram=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader 2>/dev/null || echo "?")
    echo "  VRAM: $vram"
    
    # Warmup: 5 fast requests
    for i in $(seq 1 5); do
        curl -sf http://127.0.0.1:$PORT/v1/chat/completions \
            -H "Content-Type: application/json" \
            -d '{"model":"local","messages":[{"role":"user","content":"Hi"}],"max_tokens":20,"temperature":0}' \
            >/dev/null 2>&1
        sleep 0.5
    done
    
    # Measure: 5 runs
    local total_tg=0
    local count=0
    local run_data=""
    
    for run in $(seq 1 5); do
        local RESP=$(curl -sf http://127.0.0.1:$PORT/v1/chat/completions \
            -H "Content-Type: application/json" \
            -d "{\"model\":\"local\",\"messages\":[{\"role\":\"user\",\"content\":\"$PROMPT\"}],\"max_tokens\":128,\"temperature\":0}")
        
        local TG=$(echo "$RESP" | $PYTHON -c "
import sys,json
try:
    d=json.load(sys.stdin)
    t=d.get('timings',{})
    print(f\"{t.get('predicted_per_second',0):.2f}\")
except: print('0')
" 2>/dev/null)
        
        local PP=$(echo "$RESP" | $PYTHON -c "
import sys,json
try:
    d=json.load(sys.stdin)
    t=d.get('timings',{})
    print(f\"{t.get('prompt_per_second',0):.2f}\")
except: print('0')
" 2>/dev/null)
        
        echo "  Run $run: TG=${TG} PP=${PP}"
        run_data="$run_data $TG"
        
        if [ "$(echo "$TG > 0" | $PYTHON 2>/dev/null)" = "True" ] 2>/dev/null; then
            total_tg=$(echo "$total_tg + $TG" | $PYTHON 2>/dev/null)
            count=$((count + 1))
        fi
    done
    
    local avg_tg="0"
    if [ "$count" -gt 0 ]; then
        avg_tg=$(echo "scale=2; $total_tg / $count" | $PYTHON 2>/dev/null)
    fi
    
    local server_tg=$(grep "predicted_per_second" /tmp/llama-${name}.log 2>/dev/null | tail -1 | $PYTHON -c "
import sys,re
line=sys.stdin.read()
m=re.search(r'predicted_per_second=([\d.]+)', line)
print(f'{float(m.group(1)):.2f}' if m else 'N/A')
" 2>/dev/null || echo "N/A")
    
    local vram=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader 2>/dev/null || echo "?")
    
    echo "  >>> RESULT: avg_TG=${avg_tg} server_TG=${server_tg} VRAM=${vram}"
    echo "$name | avg_TG=$avg_tg | server_TG=$server_tg | VRAM=$vram | runs:$run_data" >> "$RESULTS_FILE"
    echo ""
}

# ============================================================
echo "CONFIG 1: Baseline (ncmoe=99, ngl=45, ctx=4K, t=8)"
start_server "baseline-4k" \
    -c 4096 -t 8 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 \
    --split-mode layer --parallel 1 --jinja --no-warmup \
    --n-cpu-moe 99 -ngl 45

# ============================================================
echo "CONFIG 2: ncmoe=35 (video's config, more experts on GPU)"
start_server "ncmoe35-4k" \
    -c 4096 -t 8 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 \
    --split-mode layer --parallel 1 --jinja --no-warmup \
    --n-cpu-moe 35 -ngl 45

# ============================================================
echo "CONFIG 3: ngl=55 (more layers on GPU)"
start_server "ngl55-4k" \
    -c 4096 -t 8 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 \
    --split-mode layer --parallel 1 --jinja --no-warmup \
    --n-cpu-moe 99 -ngl 55

# ============================================================
echo "CONFIG 4: ngl=55 + ncmoe=55"
start_server "ngl55-ncmoe55-4k" \
    -c 4096 -t 8 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 \
    --split-mode layer --parallel 1 --jinja --no-warmup \
    --n-cpu-moe 55 -ngl 55

# ============================================================
echo "CONFIG 5: no-mmap + baseline"
start_server "nommap-4k" \
    -c 4096 -t 8 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 \
    --split-mode layer --parallel 1 --jinja --no-warmup \
    --n-cpu-moe 99 -ngl 45 --no-mmap

# ============================================================
echo "CONFIG 6: t=12 (more threads)"
start_server "t12-4k" \
    -c 4096 -t 12 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 \
    --split-mode layer --parallel 1 --jinja --no-warmup \
    --n-cpu-moe 99 -ngl 45

# ============================================================
echo "CONFIG 7: ngl=60 (maximum GPU layers)"
start_server "ngl60-4k" \
    -c 4096 -t 8 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 \
    --split-mode layer --parallel 1 --jinja --no-warmup \
    --n-cpu-moe 99 -ngl 60

# ============================================================
echo "CONFIG 8: ctx=32K (test if context size matters)"
start_server "ctx32k" \
    -c 32768 -t 8 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 \
    --split-mode layer --parallel 1 --jinja --no-warmup \
    --n-cpu-moe 99 -ngl 45

# ============================================================
echo ""
echo "========================================"
echo "FINAL RESULTS"
echo "========================================"
cat "$RESULTS_FILE"

# Kill server
pkill -9 -f llama-server 2>/dev/null || true
