#!/usr/bin/env bash
# opencode-session.sh — roda o TUI do opencode e GUARDA a janela ao fechar.
#
# Uso:
#   ./scripts/opencode-session.sh            # sessão nova no cwd atual
#   ./scripts/opencode-session.sh -s <id>    # reabre uma sessão específica
#   ./scripts/opencode-session.sh --cwd <dir> [args...]
#
# POR QUÊ (03/11, dono): `foot -e opencode -s <id>` mata a janela junto com o
# TUI — a mensagem que o opencode deixa ("pra abrir essa sessão de novo")
# morre com a janela e depois é caça ao tesouro. Aqui, ao sair, a janela
# FICA, mostra o comando exato de reabertura e espera um Enter.
#
# A sessão encerrada também é registrada em
# ~/.local/state/jarvis/last-closed-session.json → `opencode-sessions.py
# resume --last` reabre a última.
#
# Contrato:
#   - exit code do opencode é propagado (130 no Ctrl+C);
#   - sem sessão identificável, mostra o comando genérico e NÃO trava;
#   - o hint vai para stderr e para o scrollback do terminal.
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSIONS_PY="$SCRIPT_DIR/opencode-sessions.py"

SESSION_ID=""
CWD_OVERRIDE=""
ARGS=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    -s) SESSION_ID="${2:?-s exige um id}"; ARGS+=("-s" "$SESSION_ID"); shift 2 ;;
    --cwd) CWD_OVERRIDE="${2:?--cwd exige um caminho}"; shift 2 ;;
    *) ARGS+=("$1"); shift ;;
  esac
done

if [[ -n "$CWD_OVERRIDE" ]]; then
  cd "$CWD_OVERRIDE" || { echo "cwd inválido: $CWD_OVERRIDE" >&2; exit 1; }
fi

START_MS="$(date +%s%3N)"
opencode "${ARGS[@]}"
OPENCODE_STATUS=$?

# Sessão encerrada: a que foi passada (-s) ou a criada agora (procura no banco).
CLOSED_ID="$SESSION_ID"
if [[ -z "$CLOSED_ID" ]]; then
  CLOSED_ID="$(python3 "$SESSIONS_PY" resolve --since-ms "$START_MS" --directory "$PWD" 2>/dev/null || true)"
fi

if [[ -n "$CLOSED_ID" ]]; then
  python3 "$SESSIONS_PY" closed "$CLOSED_ID" --directory "$PWD" >/dev/null 2>&1 || true
  RESUME_CMD="opencode -s $CLOSED_ID"
  RESUME_CMD_LONG="$SCRIPT_DIR/opencode-resume.sh --session $CLOSED_ID"
else
  RESUME_CMD="opencode-resume.sh --list"
  RESUME_CMD_LONG="$SCRIPT_DIR/opencode-resume.sh --list   # liste e escolha uma"
fi

{
  echo ""
  echo "────────────────────────────────────────────────────────────"
  echo " TUI encerrado (exit $OPENCODE_STATUS)"
  if [[ -n "$CLOSED_ID" ]]; then
    echo " sessão: $CLOSED_ID"
    echo " reabrir:  $RESUME_CMD"
  else
    echo " sessão: (não identificada)"
  fi
  echo " atalho:   $RESUME_CMD_LONG"
  echo "────────────────────────────────────────────────────────────"
  printf " [Enter] fecha esta janela  "
} >&2

read -r _ || true
exit "$OPENCODE_STATUS"
