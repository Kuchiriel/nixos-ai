#!/usr/bin/env bash
# F138: train 150M on the FineWeb-Edu 1B-token corpus and apply the
# pre-registered gate F118 (val_loss <= 1.9762, baseline F43).
#
# The corpus was already materialized by F136:
#   fineweb-edu-1b-ids-top10000.npy        1e9 uint16 ids, remap top-10000
#   fineweb-edu-1b-ids-top10000-stats.json  {"vocab": 10000, ...}
# The sidecar name matches f32-wordlevel.py's rule
#   stats = npy.replace(".npy", "-stats.json")
# so no download and no re-tokenization happen here.
set -uo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT_DIR=${OUT_DIR:-$HOME/work/hybrid}
PYTHON=${PYTHON:-/home/nixos/.venvs/finetune/bin/python}
CORPUS=${CORPUS:-$HOME/work/hybrid/fineweb-edu-1b-ids-top10000.npy}
STATS=${STATS:-$HOME/work/hybrid/fineweb-edu-1b-ids-top10000-stats.json}
SEED=${SEED:-42}
STEPS=${STEPS:-9600}
DEPTH=${DEPTH:-1216}
SEQ=${SEQ:-256}
BATCH=${BATCH:-8}
LR=${LR:-1e-4}
WARMUP=${WARMUP:-500}
# Pre-registered gate F118 (docs/f118-corpus-escada): baseline F43 = 1.9762.
GATE_MAX_VAL_LOSS=${GATE_MAX_VAL_LOSS:-1.9762}
LOCK=${LOCK:-$OUT_DIR/.gpu-job.lock}
STATUS="$OUT_DIR/f138-fineweb-status.log"

# Testability: the unit checks and the GPU probe can be stubbed, and
# DRY_RUN=1 prints the trainer command instead of running it.
SYSTEMCTL=${SYSTEMCTL:-systemctl --user}
NVIDIA_SMI=${NVIDIA_SMI:-nvidia-smi}
DRY_RUN=${DRY_RUN:-0}

mkdir -p "$OUT_DIR/checkpoints"
G=$(ls -dt /nix/store/*-gcc-*-lib/lib 2>/dev/null | head -1)
export LD_LIBRARY_PATH="$G:/run/opengl-driver/lib:/run/current-system/sw/share/nix-ld/lib"
export TRITON_LIBCUDA_PATH=/run/opengl-driver/lib
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

gpu_free() {
  ! $NVIDIA_SMI --query-compute-apps=pid,process_name --format=csv,noheader,nounits \
    | grep -q 'finetune'
}

# 1. The corpus must already exist (F136 materialized it).
if [ ! -s "$CORPUS" ] || [ ! -s "$STATS" ]; then
  echo "F53/F138 sem corpus materialized: $CORPUS / $STATS" >> "$STATUS"
  exit 90
fi

# 2. The sidecar must be readable by f32 (vocab + the name rule).
if ! python3 -c "import json,sys; d=json.load(open(sys.argv[1])); assert d['vocab']>0" "$STATS"; then
  echo "F138 stats invalido: $STATS" >> "$STATUS"
  exit 92
fi

# 3. Wait for the GPU, then take the global lock and re-check.
while ! gpu_free; do
  printf 'F138 waiting for a free GPU (%s)\n' "$(date -u +%H:%M:%S)" >> "$STATUS"
  sleep 60
done
exec 9>"$LOCK"
until flock -n 9; do
  sleep 60
done
until gpu_free; do
  printf 'F138 waiting for a free GPU after lock (%s)\n' "$(date -u +%H:%M:%S)" >> "$STATUS"
  sleep 60
done

# 4. Train with exactly the pre-registered protocol.
OUT_JSON="$OUT_DIR/f138-fineweb-150m-s${SEED}.json"
TRAIN_CMD=("$PYTHON" -u "$REPO_ROOT/scripts/f32-wordlevel.py"
  --npy "$CORPUS" --d "$DEPTH" --steps "$STEPS" --seed "$SEED" --batch "$BATCH"
  --seq "$SEQ" --no-ss --lr "$LR" --warmup "$WARMUP" --device cuda
  --ckpt "$OUT_DIR/checkpoints/f138-fineweb-150m-s${SEED}.pt"
  --out "$OUT_JSON")
if [ "$DRY_RUN" = "1" ]; then
  printf 'DRY_RUN: %s\n' "${TRAIN_CMD[*]}" \
    >> "$OUT_DIR/f138-fineweb-150m-s${SEED}.log"
  rc=0
else
  "${TRAIN_CMD[@]}" > "$OUT_DIR/f138-fineweb-150m-s${SEED}.log" 2>&1
  rc=$?
fi
printf 'F138_FINEWEB_S%s_RC=%s\n' "$SEED" "$rc" >> "$STATUS"
if [ "$rc" -ne 0 ]; then
  exit "$rc"
fi

# 5. Apply the pre-registered gate F118 and record the verdict in the JSON.
# In DRY_RUN there is no result JSON, so the gate step is skipped.
if [ "$DRY_RUN" != "1" ]; then
  if [ ! -s "$OUT_JSON" ]; then
    echo "F138 sem JSON de resultado: $OUT_JSON" >> "$STATUS"
    exit 93
  fi
  python3 - "$OUT_JSON" "$GATE_MAX_VAL_LOSS" <<'PY' >> "$STATUS"
import json, pathlib, sys
result_path = pathlib.Path(sys.argv[1])
limit = float(sys.argv[2])
result = json.loads(result_path.read_text(encoding="utf-8"))
value = result["val_loss"]
verdict = "PASS" if value <= limit else "REPROVADO"
gate = {
    "gate": "F118",
    "metric": "val_loss",
    "threshold": limit,
    "observed": value,
    "baseline": "F43 150M TinyStories-full val_loss 1.9762",
    "verdict": verdict,
    "note": "valor acima do limiar reprova o corpus; nao extrapolar",
}
result["gate_f118"] = gate
result_path.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
print("F138_GATE_F118 " + json.dumps(gate))
PY
  gate_rc=$?
  printf 'F138_GATE_RC=%s\n' "$gate_rc" >> "$STATUS"
  if [ "$gate_rc" -ne 0 ]; then
    exit "$gate_rc"
  fi
fi
printf 'F138_FINEWEB_DONE\n' >> "$STATUS"
