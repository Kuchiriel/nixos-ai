#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# grid_benchmark.sh — Grid search focado nos genes mais sensíveis
# ══════════════════════════════════════════════════════════════════════════════
# Estratégia baseada nos resultados do GA:
#   1. nCpuMoe é o gene mais sensível (expert routing GPU↔CPU)
#   2. gpuLayers controla VRAM budget
#   3. q8_0 KV = melhor精度, mais VRAM
#
# Fases:
#   Phase 1: nCpuMoe sweep (9 valores) — encontra sweet spot
#   Phase 2: gpuLayers sweep (5 valores) — otimiza VRAM
#   Phase 3: Combinação final — valida os melhores genes juntos
#
# Uso:
#   ./grid_benchmark.sh              # Todas as fases
#   ./grid_benchmark.sh --phase 1    # Só nCpuMoe sweep
#   ./grid_benchmark.sh --phase 2    # Só gpuLayers sweep
#   ./grid_benchmark.sh --phase 3    # Só combinação final
#   ./grid_benchmark.sh --runs 5     # 5 runs por config (mais preciso)
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PYTHON3="${PYTHON3:-python3}"
LOG_DIR="${SCRIPT_DIR}/logs/grid-benchmark"
RUNS=3
PHASE="all"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --runs) RUNS="$2"; shift 2 ;;
        --phase) PHASE="$2"; shift 2 ;;
        *) echo "Uso: $0 [--runs N] [--phase 1|2|3|all]"; exit 1 ;;
    esac
done

mkdir -p "$LOG_DIR"

echo "🔬 Grid Search Benchmark — Focado nos genes mais sensíveis"
echo "  Runs per config: $RUNS"
echo "  Phase:           $PHASE"
echo "  Log dir:         $LOG_DIR"
echo ""
echo "  ⚠️  Pare o Roo Dev (o script reinicia o servidor)"
echo ""

# ─── Python engine para o grid search ───
exec "$PYTHON3" "$SCRIPT_DIR/grid_engine.py" \
    --runs "$RUNS" \
    --phase "$PHASE" \
    --log-dir "$LOG_DIR"
