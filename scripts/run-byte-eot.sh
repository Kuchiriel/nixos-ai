#!/bin/bash
# F104: byte+EOT 257 symbols, d=1312 paired. --check NEVER trains.
# The launch path is deliberately locked to the preregistered F102 gate.
set -uo pipefail
NPY=/home/nixos/work/hybrid/byte-eot-ids.npy
STATS=/home/nixos/work/hybrid/byte-eot-ids-stats.json
TRAINER=/home/nixos/projects/nixos-ai/scripts/f32-byte-eot.py
# During the isolated F104 worktree, prefer its copy; after merge the canonical
# path above is identical.  No training is launched by --check.
if [ -f "/home/nixos/worktrees/f104-byte-eot-gate/scripts/f32-byte-eot.py" ]; then
  TRAINER=/home/nixos/worktrees/f104-byte-eot-gate/scripts/f32-byte-eot.py
fi
FREE_MIN=4500
RUNTIME_PID=2882380

if [ "${1:-}" = "--check" ]; then
  echo "BYTE-EOT: --check (sem treino, sem GPU)"
  /home/nixos/.venvs/finetune/bin/python "$TRAINER" --check
  exit $?
fi
if [ "${1:-}" != "--run" ]; then
  echo "BYTE-EOT: use --check (sem treino) ou --run (explicit)" >&2
  exit 2
fi

# Resource guard: free VRAM and no other CUDA compute job. Validate the
# resource, never a PID. The known resident llama-server is infrastructure.
FREE=$(nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1)
BUSY=$(nvidia-smi --query-compute-apps=pid --format=csv,noheader 2>/dev/null | awk -v skip="$RUNTIME_PID" 'NF && $1!=skip {print $1}' | wc -l)
if [ "${FREE:-0}" -lt "$FREE_MIN" ] || [ "$BUSY" -gt 0 ]; then
  echo "BYTE-EOT: GPU livre=${FREE:-0}MiB (min=$FREE_MIN), outros jobs CUDA=$BUSY — abortando (rc=9)" >&2
  exit 9
fi
[ -f "$NPY" ] || { echo "BYTE-EOT: corpus ausente: $NPY" >&2; exit 8; }
[ -f "$STATS" ] || { echo "BYTE-EOT: stats ausente: $STATS" >&2; exit 8; }

cd /home/nixos/projects/nixos-ai || exit 8
G=$(ls -dt /nix/store/*-gcc-*-lib/lib 2>/dev/null | head -1)
export LD_LIBRARY_PATH="$G:/run/opengl-driver/lib:/run/current-system/sw/share/nix-ld/lib"
export TRITON_LIBCUDA_PATH=/run/opengl-driver/lib
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True
exec /home/nixos/.venvs/finetune/bin/python -u "$TRAINER" --run \
  --device cuda --steps 9600 --seed 42 --batch 8 --seq 256 \
  --lr 1e-4 --warmup 500 \
  --ckpt /home/nixos/work/hybrid/checkpoints/f104-byte-eot-d1312-s42.pt \
  --out /home/nixos/work/hybrid/f104-byte-eot-d1312-s42.json
