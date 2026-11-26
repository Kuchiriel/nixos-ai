#!/usr/bin/env bash
# F43: 150M on the full streamed corpus, two seeds, serialized GPU lock.
set -uo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT_DIR=${OUT_DIR:-$HOME/work/hybrid}
PYTHON=${PYTHON:-/home/nixos/.venvs/finetune/bin/python}
CORPUS=${CORPUS:-$HOME/Books/corpora/tinystories-full-ids.npy}
STATS=${STATS:-$HOME/work/hybrid/f42-full-stats.json}
SEEDS=${SEEDS:-"42 43"}
STEPS=${STEPS:-9600}
DEPTH=${DEPTH:-1216}
LR=${LR:-1e-4}
WARMUP=${WARMUP:-500}
LOCK=${LOCK:-$OUT_DIR/.gpu-job.lock}
STATUS="$OUT_DIR/f43-150m-full-status.log"

mkdir -p "$OUT_DIR/checkpoints"
G=$(ls -dt /nix/store/*-gcc-*-lib/lib 2>/dev/null | head -1)
export LD_LIBRARY_PATH="$G:/run/opengl-driver/lib:/run/current-system/sw/share/nix-ld/lib"
export TRITON_LIBCUDA_PATH=/run/opengl-driver/lib
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# Wait for F42's streamed corpus and its metadata.
while [ ! -f "$STATS" ] || pgrep -f '[f]42_stream.py' >/dev/null; do
  sleep 60
done

# One global GPU job lock. The second check catches trainers that do not use it.
exec 9>"$LOCK"
until flock -n 9; do
  sleep 60
done
while nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader,nounits \
  | grep -q 'finetune'; do
  sleep 60
done

for seed in $SEEDS; do
  "$PYTHON" -u "$REPO_ROOT/scripts/f43-wordlevel-npy.py" \
    --corpus "$CORPUS" --stats "$STATS" \
    --steps "$STEPS" --seed "$seed" --d "$DEPTH" --seq 256 --batch 8 \
    --lr "$LR" --warmup "$WARMUP" --device cuda \
    --ckpt "$OUT_DIR/checkpoints/f43-150m-full-s${seed}.pt" \
    --out "$OUT_DIR/f43-150m-full-s${seed}.json" \
    > "$OUT_DIR/f43-150m-full-s${seed}.log" 2>&1
  rc=$?
  printf 'F43_150M_FULL_S%s_RC=%s\n' "$seed" "$rc" >> "$STATUS"
  if [ "$rc" -ne 0 ]; then
    exit "$rc"
  fi
done
printf 'F43_150M_FULL_DONE\n' >> "$STATUS"
