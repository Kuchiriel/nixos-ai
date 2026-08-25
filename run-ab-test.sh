#!/usr/bin/env bash
# run-ab-test.sh — A/B benchmark: baseline vs n-gram spec
# Runs everything sequentially. Server lifecycle managed inline.
set -euo pipefail

LLAMA_DIR=/nix/store/n7n3jfqfxdbb74kzqk2bhjdgs56byirv-llama-cpp-10273
MODEL=/nix/store/in9pq5ak2mj5km4f6r87v295bfm53w6c-Qwen3.6-35B-A3B-UD-Q4_K_M.gguf
PROMPT='O rápido raposa marrom pula sobre o cão preguiçoso. O rápido raposa marrom pula sobre o cão preguiçoso. O rápido raposa marrom pula sobre o cão preguiçoso. O rápido raposa marrom pula sobre o cão preguiçoso. O rápido raposa marrom pula sobre o cão preguiçoso.\n\nResuma o texto acima em uma frase.'

test_server() {
    local label=$1
    local extra_args=${2:-}
    
    echo "═══════════════════════════════════"
    echo "  $label"
    echo "═══════════════════════════════════"
    
    # Start server
    $LLAMA_DIR/bin/llama-server -m "$MODEL" -ngl 45 -ncmoe 99 -sm layer -t 6 \
        -c 4096 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 \
        --host 0.0.0.0 --port 8080 --jinja --parallel 1 \
        $extra_args &
    local SPID=$!
    
    # Wait for ready
    for i in $(seq 1 60); do
        curl -sf http://127.0.0.1:8080/health &>/dev/null && break
        kill -0 $SPID 2>/dev/null || { echo "❌ Server died"; return 1; }
        sleep 1
    done
    curl -sf http://127.0.0.1:8080/health &>/dev/null || { echo "❌ Timeout"; kill $SPID 2>/dev/null; return 1; }
    echo "✅ Server ready"
    
    # Warmup
    curl -sf http://127.0.0.1:8080/completion -H "Content-Type: application/json" \
        -d '{"prompt":"warmup","n_predict":32,"temperature":0,"seed":42,"ignore_eos":true}' &>/dev/null
    sleep 2
    
    # 5 runs
    echo ""
    for i in 1 2 3 4 5; do
        RESP=$(curl -s http://127.0.0.1:8080/completion -H "Content-Type: application/json" \
            -d "{\"prompt\":\"$PROMPT\",\"n_predict\":128,\"cache_prompt\":false,\"temperature\":0,\"seed\":42,\"ignore_eos\":true}")
        TG=$(echo "$RESP" | grep -o '"predicted_per_second":[0-9.]*' | cut -d: -f2)
        PP=$(echo "$RESP" | grep -o '"prompt_per_second":[0-9.]*' | cut -d: -f2)
        GPU=$(nvidia-smi --query-gpu=memory.used,temperature.gpu --format=csv,noheader,nounits 2>/dev/null | head -1)
        printf "  Run %d: PP %6.1f t/s | TG %5.1f t/s | %s\n" "$i" "$PP" "$TG" "$GPU"
        sleep 2
    done
    
    # Kill
    kill $SPID 2>/dev/null; wait $SPID 2>/dev/null
    echo ""
}

# Kill any old server
pkill -9 -f llama-server 2>/dev/null || true
sleep 2

# A: Baseline
test_server "A: BASELINE (no spec)"

sleep 3

# B: N-gram spec
test_server "B: N-GRAM SPEC (ngram-mod, n_max=64)" "--spec-type ngram-mod --spec-draft-n-max 64"

echo "═══════════════════════════════════"
echo "  Compare A vs B above"
echo "═══════════════════════════════════"
