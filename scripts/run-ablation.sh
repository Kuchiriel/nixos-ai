#!/bin/bash
# F91: ablacao beta/residual-norm em 3 tamanhos x 3 modos. NAO rodar sem gate.
set -uo pipefail
FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader | awk '{print $1}' | head -1)
BUSY=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader | awk 'NF && $1!=2882380' | wc -l)
if [ "${FREE:-0}" -lt 4500 ] || [ "$BUSY" -gt 0 ]; then
  echo "ABLACAO: GPU livre=${FREE}MiB, outros CUDA=$BUSY — abortando (rc=9)" >&2
  exit 9
fi
if [ "${1:-}" = "--check" ]; then
  echo "ABLACAO: guard OK (livre=${FREE}MiB, outros=$BUSY) — sem treinar"
  exit 0
fi
cd /home/nixos/work/hybrid || exit 8
G=$(ls -dt /nix/store/*-gcc-*-lib/lib 2>/dev/null | head -1)
export LD_LIBRARY_PATH="$G:/run/opengl-driver/lib:/run/current-system/sw/share/nix-ld/lib"
export TRITON_LIBCUDA_PATH=/run/opengl-driver/lib
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
NPY=/home/nixos/Books/corpora/tinystories-full-ids.npy
for D in 320 704 1216; do
  for MODE in beta0 beta005 normoff; do
    export ABLATION_MODE="$MODE"
    TAG="ablation-d${D}-${MODE}-s42"
    /home/nixos/.venvs/finetune/bin/python -u f32-ablation.py \
      --npy "$NPY" --d "$D" --steps 9600 --seed 42 --batch 8 --no-ss \
      --lr 1e-4 --warmup 500 --device cuda --val-every 3200 \
      --ckpt "/home/nixos/work/hybrid/checkpoints/${TAG}.pt" \
      --out "/home/nixos/work/hybrid/${TAG}.json" \
      > "/home/nixos/work/hybrid/${TAG}.log" 2>&1
    echo "ABLATION_RC $TAG=$?" >> /home/nixos/work/hybrid/ablation-status.log
  done
done
