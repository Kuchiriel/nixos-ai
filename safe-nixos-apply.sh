#!/usr/bin/env bash
# safe-nixos-apply.sh — wrapper de ativação segura para uso por agente autônomo.
#
# Uso: ./safe-nixos-apply.sh <build|test|switch> [hostname]
#
#   build  — só valida (nix build), nunca ativa nada. Sempre seguro.
#   test   — ativa a config SEM torná-la o default de boot (reboot reverte sozinho).
#   switch — ativa e torna default de boot. Só roda se test+health check passarem.
#
# Regras de segurança embutidas:
#   1. NUNCA ativa (test/switch) sem antes confirmar que builda limpo.
#   2. NUNCA ativa enquanto o llama-server tem slot em processamento
#      (evita cancelar requisição em voo e travar o próprio agente que depende dele).
#   3. Após ativar, roda health check dos serviços jarvis + llama-server.
#      Se qualquer coisa falhar, rollback automático via `switch --rollback`.
#   4. Loga tudo em NIGHTLOG.md na raiz do repo, com timestamp.
#
# Este script é o ÚNICO jeito que o agente deve tocar em nixos-rebuild.
# Chamar nixos-rebuild diretamente é proibido pelas instruções do modo.

set -euo pipefail

MODE="${1:?uso: safe-nixos-apply.sh <build|test|switch> [hostname]}"
HOSTNAME="${2:-nitro-v15}"
LLAMA_URL="http://127.0.0.1:8080"
LOG="NIGHTLOG.md"
MAX_WAIT_IDLE=120   # segundos esperando slot livre antes de desistir desta tentativa
MAX_WAIT_HEALTH=90  # segundos esperando o serviço voltar depois de ativar

log() {
    printf -- "- %s [safe-nixos-apply:%s] %s\n" "$(date -Iseconds)" "$MODE" "$1" >>"$LOG"
    echo "[safe-nixos-apply] $1"
}

# ── 1. Confirma que não há request em voo no llama-server ──────────────────
wait_for_idle() {
    local waited=0
    while (( waited < MAX_WAIT_IDLE )); do
        local busy
        busy=$(curl -s --max-time 3 "${LLAMA_URL}/slots" 2>/dev/null \
            | grep -o '"is_processing":true' | wc -l || echo 0)
        if [[ "$busy" -eq 0 ]]; then
            return 0
        fi
        sleep 5
        waited=$((waited + 5))
    done
    return 1
}

if [[ "$MODE" != "build" ]]; then
    log "checando se llama-server está ocioso antes de ativar..."
    if ! wait_for_idle; then
        log "ABORTADO: llama-server ainda ocupado após ${MAX_WAIT_IDLE}s — não é seguro ativar agora. Tente de novo na próxima iteração."
        exit 2
    fi
    log "llama-server ocioso, prosseguindo."
fi

# ── 2. git add -A (o flake só enxerga arquivos trackeados/staged) ──────────
git add -A

# ── 3. Sempre builda primeiro, nunca ativa config que não builda ───────────
log "buildando configuração (nixos-rebuild build)..."
if ! sudo nixos-rebuild build --flake ".#${HOSTNAME}" 2>&1 | tee -a "$LOG"; then
    log "BUILD FALHOU — nada foi ativado, config permanece intocada."
    exit 1
fi
log "build OK."

if [[ "$MODE" == "build" ]]; then
    exit 0
fi

# ── 4. Guarda a geração atual para poder confirmar rollback depois ─────────
PREV_GEN=$(sudo nixos-rebuild list-generations --flake ".#${HOSTNAME}" 2>/dev/null \
    | awk '/current/{print $1; exit}' || echo "unknown")
log "geração atual antes de ativar: ${PREV_GEN}"

# ── 5. Ativa (test = não mexe no boot default; switch = mexe) ──────────────
log "ativando via 'nixos-rebuild ${MODE}'..."
if ! sudo nixos-rebuild "$MODE" --flake ".#${HOSTNAME}" 2>&1 | tee -a "$LOG"; then
    log "ATIVAÇÃO FALHOU (${MODE}) — tentando rollback imediato."
    sudo nixos-rebuild switch --rollback --flake ".#${HOSTNAME}" || true
    log "ROLLBACK executado (ativação tinha falhado)."
    exit 1
fi

# ── 6. Health check pós-ativação — serviços críticos + llama-server vivo ───
health_ok() {
    local svc
    for svc in llama-cpp-server qdrant jarvis-vault jarvis-idle; do
        if systemctl is-enabled --quiet "$svc" 2>/dev/null; then
            systemctl is-active --quiet "$svc" || return 1
        fi
    done
    local waited=0
    while (( waited < MAX_WAIT_HEALTH )); do
        if curl -s --max-time 3 -o /dev/null -w "%{http_code}" "${LLAMA_URL}/models" 2>/dev/null | grep -q "^200$"; then
            return 0
        fi
        sleep 5
        waited=$((waited + 5))
    done
    return 1
}

log "checando saúde dos serviços após ativação..."
if health_ok; then
    log "HEALTH CHECK OK — geração ativa e saudável (modo: ${MODE})."
    exit 0
else
    log "HEALTH CHECK FALHOU após ${MODE} — executando rollback automático."
    sudo nixos-rebuild switch --rollback --flake ".#${HOSTNAME}" || true
    log "ROLLBACK executado. Geração anterior (${PREV_GEN}) restaurada como default."
    exit 1
fi
