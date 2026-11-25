#!/usr/bin/env bash
# F21c: rerun the 300M architecture comparison with causal training/reference.
set -uo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT_DIR=${OUT_DIR:-$HOME/work/hybrid}
PYTHON=${PYTHON:-/home/nixos/.venvs/finetune/bin/python}
SEEDS=${SEEDS:-"42 43"}
VARIANTS=${VARIANTS:-"plain ngpt_only loop_spec"}
PROMPTS=${PROMPTS:-100}
STEPS=${STEPS:-4800}
DEPTH=${DEPTH:-1768}
TARGET_TOKENS=16
STATUS="$OUT_DIR/f21c-300m-valid-status.log"

mkdir -p "$OUT_DIR"
G=$(ls -dt /nix/store/*-gcc-*-lib/lib 2>/dev/null | head -1)
export LD_LIBRARY_PATH="$G:/run/opengl-driver/lib:/run/current-system/sw/share/nix-ld/lib"
export TRITON_LIBCUDA_PATH=/run/opengl-driver/lib
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
export CPATH=/nix/store/jy00n3jp5xj8s40n1fbldmkcr5n7avxc-python3-3.13.15/include/python3.13
export CC=/nix/store/0592hadxldzhhd3ppc6nskslzd39fwlz-gcc-wrapper-15.3.0/bin/gcc

for seed in $SEEDS; do
  for variant in $VARIANTS; do
    modes="full"
    if [ "$variant" = "loop_spec" ]; then
      modes="full,per_loop,last"
    fi
    "$PYTHON" -u "$REPO_ROOT/scripts/f21-measure.py" \
      --seed "$seed" --steps "$STEPS" --prompts "$PROMPTS" \
      --target-tokens "$TARGET_TOKENS" --depth "$DEPTH" \
      --variant "$variant" --causal-train --modes "$modes" --device cuda \
      --out "$OUT_DIR/f21c-300m-valid-${variant}-s${seed}.json" \
      > "$OUT_DIR/f21c-300m-valid-${variant}-s${seed}.log" 2>&1
    rc=$?
    printf 'F21C_300M_VALID_%s_S%s_RC=%s\n' "$variant" "$seed" "$rc" >> "$STATUS"
    if [ "$rc" -ne 0 ]; then
      exit "$rc"
    fi
  done
done
printf 'F21C_300M_VALID_DONE\n' >> "$STATUS"
