#!/usr/bin/env bash
# benchmark.sh — Benchmark E2E com gerenciamento de servidor
# Zero dependência de python. Usa grep/awk pra extrair timings.
#
# ./benchmark.sh --label baseline --repeat 5 --warmup
# ./benchmark.sh --label "ngram" --repeat 5 --warmup --spec-args "--spec-type ngram-mod --spec-draft-n-max 64"

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs/benchmark"

# ─── Defaults ───
LLAMA_DIR="/nix/store/n7n3jfqfxdbb74kzqk2bhjdgs56byirv-llama-cpp-10273"
MODEL="/nix/store/in9pq5ak2mj5km4f6r87v295bfm53w6c-Qwen3.6-35B-A3B-UD-Q4_K_M.gguf"
SERVER_URL="http://127.0.0.1:8080"
REPEAT=5
WARMUP=false
LABEL="benchmark"
PORT=8080
SPEC_ARGS=""

while [[ $# -gt 0 ]]; do
    case "$1" in
        --repeat)    REPEAT="$2"; shift 2 ;;
        --warmup)    WARMUP=true; shift ;;
        --label)     LABEL="$2"; shift 2 ;;
        --model)     MODEL="$2"; shift 2 ;;
        --port)      PORT="$2"; SERVER_URL="http://127.0.0.1:${PORT}"; shift 2 ;;
        --spec-args) SPEC_ARGS="$2"; shift 2 ;;
        -h|--help)   echo "Usage: $0 [--repeat N] [--warmup] [--label NAME] [--spec-args ARGS]"; exit 0 ;;
        *) echo "Unknown: $1"; exit 1 ;;
    esac
done

mkdir -p "$LOG_DIR"

# ─── Kill old server ───
pkill -f "llama-server.*--port $PORT" 2>/dev/null || true
sleep 1

# ─── Start server ───
echo "🚀 ${LABEL}: starting server..." >&2
"${LLAMA_DIR}/bin/llama-server" \
    -m "$MODEL" -ngl 45 -ncmoe 99 -sm layer -t 6 \
    -c 4096 -b 512 -ub 512 -fa on -ctk q4_0 -ctv q4_0 \
    --host 0.0.0.0 --port "$PORT" --jinja --parallel 1 \
    $SPEC_ARGS \
    </dev/null >/dev/null 2>&1 &
SERVER_PID=$!
trap "kill $SERVER_PID 2>/dev/null; wait $SERVER_PID 2>/dev/null" EXIT

echo "⏳ Waiting for server..." >&2
for i in $(seq 1 60); do
    curl -sf "${SERVER_URL}/health" &>/dev/null && break
    kill -0 $SERVER_PID 2>/dev/null || { echo "❌ Server died" >&2; exit 1; }
    sleep 1
done
curl -sf "${SERVER_URL}/health" &>/dev/null || { echo "❌ Timeout" >&2; exit 1; }
echo "✅ Server ready" >&2

# ─── Warmup ───
if $WARMUP; then
    echo "🔥 Warmup..." >&2
    curl -sf "${SERVER_URL}/completion" -H "Content-Type: application/json" \
        -d '{"prompt":"warmup","n_predict":32,"temperature":0,"seed":42,"ignore_eos":true}' &>/dev/null
    sleep 2
fi

# ─── Benchmark ───
echo "📊 ${LABEL}: ${REPEAT} runs" >&2
echo "" >&2

TG_TOTAL=0; TG_MIN=999; TG_MAX=0

for i in $(seq 1 "$REPEAT"); do
    # Get GPU state before run
    GPU_INFO=$(nvidia-smi --query-gpu=memory.used,temperature.gpu --format=csv,noheader,nounits 2>/dev/null | head -1 || echo "?,?,?")

    T0=$(date +%s%N)

    RESP=$(curl -s "${SERVER_URL}/completion" -H "Content-Type: application/json" \
        -d '{"prompt":"O rápido raposa marrom pula sobre o cão preguiçoso. O rápido raposa marrom pula sobre o cão preguiçoso. O rápido raposa marrom pula sobre o cão preguiçoso. O rápido raposa marrom pula sobre o cão preguiçoso. O rápido raposa marrom pula sobre o cão preguiçoso. O rápido raposa marrom pula sobre o cão preguiçoso. O rápido raposa marrom pula sobre o cão preguiçoso. O rápido raposa marrom pula sobre o cão preguiçoso. O rápido raposa marrom pula sobre o cão preguiçoso. O rápido raposa marrom pula sobre o cão preguiçoso.\n\nResuma o texto acima em uma frase.","n_predict":128,"cache_prompt":false,"temperature":0,"seed":42,"ignore_eos":true}')

    T1=$(date +%s%N)
    WALL_MS=$(( (T1 - T0) / 1000000 ))

    # Extract with grep/awk (no python)
    PP=$(echo "$RESP" | grep -o '"prompt_per_second":[0-9.]*' | head -1 | cut -d: -f2 || echo "0")
    TG=$(echo "$RESP" | grep -o '"predicted_per_second":[0-9.]*' | head -1 | cut -d: -f2 || echo "0")
    PN=$(echo "$RESP" | grep -o '"prompt_n":[0-9]*' | head -1 | cut -d: -f2 || echo "0")

    # Calculate stats
    TG_TOTAL=$(echo "$TG_TOTAL + $TG" | bc -l 2>/dev/null || echo "$TG_TOTAL")
    if (( $(echo "$TG < $TG_MIN" | bc -l 2>/dev/null || echo 0) )); then TG_MIN=$TG; fi
    if (( $(echo "$TG > $TG_MAX" | bc -l 2>/dev/null || echo 0) )); then TG_MAX=$TG; fi

    printf "  Run %2d/%d: PP %6.1f t/s | TG %5.1f t/s | %s | %sms wall\n" \
        "$i" "$REPEAT" "$PP" "$TG" "$GPU_INFO" "$WALL_MS" >&2

    if [[ $i -lt $REPEAT ]]; then sleep 2; fi
done

# ─── Summary ───
echo "" >&2
TG_AVG=$(echo "scale=1; $TG_TOTAL / $REPEAT" | bc -l 2>/dev/null || echo "?")
echo "═══ ${LABEL} (${REPEAT} runs) ═══" >&2
echo "  TG: avg=${TG_AVG}  min=${TG_MIN}  max=${TG_MAX} t/s" >&2
echo "" >&2
echo "✅ Done" >&2
