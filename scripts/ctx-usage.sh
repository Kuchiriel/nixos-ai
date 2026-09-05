#!/usr/bin/env bash
# ctx-usage.sh — Agrega uso real do LLM local a partir do journal.
# Uso: ./scripts/ctx-usage.sh [--since "7 days ago"]
# Métricas: reqs, média/max de tokens gerados, TG médio, erros.
# Guia decisões de ctx/parallel com dados em vez de achismo.
set -uo pipefail

SINCE="${2:-7 days ago}"
# Escopo: invocação atual do serviço (evita misturar eras Qwen/Bonsai).
INVOCATION=$(systemctl show -p InvocationID --value llama-cpp-server 2>/dev/null || true)
if [ -n "$INVOCATION" ]; then
  LOG=$(journalctl -u llama-cpp-server --since "$SINCE" _SYSTEMD_INVOCATION_ID="$INVOCATION" --no-pager 2>/dev/null)
else
  LOG=$(journalctl -u llama-cpp-server --since "$SINCE" --no-pager 2>/dev/null)
fi

REQS=$(echo "$LOG" | grep -c "launch_slot_" || true)
NGEN=$(echo "$LOG" | grep -oE "n_gen =[ ]+[0-9]+" | grep -oE "[0-9]+" | awk '{s+=$1; c++; if($1>m)m=$1} END {printf "n=%d media=%.0f max=%d", c+0, (c?s/c:0), m+0}')
TG=$(echo "$LOG" | grep -oE "tg =[ ]+[0-9.]+" | grep -oE "[0-9.]+" | awk '{s+=$1; c++} END {printf "media=%.1f", (c?s/c:0)}')
ERRS=$(echo "$LOG" | grep -ciE "error|fail|oom|cuda.*lost" || true)

echo "== Uso LLM desde: $SINCE =="
echo "requests (slots): $REQS"
echo "tokens gerados:   $NGEN"
echo "TG:               $TG t/s"
echo "linhas erro/fail: $ERRS"
echo ""
echo "Regra: ctx 48K só se max gerado+prompt frequente >25K. Paralelo 2 só com uso concorrente real."
