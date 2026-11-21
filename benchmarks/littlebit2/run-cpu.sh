#!/bin/bash
# QAT A/B em CPU: sem GPU, sem parar servicos de producao.
set -uo pipefail
LOG=/home/nixos/projects/LittleBit/ab-cpu.log
LIB=/nix/store/0ba5kj6r0zhfwd84l5vzccqvx7amlq2c-gcc-15.3.0-lib/lib
export LD_LIBRARY_PATH=$LIB:/run/opengl-driver/lib:/run/current-system/sw/share/nix-ld/lib
export LB_STEPS=${LB_STEPS:-30} LB_SEQ=${LB_SEQ:-256} LB_EVAL_WINDOWS=${LB_EVAL_WINDOWS:-6}
export LB_THREADS=${LB_THREADS:-8} OMP_NUM_THREADS=${LB_THREADS:-8}
cd /home/nixos/projects/LittleBit || exit 1
echo "=== INICIO CPU $(date -u +%FT%TZ) steps=$LB_STEPS seq=$LB_SEQ" >>"$LOG"
for V in False True; do
  echo "=== variant use_itq=$V $(date -u +%FT%TZ)" >>"$LOG"
  .venv/bin/python minimal_qat.py --use-itq "$V" --device cpu --out "cpu_itq_$V.json" >>"$LOG" 2>&1
  echo "=== rc=$? $(date -u +%FT%TZ)" >>"$LOG"
done
echo "=== FIM $(date -u +%FT%TZ)" >>"$LOG"
