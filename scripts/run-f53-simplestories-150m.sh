#!/usr/bin/env bash
# F53: SimpleStories diversity corpus, 150M, two seeds, after F50.
set -uo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT_DIR=${OUT_DIR:-$HOME/work/hybrid}
PYTHON=${PYTHON:-/home/nixos/.venvs/finetune/bin/python}
CORPUS_DIR=${CORPUS_DIR:-$HOME/Books/corpora/SimpleStories}
PARQUET=${PARQUET:-$CORPUS_DIR/processed.parquet}
CORPUS=${CORPUS:-$CORPUS_DIR/sample200mb-ids.npy}
SAMPLE_TEXT=${SAMPLE_TEXT:-$CORPUS_DIR/sample200mb.txt}
STATS=${STATS:-$CORPUS_DIR/sample200mb-ids-stats.json}
SEEDS=${SEEDS:-"42 43"}
STEPS=${STEPS:-9600}
DEPTH=${DEPTH:-1216}
LR=${LR:-1e-4}
WARMUP=${WARMUP:-500}
LOCK=${LOCK:-$OUT_DIR/.gpu-job.lock}
STATUS="$OUT_DIR/f53-simplestories-status.log"

mkdir -p "$OUT_DIR/checkpoints"
G=$(ls -dt /nix/store/*-gcc-*-lib/lib 2>/dev/null | head -1)
export LD_LIBRARY_PATH="$G:/run/opengl-driver/lib:/run/current-system/sw/share/nix-ld/lib"
export TRITON_LIBCUDA_PATH=/run/opengl-driver/lib
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# F50 owns the GPU until its curve is complete.
while systemctl --user is-active --quiet jarvis-f50-150m-60k; do
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

if [ ! -s "$CORPUS" ] || [ ! -s "$STATS" ]; then
  if [ -s "$CORPUS" ] && [ -s "$SAMPLE_TEXT" ]; then
    # The canonical 200MB sample already exists; derive only the top-k remap
    # stats required by f32 --npy instead of rebuilding the corpus.
    "$PYTHON" -u "$REPO_ROOT/scripts/f53-derive-stats.py" \
      --text "$SAMPLE_TEXT" --npy "$CORPUS" --stats "$STATS" \
      --vocab 10000 --seed 42 \
      > "$OUT_DIR/f53-simplestories-stats.log" 2>&1
  else
    "$PYTHON" -u "$REPO_ROOT/scripts/f53-simplestories-tokenize.py" \
      --parquet "$PARQUET" --out "$CORPUS" --stats "$STATS" \
      --target-bytes 200000000 --vocab 10000 --seed 42 \
      > "$OUT_DIR/f53-simplestories-tokenize.log" 2>&1
  fi
  rc=$?
  printf 'F53_TOKENIZE_RC=%s\n' "$rc" >> "$STATUS"
  if [ "$rc" -ne 0 ]; then
    exit "$rc"
  fi
fi

for seed in $SEEDS; do
  "$PYTHON" -u "$REPO_ROOT/scripts/f32-wordlevel.py" \
    --npy "$CORPUS" --d "$DEPTH" --steps "$STEPS" --seed "$seed" --batch 8 \
    --no-ss --lr "$LR" --warmup "$WARMUP" --device cuda \
    --ckpt "$OUT_DIR/checkpoints/f53-simplestories-150m-s${seed}.pt" \
    --out "$OUT_DIR/f53-simplestories-150m-s${seed}.json" \
    > "$OUT_DIR/f53-simplestories-150m-s${seed}.log" 2>&1
  rc=$?
  printf 'F53_SIMPLESTORIES_150M_S%s_RC=%s\n' "$seed" "$rc" >> "$STATUS"
  if [ "$rc" -ne 0 ]; then
    exit "$rc"
  fi
done
printf 'F53_SIMPLESTORIES_DONE\n' >> "$STATUS"
