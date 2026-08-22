#!/usr/bin/env bash
# continuous-improvement.sh — Loop de melhoria contínua para nixos-ai
#
# Este script roda automaticamente em loop, verificando:
# 1. nix flake check — valida o flake
# 2. pytest — roda testes do JARVIS
# 3. git status — verifica mudanças
# 4. Log de métricas (tempo de build, sucesso/falha)
#
# Uso:
#   ./continuous-improvement.sh          # roda em loop (default: 5 min entre ciclos)
#   ./continuous-improvement.sh --once   # roda apenas uma vez
#   ./continuous-improvement.sh --interval 300  # intervalo customizado (segundos)
#
# Saída é logada em logs/continuous-improvement.log
# Pressione Ctrl+C para parar

set -euo pipefail

# ── Configurações ────────────────────────────────────────────────
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs"
LOG_FILE="${LOG_DIR}/continuous-improvement.log"
METRICS_FILE="${LOG_DIR}/metrics.csv"
CYCLE_INTERVAL="${CYCLE_INTERVAL:-300}"  # 5 minutos default
RUN_ONCE=false

# ── Parse de argumentos ─────────────────────────────────────────
while [[ $# -gt 0 ]]; do
  case $1 in
    --once)
      RUN_ONCE=true
      shift
      ;;
    --interval)
      CYCLE_INTERVAL="$2"
      shift 2
      ;;
    --help|-h)
      echo "Uso: $0 [--once] [--interval SEGUNDOS]"
      echo ""
      echo "Opções:"
      echo "  --once          Roda apenas uma vez e sai"
      echo "  --interval N    Intervalo entre ciclos (default: ${CYCLE_INTERVAL}s)"
      echo "  --help, -h      Mostra esta ajuda"
      exit 0
      ;;
    *)
      echo "Unknown option: $1"
      exit 1
      ;;
  esac
done

# ── Inicialização ────────────────────────────────────────────────
mkdir -p "${LOG_DIR}"

# Cria CSV de métricas se não existir
if [[ ! -f "${METRICS_FILE}" ]]; then
  echo "timestamp,cycle,flake_check,pytest,build_time_s,test_time_s,status" > "${METRICS_FILE}"
fi

CYCLE=0
START_TIME=$(date +%s)

# ── Funções de log ───────────────────────────────────────────────
log() {
  local msg="[$(date '+%Y-%m-%d %H:%M:%S')] $*"
  echo "$msg" | tee -a "${LOG_FILE}"
}

log_header() {
  log ""
  log "═══════════════════════════════════════════════════════════"
  log "  $*"
  log "═══════════════════════════════════════════════════════════"
}

# ── Checks ───────────────────────────────────────────────────────
check_flake() {
  log "▶ Verificando flake (nix flake check)..."
  local start=$(date +%s)
  
  if nix flake check --no-link 2>&1 | tee -a "${LOG_FILE}"; then
    local elapsed=$(( $(date +%s) - start ))
    log "✓ flake check passou (${elapsed}s)"
    echo "${elapsed}"
    return 0
  else
    local elapsed=$(( $(date +%s) - start ))
    log "✗ flake check falhou (${elapsed}s)"
    echo "${elapsed}"
    return 1
  fi
}

check_pytest() {
  log "▶ Rodando testes pytest..."
  local start=$(date +%s)
  
  cd "${SCRIPT_DIR}"
  if nix develop --command python3 -m pytest modules/ai/jarvis/tests/ -x -q --tb=short 2>&1 | tee -a "${LOG_FILE}"; then
    local elapsed=$(( $(date +%s) - start ))
    log "✓ pytest passou (${elapsed}s)"
    echo "${elapsed}"
    return 0
  else
    local elapsed=$(( $(date +%s) - start ))
    log "✗ pytest falhou (${elapsed}s)"
    echo "${elapsed}"
    return 1
  fi
}

check_git_status() {
  log "▶ Status do git:"
  cd "${SCRIPT_DIR}"
  git status --short 2>&1 | head -20 | while read -r line; do
    log "  $line"
  done
}

# ── Ciclo principal ──────────────────────────────────────────────
run_cycle() {
  CYCLE=$((CYCLE + 1))
  local cycle_start=$(date +%s)
  
  log_header "CICLO #${CYCLE}"
  
  local flake_ok=true
  local pytest_ok=true
  local flake_time=0
  local pytest_time=0
  
  # 1. Flake check
  if ! flake_time=$(check_flake); then
    flake_ok=false
  fi
  
  # 2. Pytest (só se flake passou)
  if $flake_ok; then
    if ! pytest_time=$(check_pytest); then
      pytest_ok=false
    fi
  else
    log "⊘ pytest pulado (flake check falhou)"
    pytest_time=0
  fi
  
  # 3. Git status
  check_git_status
  
  # 4. Registrar métricas
  local cycle_time=$(( $(date +%s) - cycle_start ))
  local status="OK"
  if ! $flake_ok || ! $pytest_ok; then
    status="FAIL"
  fi
  
  echo "$(date -Iseconds),${CYCLE},${flake_ok},${pytest_ok},${flake_time},${pytest_time},${status}" >> "${METRICS_FILE}"
  
  # 5. Resumo do ciclo
  log_header "RESUMO DO CICLO #${CYCLE}"
  log "  flake check:  $([ "$flake_ok" = true ] && echo '✓ PASS' || echo '✗ FAIL') (${flake_time}s)"
  log "  pytest:       $([ "$pytest_ok" = true ] && echo '✓ PASS' || echo '✗ FAIL') (${pytest_time}s)"
  log "  tempo ciclo:  ${cycle_time}s"
  
  local uptime=$(( $(date +%s) - START_TIME ))
  log "  uptime:       ${uptime}s ($(printf '%02d:%02d:%02d' $((uptime/3600)) $((uptime%3600/60)) $((uptime%60))))"
}

# ── Main ─────────────────────────────────────────────────────────
log_header "NIXOS-AI CONTINUOUS IMPROVEMENT"
log "Script: ${BASH_SOURCE[0]}"
log "Diretório: ${SCRIPT_DIR}"
log "Log: ${LOG_FILE}"
log "Métricas: ${METRICS_FILE}"
log "Intervalo: ${CYCLE_INTERVAL}s"
log "Modo: $([ "$RUN_ONCE" = true ] && echo 'uma vez' || echo 'loop contínuo')"

if $RUN_ONCE; then
  run_cycle
  log "Modo --once: saindo após 1 ciclo"
  exit 0
fi

# Loop contínuo
while true; do
  run_cycle
  
  log "⏳ Próximo ciclo em ${CYCLE_INTERVAL}s... (Ctrl+C para parar)"
  sleep "${CYCLE_INTERVAL}"
done
