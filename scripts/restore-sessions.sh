#!/usr/bin/env bash
# restore-sessions.sh — relança as sessões opencode capturadas no snapshot, no layout original
#
# Uso:
#   ./scripts/restore-sessions.sh [--dry-run] [--file <snapshot.tsv>]
#   ./scripts/restore-sessions.sh --capture [--dry-run] [--file <snapshot.tsv>]
#
# Exemplo:
#   ./scripts/restore-sessions.sh --dry-run
#   ./scripts/restore-sessions.sh --file docs/auditoria/snapshot-sessoes-2026-11-03.tsv
#   ./scripts/restore-sessions.sh --capture          # grava o layout ATUAL no state
#
# Contrato:
#   - o TSV tem: ws<TAB>slot(left|right)<TAB>session_id<TAB>label<TAB>focus(0|1)
#   - cada sessão vira uma janela `foot -e opencode -s <session_id>` no workspace certo
#   - o layout (dwindle, 2 colunas) sai do ordem de criação: left primeiro
#   - idempotente: sessão já aberta (pgrep -f "opencode -s <id>") é pulada
#   - --dry-run não abre nada (com --capture, imprime o TSV em vez de gravar)
#   - --capture lê hyprctl + /proc (foot → opencode -s <id>) e grava o snapshot
#     ATUAL; sem --file grava em ~/.local/state/jarvis/sessions-snapshot.tsv
#     (o timer session-snapshot roda isso a cada 60s; o exec-once do Hyprland
#     restaura do mesmo arquivo no boot)
#   - restore sem --file prefere o snapshot do state; cai no TSV datado do repo
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(dirname "$SCRIPT_DIR")"
DEFAULT_FILE="$REPO_DIR/docs/auditoria/snapshot-sessoes-2026-11-03.tsv"
STATE_FILE="${XDG_STATE_HOME:-$HOME/.local/state}/jarvis/sessions-snapshot.tsv"
FILE=""
FILE_SET=0
DRY_RUN=0
CAPTURE=0

while [[ $# -gt 0 ]]; do
  case "$1" in
    --dry-run) DRY_RUN=1; shift ;;
    --capture) CAPTURE=1; shift ;;
    --file) FILE="${2:?--file exige um caminho}"; FILE_SET=1; shift 2 ;;
    -h|--help) sed -n '2,20p' "$0"; exit 0 ;;
    *) echo "opção desconhecida: $1" >&2; exit 2 ;;
  esac
done

if [[ $FILE_SET -eq 0 ]]; then
  if [[ $CAPTURE -eq 1 ]]; then
    FILE="$STATE_FILE"
  elif [[ -r "$STATE_FILE" ]]; then
    FILE="$STATE_FILE"
  else
    FILE="$DEFAULT_FILE"
  fi
fi

[[ -r "$FILE" ]] || { [[ $CAPTURE -eq 1 ]] || { echo "snapshot ilegível: $FILE" >&2; exit 1; }; }
command -v hyprctl >/dev/null || { echo "hyprctl não encontrado" >&2; exit 1; }
command -v foot >/dev/null || { echo "foot não encontrado" >&2; exit 1; }

capture() {
  python3 - "$FILE" "$DRY_RUN" <<'PY'
import json, os, subprocess, sys

path, dry = sys.argv[1], sys.argv[2] == "1"

def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)

r = run(["hyprctl", "clients", "-j"])
if r.returncode != 0:
    sys.exit(f"hyprctl falhou (sessão gráfica?): {r.stderr.strip()[:120]}")
try:
    clients = json.loads(r.stdout or "[]")
except ValueError:
    sys.exit("hyprctl devolveu JSON inválido")

def read(path, mode="r"):
    try:
        with open(path, mode) as fh:
            return fh.read()
    except OSError:
        return "" if mode == "r" else b""

def ppid_of(pid):
    for line in read(f"/proc/{pid}/status").splitlines():
        if line.startswith("PPid:"):
            return int(line.split()[1])
    return None

def comm_of(pid):
    return read(f"/proc/{pid}/comm").strip()

pg = run(["pgrep", "-f", r"opencode -s "])
sessions = []
for pid_s in pg.stdout.split():
    try:
        pid = int(pid_s)
    except ValueError:
        continue
    parts = [p for p in read(f"/proc/{pid}/cmdline", "rb").decode("utf-8", "replace").split("\0") if p]
    sid = None
    for i, p in enumerate(parts):
        if p == "-s" and i + 1 < len(parts):
            sid = parts[i + 1]
    if not sid:
        continue
    foot = None
    cur = pid
    for _ in range(6):
        cur = ppid_of(cur)
        if not cur or cur <= 1:
            break
        if comm_of(cur) == "foot":
            foot = cur
            break
    if foot is not None:
        sessions.append((sid, foot))

by_pid = {c.get("pid"): c for c in clients}
rows = []
for sid, foot in sessions:
    c = by_pid.get(foot)
    if not c:
        continue
    title = (c.get("title") or "").strip()
    label = title[5:].strip() if title.startswith("OC | ") else title
    rows.append({
        "ws": c["workspace"]["id"],
        "x": c.get("at", [0, 0])[0],
        "sid": sid,
        "label": label or sid,
        "focus": 1 if c.get("focused") else 0,
    })

# uma linha por foot; left/right pela posição X dentro do workspace
rows.sort(key=lambda r: (r["ws"], r["x"]))
out = ["ws\tslot\tsession_id\tlabel\tfocus"]
count = {}
for r in rows:
    n = count.get(r["ws"], 0)
    count[r["ws"]] = n + 1
    slot = "left" if n == 0 else ("right" if n == 1 else f"slot{n + 1}")
    out.append(f"{r['ws']}\t{slot}\t{r['sid']}\t{r['label']}\t{r['focus']}")
text = "\n".join(out) + "\n"

if dry:
    sys.stdout.write(text)
    sys.exit(0)
os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
tmp = path + ".tmp"
with open(tmp, "w", encoding="utf-8") as fh:
    fh.write(text)
os.replace(tmp, path)
print(f"capturado: {len(rows)} sessão(ões) -> {path}")
PY
}

if [[ $CAPTURE -eq 1 ]]; then
  capture
  exit 0
fi

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
