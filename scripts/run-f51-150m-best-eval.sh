#!/usr/bin/env bash
# F51: evaluate F50's best checkpoint on the same held-out corpus window.
set -uo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT_DIR=${OUT_DIR:-$HOME/work/hybrid}
PYTHON=${PYTHON:-/home/nixos/.venvs/finetune/bin/python}
CORPUS=${CORPUS:-$HOME/Books/corpora/tinystories-full-ids.npy}
F50_JSON=${F50_JSON:-$OUT_DIR/f50-150m-60k-s42.json}
LOCK=${LOCK:-$OUT_DIR/.gpu-job.lock}
STATUS="$OUT_DIR/f51-150m-best-eval-status.log"

G=$(ls -dt /nix/store/*-gcc-*-lib/lib 2>/dev/null | head -1)
export LD_LIBRARY_PATH="$G:/run/opengl-driver/lib:/run/current-system/sw/share/nix-ld/lib"
export TRITON_LIBCUDA_PATH=/run/opengl-driver/lib
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

# F50 must finish and publish its JSON before choosing its best checkpoint.
while ! grep -q '^F50_150M_60K_DONE$' "$OUT_DIR/f50-150m-60k-status.log" 2>/dev/null; do
  sleep 60
done
if [ ! -s "$F50_JSON" ]; then
  echo "F51 sem JSON da F50: $F50_JSON" >> "$STATUS"
  exit 90
fi
CHECKPOINT=$(/home/nixos/.venvs/finetune/bin/python - "$F50_JSON" <<'PY'
import json, pathlib, sys
result = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
checkpoint = result.get("best_checkpoint") or result.get("checkpoint")
if not checkpoint:
    raise SystemExit("F50 JSON sem checkpoint")
print(checkpoint)
PY
)
if [ ! -s "$CHECKPOINT" ]; then
  echo "F51 checkpoint ausente: $CHECKPOINT" >> "$STATUS"
  exit 91
fi

exec 9>"$LOCK"
until flock -n 9; do
  sleep 60
done
while nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader,nounits \
  | grep -q 'finetune'; do
  sleep 60
done

"$PYTHON" -u "$REPO_ROOT/scripts/f51-eval-checkpoint.py" \
  --corpus "$CORPUS" --checkpoint "$CHECKPOINT" --seq 256 --batch 8 \
  --val-ratio 0.01 --val-tokens 200000 --device cuda \
  --out "$OUT_DIR/f51-150m-best-eval.json" \
  > "$OUT_DIR/f51-150m-best-eval.log" 2>&1
rc=$?
printf 'F51_150M_BEST_EVAL_RC=%s\n' "$rc" >> "$STATUS"
if [ "$rc" -ne 0 ]; then
  exit "$rc"
fi
printf 'F51_150M_BEST_EVAL_DONE\n' >> "$STATUS"
