#!/usr/bin/env bash
# F38: 50M word-level TinyStories, periodic validation and best checkpoint.
set -uo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT_DIR=${OUT_DIR:-$HOME/work/hybrid}
PYTHON=${PYTHON:-/home/nixos/.venvs/finetune/bin/python}
SEED=${SEED:-42}
STEPS=${STEPS:-20000}
DEPTH=${DEPTH:-704}
VAL_EVERY=${VAL_EVERY:-4000}
VAL_TOKENS=${VAL_TOKENS:-200000}
STATUS="$OUT_DIR/f38-early-stop-status.log"

mkdir -p "$OUT_DIR/checkpoints"
G=$(ls -dt /nix/store/*-gcc-*-lib/lib 2>/dev/null | head -1)
export LD_LIBRARY_PATH="$G:/run/opengl-driver/lib:/run/current-system/sw/share/nix-ld/lib"
export TRITON_LIBCUDA_PATH=/run/opengl-driver/lib
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

"$PYTHON" -u "$REPO_ROOT/scripts/f38-wordlevel-early-stop.py" \
  --steps "$STEPS" --seed "$SEED" --d "$DEPTH" --seq 256 --batch 8 \
  --no-ss --device cuda --val-every "$VAL_EVERY" --val-tokens "$VAL_TOKENS" \
  --ckpt "$OUT_DIR/checkpoints/f38-50m-s${SEED}-step{step}.pt" \
  --out "$OUT_DIR/f38-50m-s${SEED}.json" \
  > "$OUT_DIR/f38-50m-s${SEED}.log" 2>&1
rc=$?
printf 'F38_50M_S%s_RC=%s\n' "$SEED" "$rc" >> "$STATUS"
if [ "$rc" -ne 0 ]; then
  exit "$rc"
fi
printf 'F38_50M_S%s_DONE\n' "$SEED" >> "$STATUS"
