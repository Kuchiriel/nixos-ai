#!/usr/bin/env bash
# F39: diagnose F37 seed43 instability with lower LR + warmup.
set -uo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT_DIR=${OUT_DIR:-$HOME/work/hybrid}
PYTHON=${PYTHON:-/home/nixos/.venvs/finetune/bin/python}
SEED=${SEED:-43}
STEPS=${STEPS:-9600}
DEPTH=${DEPTH:-1216}
LR=${LR:-1e-4}
WARMUP=${WARMUP:-500}
FIRST_VAL=${FIRST_VAL:-400}
VAL_EVERY=${VAL_EVERY:-4000}
VAL_TOKENS=${VAL_TOKENS:-200000}
STATUS="$OUT_DIR/f39-150m-lr-status.log"

mkdir -p "$OUT_DIR/checkpoints"
G=$(ls -dt /nix/store/*-gcc-*-lib/lib 2>/dev/null | head -1)
export LD_LIBRARY_PATH="$G:/run/opengl-driver/lib:/run/current-system/sw/share/nix-ld/lib"
export TRITON_LIBCUDA_PATH=/run/opengl-driver/lib
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

"$PYTHON" -u "$REPO_ROOT/scripts/f39-wordlevel-lr-diagnose.py" \
  --steps "$STEPS" --seed "$SEED" --d "$DEPTH" --seq 256 --batch 8 \
  --lr "$LR" --warmup "$WARMUP" --first-val-step "$FIRST_VAL" \
  --val-every "$VAL_EVERY" --val-tokens "$VAL_TOKENS" \
  --no-ss --device cuda \
  --ckpt "$OUT_DIR/checkpoints/f39-150m-s${SEED}-lr${LR}-step{step}.pt" \
  --out "$OUT_DIR/f39-150m-s${SEED}.json" \
  > "$OUT_DIR/f39-150m-s${SEED}.log" 2>&1
rc=$?
printf 'F39_150M_S%s_LR%s_RC=%s\n' "$SEED" "$LR" "$rc" >> "$STATUS"
if [ "$rc" -ne 0 ]; then
  exit "$rc"
fi
printf 'F39_150M_S%s_DONE\n' "$SEED" >> "$STATUS"
