#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════════════════════
# ga-benchmark.sh — Algoritmo Genético para Tuning do llama.cpp
# ══════════════════════════════════════════════════════════════════════════════
# Otimiza flags do llama-server via seleção natural:
#   1. População inicial com mutações aleatórias
#   2. Benchmarka cada indivíduo
#   3. Fitness ponderado (decode t/s dominante)
#   4. Seleção → crossover → mutação → nova geração
#   5. Repete até convergência
#
# Uso:
#   ./ga-benchmark.sh                    # 5 gerações, pop 6
#   ./ga-benchmark.sh --gens 10          # 10 gerações
#   ./ga-benchmark.sh --pop 8            # 8 indivíduos/geração
#   ./ga-benchmark.sh --runs 3           # 3 runs/indivíduo
#   ./ga-benchmark.sh --baseline-only    # Só baseline
#   ./ga-benchmark.sh --resume GEN       # Resume da geração GEN
#   ./ga-benchmark.sh --dry-run          # Mostra plano sem executar
# ══════════════════════════════════════════════════════════════════════════════
set -euo pipefail
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs/ga-benchmark"
LOCK_FILE="/tmp/ga-benchmark.lock"
SERVER_URL="http://127.0.0.1:8080"
PYTHON3="${PYTHON3:-python3}"

# ─── Parse args ───
GENERATIONS=5
POPULATION=6
RUNS=3
BASELINE_ONLY=false
RESUME_GEN=0
DRY_RUN=false
MUTATION_RATE=0.3
CROSSOVER_RATE=0.7
ELITISM=2

FAST=false
CTX_SIZE=196608
PORT=8080
while [[ $# -gt 0 ]]; do
    case "$1" in
        --gens) GENERATIONS="$2"; shift 2 ;;
        --pop) POPULATION="$2"; shift 2 ;;
        --runs) RUNS="$2"; shift 2 ;;
        --baseline-only) BASELINE_ONLY=true; shift ;;
        --resume) RESUME_GEN="$2"; shift 2 ;;
        --dry-run) DRY_RUN=true; shift ;;
        --mutation-rate) MUTATION_RATE="$2"; shift 2 ;;
        --crossover-rate) CROSSOVER_RATE="$2"; shift 2 ;;
        --elitism) ELITISM="$2"; shift 2 ;;
        --fast) FAST=true; shift ;;
        --ctx-size) CTX_SIZE="$2"; shift 2 ;;
        --port) PORT="$2"; shift 2 ;;
        *) echo "Uso: $0 [--gens N] [--pop N] [--runs N] [--fast] [--dry-run]"; exit 1 ;;
    esac
done
# Fast mode: override runs and context
if $FAST; then
    RUNS=1
    CTX_SIZE=32768
fi

mkdir -p "$LOG_DIR"

# ─── Lock ───
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "ERRO: Outro ga-benchmark ja esta rodando" >&2; exit 1
fi

# ─── Header ───
echo "🧬 Genetic Algorithm Benchmark — llama.cpp Tuning"
echo "  Generations:  $GENERATIONS"
echo "  Population:   $POPULATION"
echo "  Runs/indiv:   $RUNS"
echo "  Mutation:     $MUTATION_RATE"
echo "  Crossover:    $CROSSOVER_RATE"
echo "  Elitism:      $ELITISM"
echo "  Server:       $SERVER_URL"
echo "  Log dir:      $LOG_DIR"
echo ""
echo "  ⚠️  Pare o Roo Dev antes de rodar (o GA reinicia o servidor)"

# ─── Dry run: show gene space ───
if $DRY_RUN; then
    "$PYTHON3" "$SCRIPT_DIR/ga_engine.py" --dry-run --log-dir "$LOG_DIR"
    exit 0
fi

# ─── Check server ───
if ! curl -sf "${SERVER_URL}/health" > /dev/null 2>&1; then
    echo "ERRO: llama-server nao respondendo em ${SERVER_URL}" >&2
    echo "   (inicie o servidor antes de rodar o GA)" >&2
    exit 1
fi
echo "   srv: OK (${SERVER_URL})"

# ─── Run GA engine ───
"$PYTHON3" "$SCRIPT_DIR/ga_engine.py" \
    --gens "$GENERATIONS" \
    --pop "$POPULATION" \
    --runs "$RUNS" \
    --mutation-rate "$MUTATION_RATE" \
    --crossover-rate "$CROSSOVER_RATE" \
    --elitism "$ELITISM" \
    --resume "$RESUME_GEN" \
    --port "$PORT" \
    --ctx-size "$CTX_SIZE" \
    --log-dir "$LOG_DIR" \
    $(if $BASELINE_ONLY; then echo "--baseline-only"; fi) \
    $(if $FAST; then echo "--fast"; fi)
