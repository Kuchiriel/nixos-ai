#!/usr/bin/env bash
# F50: 150M full corpus, 60k-step validation curve, one seed.
set -uo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT_DIR=${OUT_DIR:-$HOME/work/hybrid}
PYTHON=${PYTHON:-/home/nixos/.venvs/finetune/bin/python}
CORPUS=${CORPUS:-$HOME/Books/corpora/tinystories-full-ids.npy}
STEPS=${STEPS:-60000}
DEPTH=${DEPTH:-1216}
SEED=${SEED:-42}
LR=${LR:-1e-4}
WARMUP=${WARMUP:-500}
VAL_EVERY=${VAL_EVERY:-4000}
LOCK=${LOCK:-$OUT_DIR/.gpu-job.lock}
STATUS="$OUT_DIR/f50-150m-60k-status.log"

mkdir -p "$OUT_DIR/checkpoints"
G=$(ls -dt /nix/store/*-gcc-*-lib/lib 2>/dev/null | head -1)
export LD_LIBRARY_PATH="$G:/run/opengl-driver/lib:/run/current-system/sw/share/nix-ld/lib"
export TRITON_LIBCUDA_PATH=/run/opengl-driver/lib
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# F49 owns the GPU until its 40k curve is complete.
while systemctl --user is-active --quiet jarvis-f49; do
  sleep 60
done

# One global GPU lock plus a process check for trainers that do not use it.
exec 9>"$LOCK"
until flock -n 9; do
  sleep 60
done
while nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader,nounits \
  | grep -q 'finetune'; do
  sleep 60
done

"$PYTHON" -u "$REPO_ROOT/scripts/f32-wordlevel.py" \
  --npy "$CORPUS" --d "$DEPTH" --steps "$STEPS" --val-every "$VAL_EVERY" \
  --seed "$SEED" --batch 8 --no-ss --lr "$LR" --warmup "$WARMUP" \
  --device cuda \
  --ckpt "$OUT_DIR/checkpoints/f50-150m-60k-s${SEED}.pt" \
  --out "$OUT_DIR/f50-150m-60k-s${SEED}.json" \
  > "$OUT_DIR/f50-150m-60k-s${SEED}.log" 2>&1
rc=$?
printf 'F50_150M_60K_S%s_RC=%s\n' "$SEED" "$rc" >> "$STATUS"
if [ "$rc" -ne 0 ]; then
  exit "$rc"
fi
printf 'F50_150M_60K_DONE\n' >> "$STATUS"
