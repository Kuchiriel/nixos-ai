#!/usr/bin/env bash
# opencode-resume.sh — reabre uma sessão do opencode que foi fechada
#
# Uso:
#   ./scripts/opencode-resume.sh --list                 # lista as recentes
#   ./scripts/opencode-resume.sh --last                 # reabre a última fechada
#   ./scripts/opencode-resume.sh --session <id>         # reabre uma específica
#   ./scripts/opencode-resume.sh --print-only --last    # só imprime o comando
#
# POR QUÊ (03/11, dono): fechar o TUI com Ctrl+C fechava a janela inteira e a
# mensagem de retomada morria com ela. Agora o TUI roda sob
# `opencode-session.sh` (a janela sobrevive e mostra o comando) e este script
# é o caminho inverso: reabrir pelo id, sem caçar no histórico.
#
# Contrato:
#   - `--last` pega a última sessão FECHADA (o registro vem do wrapper que
#     roda o TUI; se não houver, usa a mais recente do banco que não esteja
#     aberta);
#   - reabre em NOVA janela do foot, no diretório original da sessão, sob o
#     mesmo wrapper (a janela sobrevive a um novo Ctrl+C);
#   - sessão já aberta -> foca a janela existente em vez de duplicar;
#   - `--print-only` não abre nada (só imprime o comando).
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSIONS_PY="$SCRIPT_DIR/opencode-sessions.py"
WRAPPER="$SCRIPT_DIR/opencode-session.sh"

MODE="list"
SESSION_ID=""
PRINT_ONLY=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --list) MODE="list"; shift ;;
    --last) MODE="last"; shift ;;
    --session) SESSION_ID="${2:?--session exige um id}"; MODE="session"; shift 2 ;;
    --print-only) PRINT_ONLY=1; shift ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "opção desconhecida: $1" >&2; exit 2 ;;
  esac
done

if [[ "$MODE" == "list" ]]; then
  exec python3 "$SESSIONS_PY" list
fi

if [[ "$MODE" == "session" ]]; then
  :
elif [[ -n "$SESSION_ID" ]]; then
  MODE="session"
else
  MODE="last"
fi

if [[ "$MODE" == "last" ]]; then
  SESSION_ID="$(python3 "$SESSIONS_PY" last 2>/dev/null || true)"
  if [[ -z "$SESSION_ID" ]]; then
    # sem registro do wrapper: a mais recente do banco que não esteja aberta
    SESSION_ID="$(python3 "$SESSIONS_PY" list --closed --limit 1 2>/dev/null \
      | awk 'NR==2 {print $2}')"
  fi
fi

if [[ -z "$SESSION_ID" ]]; then
  echo "nenhuma sessão fechada para reabrir" >&2
  exit 1
fi

# já aberta? -> foca a janela em vez de abrir outra
if pgrep -f -- "opencode -s $SESSION_ID" >/dev/null 2>&1; then
  ADDR="$(hyprctl clients -j 2>/dev/null | python3 -c '
import json,sys
want=sys.argv[1]
try: clients=json.load(sys.stdin)
except Exception: clients=[]
for c in clients:
    pid=str(c.get("pid"))
    try: cmd=open(f"/proc/{pid}/cmdline","rb").read().decode("utf-8","replace")
    except OSError: continue
    if want in cmd:
        print(c.get("address","")); break
' "$SESSION_ID")"
  if [[ -n "$ADDR" ]]; then
    hyprctl dispatch focuswindow "address:$ADDR" >/dev/null 2>&1 || true
    echo "já está aberta — focada: $SESSION_ID"
    exit 0
  fi
fi

DIRECTORY="$(python3 "$SESSIONS_PY" directory --session "$SESSION_ID" 2>/dev/null || true)"
CMD="opencode -s $SESSION_ID"
if [[ -n "$DIRECTORY" ]]; then
  CMD="cd '$DIRECTORY' && $CMD"
fi

if [[ "$PRINT_ONLY" -eq 1 ]]; then
  echo "$CMD"
  exit 0
fi

echo "reabrindo: $SESSION_ID"
if [[ -n "$DIRECTORY" ]]; then
  foot --app-id opencode -e bash -c "'$WRAPPER' --cwd '$DIRECTORY' -s '$SESSION_ID'" \
    >/dev/null 2>&1 &
else
  foot --app-id opencode -e bash -c "'$WRAPPER' -s '$SESSION_ID'" >/dev/null 2>&1 &
fi
disown || true
