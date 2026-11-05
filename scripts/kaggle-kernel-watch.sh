#!/usr/bin/env bash
# kaggle-kernel-watch — acompanha um kernel Kaggle até COMPLETE/ERROR e puxa o output.
#
# PURPOSE: jobs de treino no Kaggle são fire-and-forget (o agente não fica
#   esperando): este watcher faz o poll, baixa o output e avisa.
# USAGE: kaggle-kernel-watch.sh --slug <owner/kernel> [--out <dir>] [--interval <s>]
#         [--notify] [--max-min <n>]
# EXAMPLE: kaggle-kernel-watch.sh --slug magbeatles/laya-mt5-gold-fakeout-v2-finetune \
#            --out /tmp/opencode/kernel-v2 --interval 300 --notify
# NOTES: usa o CLI do venv /home/nixos/kvenv (se existir) senao nix nixpkgs#kaggle;
#   SEMPRE env -u KAGGLE_API_TOKEN* (os KGAT mortos no ambiente dominam o CLI).
set -uo pipefail

SLUG=""; OUT=""; INTERVAL=300; NOTIFY=0; MAX_MIN=720
while [[ $# -gt 0 ]]; do
  case "$1" in
    --slug) SLUG="$2"; shift 2;;
    --out) OUT="$2"; shift 2;;
    --interval) INTERVAL="$2"; shift 2;;
    --max-min) MAX_MIN="$2"; shift 2;;
    --notify) NOTIFY=1; shift;;
    -h|--help) sed -n '2,12p' "$0"; exit 0;;
    *) echo "kaggle-kernel-watch: arg desconhecido: $1" >&2; exit 2;;
  esac
done
[[ -z "$SLUG" ]] && { echo "uso: --slug owner/kernel (obrigatorio)" >&2; exit 2; }
[[ -z "$OUT" ]] && OUT="/tmp/opencode/kaggle-$(echo "$SLUG" | tr '/' '-')"
mkdir -p "$OUT"
LOG="/tmp/kaggle-watch-$(echo "$SLUG" | tr '/' '-').log"
SELF=$(basename "$0")

kaggle_cmd() {
  if [[ -x /home/nixos/kvenv/bin/kaggle ]]; then
    env -u KAGGLE_API_TOKEN -u KAGGLE_API_TOKEN_O2 /home/nixos/kvenv/bin/kaggle "$@"
  else
    env -u KAGGLE_API_TOKEN -u KAGGLE_API_TOKEN_O2 nix shell nixpkgs#kaggle -c kaggle "$@"
  fi
}

log() { echo "$(date '+%H:%M:%S') $*" | tee -a "$LOG"; }

log "$SELF on: slug=$SLUG out=$OUT intervalo=${INTERVAL}s limite=${MAX_MIN}min"
deadline=$(( $(date +%s) + MAX_MIN * 60 ))
status=""
while :; do
  raw=$(kaggle_cmd kernels status "$SLUG" 2>/dev/null | tail -1)
  status=$(printf '%s' "$raw" | grep -oE "RUNNING|COMPLETE|ERROR|QUEUED" | head -1)
  [ -z "$status" ] && status="DESCONHECIDO"
  log "status=$status"
  if [[ "$status" == "COMPLETE" || "$status" == "ERROR" ]]; then
    log "baixando output -> $OUT"
    kaggle_cmd kernels output "$SLUG" -p "$OUT" >> "$LOG" 2>&1
    log "status final=$status (output em $OUT)"
    if [[ "$NOTIFY" -eq 1 && -x /home/nixos/projects/team/tg.sh ]]; then
      /home/nixos/projects/team/tg.sh post "[kaggle] $SLUG -> $status (output em $OUT)" >> "$LOG" 2>&1
    fi
    [[ "$status" == "COMPLETE" ]] && exit 0 || exit 1
  fi
  if (( $(date +%s) > deadline )); then
    log "timeout: ${MAX_MIN}min sem completar (status=$status)"
    exit 3
  fi
  sleep "$INTERVAL"
done
