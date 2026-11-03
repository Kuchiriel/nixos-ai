#!/usr/bin/env bash
# restore-sessions.sh — relança as sessões opencode capturadas no snapshot, no layout original
#
# Uso:
#   ./scripts/restore-sessions.sh [--dry-run] [--file <snapshot.tsv>]
#
# Exemplo:
#   ./scripts/restore-sessions.sh --dry-run
#   ./scripts/restore-sessions.sh --file docs/auditoria/snapshot-sessoes-2026-11-03.tsv
#
# Contrato:
#   - o TSV tem: ws<TAB>slot(left|right)<TAB>session_id<TAB>label<TAB>focus(0|1)
#   - cada sessão vira uma janela `foot -e opencode -s <session_id>` no workspace certo
#   - o layout (dwindle, 2 colunas) sai do ordem de criação: left primeiro
#   - idempotente: sessão já aberta (pgrep -f "opencode -s <id>") é pulada
#   - --dry-run não abre nada
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
DEFAULT_FILE="$REPO_DIR/docs/auditoria/snapshot-sessoes-2026-11-03.tsv"
FILE="$DEFAULT_FILE"
DRY_RUN=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --file) FILE="${2:?--file exige um caminho}"; shift 2 ;;
    -h|--help) sed -n '2,16p' "$0"; exit 0 ;;
    *) echo "opção desconhecida: $1" >&2; exit 2 ;;
  esac
done

[[ -r "$FILE" ]] || { echo "snapshot ilegível: $FILE" >&2; exit 1; }
command -v hyprctl >/dev/null || { echo "hyprctl não encontrado" >&2; exit 1; }
command -v foot >/dev/null || { echo "foot não encontrado" >&2; exit 1; }

session_running() {
  pgrep -f -- "opencode -s $1" >/dev/null 2>&1
}

focus_session() {
  local sid="$1" pid addr
  pid="$(pgrep -f -- "opencode -s $sid" | head -n1 || true)"
  [[ -n "$pid" ]] || return 0
  addr="$(hyprctl clients -j 2>/dev/null | python3 -c '
import json,sys
pid=sys.argv[1]
try: clients=json.load(sys.stdin)
except Exception: clients=[]
for c in clients:
    if str(c.get("pid"))==pid:
        print(c.get("address","")); break
' "$pid")"
  [[ -n "$addr" ]] && hyprctl dispatch focuswindow "address:$addr" >/dev/null 2>&1 || true
}

launch() {
  local ws="$1" sid="$2" label="$3"
  if session_running "$sid"; then
    echo "pula (já aberta): $sid — $label"
    return 0
  fi
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "abriria: ws$ws  opencode -s $sid  — $label"
    return 0
  fi
  hyprctl dispatch workspace "$ws" >/dev/null 2>&1 || true
  foot -e opencode -s "$sid" >/dev/null 2>&1 &
  disown || true
  sleep 2
  echo "abriu: ws$ws  $sid — $label"
}

focus_ws=""
focus_sid=""

rows=()
while IFS=$'\t' read -r ws slot sid label focus; do
  [[ -z "${ws:-}" || "$ws" == \#* ]] && continue
  [[ "$ws" == "ws" || "$slot" == "slot" ]] && continue
  case "$slot" in
    left) rank=0 ;;
    right) rank=1 ;;
    *) rank=2 ;;
  esac
  rows+=("$ws"$'\t'"$rank"$'\t'"$sid"$'\t'"$label"$'\t'"${focus:-0}")
done < "$FILE"

# ordem: workspace ascendente, depois left antes de right (dwindle posiciona por criação)
while IFS=$'\t' read -r ws _rank sid label focus; do
  [[ -z "${ws:-}" ]] && continue
  launch "$ws" "$sid" "$label"
  if [[ "${focus:-0}" == "1" ]]; then
    focus_ws="$ws"
    focus_sid="$sid"
  fi
done < <(printf '%s\n' "${rows[@]}" | sort -t$'\t' -k1,1n -k2,2n)

if [[ -n "$focus_sid" ]]; then
  if [[ $DRY_RUN -eq 1 ]]; then
    echo "focaria: ws$focus_ws  $focus_sid"
  else
    hyprctl dispatch workspace "$focus_ws" >/dev/null 2>&1 || true
    focus_session "$focus_sid"
    echo "foco: ws$focus_ws  $focus_sid"
  fi
fi
