#!/usr/bin/env bash
# fast_tune.sh — Busca binária direcional para tuning do llama.cpp
#
# Uso:
#   ./fast_tune.sh                    # 1 run por teste (~20 min)
#   ./fast_tune.sh --runs 3           # 3 runs (~45 min, mais preciso)
#   ./fast_tune.sh --ctx-size 32768   # Contexto menor (mais rápido)
#
# ⚠️  Pare o Roo Dev antes de rodar!
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON3="${PYTHON3:-python3}"
LOG_DIR="${SCRIPT_DIR}/logs/fast-tune"
RUNS=1
CTX_SIZE=196608

while [[ $# -gt 0 ]]; do
    case "$1" in
        --runs) RUNS="$2"; shift 2 ;;
        --ctx-size) CTX_SIZE="$2"; shift 2 ;;
        --log-dir) LOG_DIR="$2"; shift 2 ;;
        *) echo "Uso: $0 [--runs N] [--ctx-size N]"; exit 1 ;;
    esac
done

mkdir -p "$LOG_DIR"

echo "🚀 Fast Directional Tuning"
echo "  Runs/test: $RUNS"
echo "  Context:   $CTX_SIZE"
echo "  Log dir:   $LOG_DIR"
echo ""
echo "  ⚠️  Pare o Roo Dev (o script reinicia o servidor)"
echo ""

exec "$PYTHON3" "$SCRIPT_DIR/fast_tune.py" \
    --runs "$RUNS" \
    --ctx-size "$CTX_SIZE" \
    --log-dir "$LOG_DIR"
