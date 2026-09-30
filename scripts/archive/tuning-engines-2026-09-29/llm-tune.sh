#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# llm-tune.sh — Tuning unificado do llama.cpp
# ══════════════════════════════════════════════════════════════════════════════
#
# 3 fases progressivas (rápido → preciso):
#   Phase 1 — Scan rápido: testa valores extremos de cada gene (1 run, 32K ctx)
#   Phase 2 — Refina: binary search nos genes promissores (1 run, 64K ctx)
#   Phase 3 — Valida: testa combinação final (3 runs, 192K ctx)
#
# Resume: salva estado a cada fase. Se morrer, roda de novo e continua.
#
# Uso:
#   ./llm-tune.sh                    # Todas as fases (~30 min)
#   ./llm-tune.sh --phase 1          # Só scan rápido (~8 min)
#   ./llm-tune.sh --phase 2          # Só refino (~10 min)
#   ./llm-tune.sh --phase 3          # Só validação (~10 min)
#   ./llm-tune.sh --resume           # Continua de onde parou
#   ./llm-tune.sh --status           # Mostra estado atual
#
# ⚠️  Pare o Roo Dev antes de rodar!
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON3="${PYTHON3:-python3}"
LOG_DIR="${SCRIPT_DIR}/logs/llm-tune"
PHASE="all"
RESUME=false
STATUS_ONLY=false

while [[ $# -gt 0 ]]; do
    case "$1" in
        --phase) PHASE="$2"; shift 2 ;;
        --resume) RESUME=true; shift ;;
        --status) STATUS_ONLY=true; shift ;;
        --log-dir) LOG_DIR="$2"; shift 2 ;;
        *) echo "Uso: $0 [--phase 1|2|3|all] [--resume] [--status]"; exit 1 ;;
    esac
done

mkdir -p "$LOG_DIR"

if $STATUS_ONLY; then
    echo "📊 LLM Tune Status"
    for p in 1 2 3; do
        f="$LOG_DIR/phase${p}.json"
        if [[ -f "$f" ]]; then
            echo "  Phase $p: DONE ($(wc -c < "$f") bytes)"
        else
            echo "  Phase $p: PENDING"
        fi
    done
    if [[ -f "$LOG_DIR/best.json" ]]; then
        echo ""
        echo "  Current best:"
        cat "$LOG_DIR/best.json" | "$PYTHON3" -c "
import json,sys
d=json.load(sys.stdin)
print(f\"    fitness: {d['fitness']:.4f}\")
print(f\"    decode:  {d['decode_tps']:.1f} t/s\")
print(f\"    config:  {d.get('config_summary', 'N/A')}\")
" 2>/dev/null || cat "$LOG_DIR/best.json"
    fi
    exit 0
fi

echo "🔧 LLM Tune — Tuning unificado do llama.cpp"
echo "  Phase:    $PHASE"
echo "  Resume:   $RESUME"
echo "  Log dir:  $LOG_DIR"
echo ""
echo "  ⚠️  Pare o Roo Dev antes de rodar!"
echo ""

exec "$PYTHON3" "$SCRIPT_DIR/llm_tune.py" \
    --phase "$PHASE" \
    $(if $RESUME; then echo "--resume"; fi) \
    --log-dir "$LOG_DIR"
