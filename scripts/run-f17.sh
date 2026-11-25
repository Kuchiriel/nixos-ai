#!/usr/bin/env bash
# F17: six-seed IC95 estimate for the last-loop KV trade-off.
# Uses the corrected F12 16-position protocol and preserves prior files.
set -uo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT_DIR=${OUT_DIR:-$HOME/work/hybrid}
PYTHON=${PYTHON:-/home/nixos/.venvs/finetune/bin/python}
SEEDS=${SEEDS:-"45 46 47 48 49 50"}
PROMPTS=${PROMPTS:-100}
STEPS=${STEPS:-2400}
TARGET_TOKENS=16
STATUS="$OUT_DIR/f17-valid-status.log"

mkdir -p "$OUT_DIR"
G=$(ls -dt /nix/store/*-gcc-*-lib/lib 2>/dev/null | head -1)
export LD_LIBRARY_PATH="$G:/run/opengl-driver/lib:/run/current-system/sw/share/nix-ld/lib"
export TRITON_LIBCUDA_PATH=/run/opengl-driver/lib
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export CPATH=/nix/store/jy00n3jp5xj8s40n1fbldmkcr5n7avxc-python3-3.13.15/include/python3.13
export CC=/nix/store/0592hadxldzhhd3ppc6nskslzd39fwlz-gcc-wrapper-15.3.0/bin/gcc

for seed in $SEEDS; do
  "$PYTHON" -u "$REPO_ROOT/scripts/f17-measure.py" \
    --seed "$seed" --steps "$STEPS" --prompts "$PROMPTS" \
    --target-tokens "$TARGET_TOKENS" --device cuda \
    --out "$OUT_DIR/f17-valid-s${seed}.json" \
    > "$OUT_DIR/f17-valid-s${seed}.log" 2>&1
  rc=$?
  printf 'F17_VALID_S%s_RC=%s\n' "$seed" "$rc" >> "$STATUS"
  if [ "$rc" -ne 0 ]; then
    exit "$rc"
  fi
done
printf 'F17_VALID_DONE\n' >> "$STATUS"
