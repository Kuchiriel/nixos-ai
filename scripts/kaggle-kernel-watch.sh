#!/usr/bin/env bash
# kaggle-kernel-watch — acompanha um kernel Kaggle até COMPLETE/ERROR e puxa o output.
#
# PURPOSE: jobs de treino no Kaggle são fire-and-forget (o agente não fica
#   esperando): este watcher faz o poll, baixa o output e avisa. O deadline usa
#   lastRunTime do kernel, não o instante em que o watcher começou.
# USAGE: kaggle-kernel-watch.sh --slug <owner/kernel> [--out <dir>] [--interval <s>]
#         [--notify] [--max-min <n>] [--once] [--kaggle-bin <path>]
# EXAMPLE: kaggle-kernel-watch.sh --slug magbeatles/laya-mt5-gold-fakeout-v2-finetune \
#            --out /tmp/opencode/kernel-v2 --interval 300 --notify
# NOTES: usa o CLI do venv /home/nixos/kvenv (se existir) senao nix nixpkgs#kaggle;
#   SEMPRE env -u KAGGLE_API_TOKEN* (os KGAT mortos no ambiente dominam o CLI).
set -uo pipefail

SLUG=""; OUT=""; INTERVAL=300; NOTIFY=0; MAX_MIN=720; ONCE=0; KAGGLE_BIN="${KAGGLE_BIN:-}"
while [[ $# -gt 0 ]]; do
  case "$1" in
    --slug) SLUG="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    --interval) INTERVAL="$2"; shift 2;;
    --max-min) MAX_MIN="$2"; shift 2;;
    --notify) NOTIFY=1; shift;;
    --once) ONCE=1; shift;;
    --kaggle-bin) KAGGLE_BIN="$2"; shift 2;;
    -h|--help) sed -n '2,13p' "$0"; exit 0;;
    *) echo "kaggle-kernel-watch: arg desconhecido: $1" >&2; exit 2;;
  esac
done
[[ -z "$SLUG" ]] && { echo "uso: --slug owner/kernel (obrigatorio)" >&2; exit 2; }
[[ "$SLUG" == */* ]] || { echo "kaggle-kernel-watch: slug deve ser owner/kernel" >&2; exit 2; }
[[ -z "$OUT" ]] && OUT="/tmp/opencode/kaggle-$(echo "$SLUG" | tr '/' '-')"
mkdir -p "$OUT"
LOG="${KAGGLE_WATCH_LOG:-/tmp/kaggle-watch-$(echo "$SLUG" | tr '/' '-').log}"
SELF=$(basename "$0")
OWNER="${SLUG%%/*}"; NAME="${SLUG#*/}"

kaggle_cmd() {
  if [[ -n "$KAGGLE_BIN" && -x "$KAGGLE_BIN" ]]; then
    env -u KAGGLE_API_TOKEN -u KAGGLE_API_TOKEN_O2 "$KAGGLE_BIN" "$@"
  elif [[ -x /home/nixos/kvenv/bin/kaggle ]]; then
    env -u KAGGLE_API_TOKEN -u KAGGLE_API_TOKEN_O2 /home/nixos/kvenv/bin/kaggle "$@"
  else
    env -u KAGGLE_API_TOKEN -u KAGGLE_API_TOKEN_O2 nix shell nixpkgs#kaggle -c kaggle "$@"
  fi
}

log() { echo "$(date '+%H:%M:%S') $*" | tee -a "$LOG"; }

last_run_time() {
  local csv
  csv=$(kaggle_cmd kernels list --user "$OWNER" --search "$NAME" --csv 2>/dev/null || true)
  printf '%s\n' "$csv" | python3 -c '
import csv, io, sys
try:
    text = sys.stdin.read()
    start = text.find("ref,title")
    if start < 0:
        print("")
    else:
        rows = list(csv.DictReader(io.StringIO(text[start:])))
        print(rows[0].get("lastRunTime", "") if rows else "")
except Exception:
    print("")
'
}

log "$SELF on: slug=$SLUG out=$OUT intervalo=${INTERVAL}s limite=${MAX_MIN}min"
watch_start=$(date +%s)
kernel_start=0
start_source="watcher_start"
status=""
while :; do
  raw=$(kaggle_cmd kernels status "$SLUG" 2>/dev/null | tail -1)
  status=$(printf '%s' "$raw" | grep -oE "RUNNING|COMPLETE|ERROR|QUEUED" | head -1)
  [ -z "$status" ] && status="DESCONHECIDO"

  last_run=$(last_run_time)
  parsed_start=""
  if [[ -n "$last_run" ]]; then
    parsed_start=$(date -u -d "$last_run" +%s 2>/dev/null || true)
  fi
  if [[ -n "$parsed_start" ]]; then
    kernel_start="$parsed_start"
    start_source="lastRunTime"
  fi
  now=$(date +%s)
  if (( kernel_start > 0 )); then
    deadline=$(( kernel_start + MAX_MIN * 60 ))
  else
    deadline=$(( watch_start + MAX_MIN * 60 ))
  fi
  elapsed=$(( (now - (kernel_start > 0 ? kernel_start : watch_start)) / 60 ))
  remaining=$(( (deadline - now) / 60 ))
  log "status=$status elapsed_min=$elapsed remaining_min=$remaining start_source=$start_source last_run=${last_run:-unknown}"

  if [[ "$status" == "COMPLETE" || "$status" == "ERROR" ]]; then
    log "baixando output -> $OUT"
    kaggle_cmd kernels output "$SLUG" -p "$OUT" >> "$LOG" 2>&1
    log "status final=$status (output em $OUT)"
    if [[ "$NOTIFY" -eq 1 && -x /home/nixos/projects/team/tg.sh ]]; then
      /home/nixos/projects/team/tg.sh post "[kaggle] $SLUG -> $status (output em $OUT)" >> "$LOG" 2>&1
    fi
    [[ "$status" == "COMPLETE" ]] && exit 0 || exit 1
  fi
  if (( now > deadline )); then
    log "timeout: ${MAX_MIN}min sem completar desde ${start_source} (status=$status elapsed_min=$elapsed)"
    exit 3
  fi
  if [[ "$ONCE" -eq 1 ]]; then
    log "once=true: poll concluido sem alterar o kernel"
    exit 0
  fi
  sleep "$INTERVAL"
done
