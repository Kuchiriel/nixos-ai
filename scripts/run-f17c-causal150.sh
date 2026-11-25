#!/usr/bin/env bash
# F17c: rerun the six-seed 150M last-loop IC95 with causal training/reference.
set -uo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT_DIR=${OUT_DIR:-$HOME/work/hybrid}
PYTHON=${PYTHON:-/home/nixos/.venvs/finetune/bin/python}
SEEDS=${SEEDS:-"45 46 47 48 49 50"}
PROMPTS=${PROMPTS:-100}
STEPS=${STEPS:-2400}
DEPTH=${DEPTH:-1216}
TARGET_TOKENS=16
STATUS="$OUT_DIR/f17c-causal150-status.log"

mkdir -p "$OUT_DIR"
G=$(ls -dt /nix/store/*-gcc-*-lib/lib 2>/dev/null | head -1)
export LD_LIBRARY_PATH="$G:/run/opengl-driver/lib:/run/current-system/sw/share/nix-ld/lib"
export TRITON_LIBCUDA_PATH=/run/opengl-driver/lib
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export CPATH=/nix/store/jy00n3jp5xj8s40n1fbldmkcr5n7avxc-python3-3.13.15/include/python3.13
export CC=/nix/store/0592hadxldzhhd3ppc6nskslzd39fwlz-gcc-wrapper-15.3.0/bin/gcc

for seed in $SEEDS; do
  "$PYTHON" -u "$REPO_ROOT/scripts/f21-measure.py" \
    --seed "$seed" --steps "$STEPS" --prompts "$PROMPTS" \
    --target-tokens "$TARGET_TOKENS" --depth "$DEPTH" \
    --variant loop_spec --causal-train --modes "full,per_loop,last" --device cuda \
    --out "$OUT_DIR/f17c-causal150-s${seed}.json" \
    > "$OUT_DIR/f17c-causal150-s${seed}.log" 2>&1
  rc=$?
  printf 'F17C_CAUSAL150_S%s_RC=%s\n' "$seed" "$rc" >> "$STATUS"
  if [ "$rc" -ne 0 ]; then
    exit "$rc"
  fi
done
printf 'F17C_CAUSAL150_DONE\n' >> "$STATUS"
