#!/usr/bin/env bash
# Simple benchmark - one config at a time, no complex bash
set +e

PYTHON="/nix/store/kxdkzc079hlg9ifg4lhjvyi2w7qwpshx-python3-3.13.14/bin/python3"
UPSTREAM="/nix/store/n7n3jfqfxdbb74kzqk2bhjdgs56byirv-llama-cpp-10273/bin/llama-server"
MODEL="/nix/store/in9pq5ak2mj5km4f6r87v295bfm53w6c-Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
PROMPT="Explain quantum entanglement."
PORT=8080
OUTFILE="/tmp/bench-final.txt"

echo "=== Benchmark $(date) ===" > "$OUTFILE"

run_one() {
    local NAME="$1"
    shift
    
    pkill -9 -f llama-server 2>/dev/null
    sleep 3
    
    echo "--- $NAME ---" >> "$OUTFILE"
    echo "Args: $@" >> "$OUTFILE"
    
    "$UPSTREAM" -m "$MODEL" --host 0.0.0.0 --port $PORT "$@" \
        </dev/null >/tmp/llama-log-${NAME}.log 2>&1 &
    
    # Wait for ready
    for i in $(seq 1 60); do
        curl -sf http://127.0.0.1:$PORT/health >/dev/null 2>&1 && break
        sleep 1
    done
    
    VRAM=$(nvidia-smi --query-gpu=memory.used --format=csv,noheader 2>/dev/null)
    echo "VRAM: $VRAM" >> "$OUTFILE"
    
    # Warmup
    for i in $(seq 1 5); do
        curl -sf http://127.0.0.1:$PORT/v1/chat/completions \
            -H "Content-Type: application/json" \
            -d '{"model":"local","messages":[{"role":"user","content":"Hi"}],"max_tokens":20,"temperature":0}' \
            >/dev/null 2>&1
        sleep 1
    done
    
    # Measure 5 runs
    for run in $(seq 1 5); do
        RESP=$(curl -sf http://127.0.0.1:$PORT/v1/chat/completions \
            -H "Content-Type: application/json" \
            -d "{\"model\":\"local\",\"messages\":[{\"role\":\"user\",\"content\":\"$PROMPT\"}],\"max_tokens\":128,\"temperature\":0}")
        
        echo "$RESP" | $PYTHON -c "
import sys,json
d=json.load(sys.stdin)
t=d['timings']
print(f\"  Run $run: TG={t['predicted_per_second']:.1f} PP={t['prompt_per_second']:.1f} tokens={t['predicted_n']}\")
" >> "$OUTFILE" 2>/dev/null
    done
    
    # Server-reported TG
    SERVER_TG=$(grep "predicted_per_second" /tmp/llama-log-${NAME}.log 2>/dev/null | tail -1 | \
        $PYTHON -c "
import sys,re
line=sys.stdin.read()
m=re.search(r'predicted_per_second=([\d.]+)', line)
print(m.group(1) if m else 'N/A')
" 2>/dev/null || echo "N/A")
    echo "Server TG: $SERVER_TG" >> "$OUTFILE"
    echo "" >> "$OUTFILE"
}

# CONFIG 1: Baseline
run_one "baseline" \
    -c 4096 -t 8 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 \
    --split-mode layer --parallel 1 --jinja --no-warmup \
    --n-cpu-moe 99 -ngl 45

# CONFIG 2: ncmoe=35
run_one "ncmoe35" \
    -c 4096 -t 8 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 \
    --split-mode layer --parallel 1 --jinja --no-warmup \
    --n-cpu-moe 35 -ngl 45

# CONFIG 3: ngl=55
run_one "ngl55" \
    -c 4096 -t 8 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 \
    --split-mode layer --parallel 1 --jinja --no-warmup \
    --n-cpu-moe 99 -ngl 55

# CONFIG 4: no-mmap
run_one "nommap" \
    -c 4096 -t 8 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 \
    --split-mode layer --parallel 1 --jinja --no-warmup \
    --n-cpu-moe 99 -ngl 45 --no-mmap

# CONFIG 5: t=12
run_one "t12" \
    -c 4096 -t 12 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 \
    --split-mode layer --parallel 1 --jinja --no-warmup \
    --n-cpu-moe 99 -ngl 45

# CONFIG 6: ngl=60
run_one "ngl60" \
    -c 4096 -t 8 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 \
    --split-mode layer --parallel 1 --jinja --no-warmup \
    --n-cpu-moe 99 -ngl 60

# Kill server
pkill -9 -f llama-server 2>/dev/null

echo "=== DONE ===" >> "$OUTFILE"
cat "$OUTFILE"
