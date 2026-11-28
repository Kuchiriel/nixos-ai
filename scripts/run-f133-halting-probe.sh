#!/usr/bin/env bash
# F133: run the halting probe on the three preregistered sizes and apply
# the F123 gate (same reduction signal at d=320, 704, 1216).
#
# For each size:
#   1. `halting_probe.py check` (CPU, no GPU) — aborts the whole run when the
#      checkpoint/corpus pair does not reproduce the published val_loss;
#   2. `halting_probe.py run` (GPU) under the global flock, after checking that
#      no other trainer holds the GPU;
#   3. the per-size result is kept verbatim.
set -uo pipefail

REPO_ROOT=$(cd "$(dirname "$0")/.." && pwd)
OUT_DIR=${OUT_DIR:-$HOME/work/hybrid}
PYTHON=${PYTHON:-/home/nixos/.venvs/finetune/bin/python}
TOKENS=${TOKENS:-200000}
LOCK=${LOCK:-$OUT_DIR/.gpu-job.lock}
STATUS="$OUT_DIR/f133-halting-probe-status.log"
SUMMARY="$OUT_DIR/f133-halting-probe-summary.json"
DEVICE=${DEVICE:-cuda}

# d=320 ablation-d320-beta005-s42.json, d=704 f42-50m-full-s42.json,
# d=1216 f75-simplefull-s42.json — each with the corpus recorded in its own
# training JSON (the probe derives it).
SIZES=${SIZES:-"320 704 1216"}
# The FINAL checkpoint of each size, not '-best': the published val_loss that
# the auto-check compares against comes from the final model.
ckpt_for_d() {
  case "$1" in
    320) echo "$OUT_DIR/checkpoints/ablation-d320-beta005-s42.pt" ;;
    704) echo "$OUT_DIR/checkpoints/f42-50m-full-s42.pt" ;;
    1216) echo "$OUT_DIR/checkpoints/f75-simplefull-s42.pt" ;;
    *) return 1 ;;
  esac
}

G=$(ls -dt /nix/store/*-gcc-*-lib/lib 2>/dev/null | head -1)
export LD_LIBRARY_PATH="$G:/run/opengl-driver/lib:/run/current-system/sw/share/nix-ld/lib"
export TRITON_LIBCUDA_PATH=/run/opengl-driver/lib
export PYTORCH_CUDA_ALLOC_CONF=expandable_segments:True

gpu_free() {
  ! nvidia-smi --query-compute-apps=pid,process_name --format=csv,noheader,nounits \
    | grep -q 'finetune'
}

mkdir -p "$OUT_DIR/checkpoints"
: > "$STATUS"

for d in $SIZES; do
  ckpt=$(ckpt_for_d "$d") || { echo "F133 sem checkpoint para d=$d" >> "$STATUS"; exit 90; }
  if [ ! -s "$ckpt" ]; then
    echo "F133 checkpoint ausente d=$d: $ckpt" >> "$STATUS"
    exit 91
  fi
  # 1. auto-check on CPU: the pair must reproduce the published val_loss.
  # 32768 tokens of held-out: measured deltas are 0,0633 / 0,0838 / 0,0117 for
  # d=320 / 704 / 1216, while a wrong remap lands at ~7,7 — the 0,10 tolerance
  # separates sampling noise from a genuinely incompatible corpus.
  if ! timeout 1800 "$PYTHON" -u "$REPO_ROOT/scripts/halting_probe.py" check \
       --ckpt "$ckpt" --d "$d" --device cpu --check-tokens 32768 \
       > "$OUT_DIR/f133-probe-check-d${d}.log" 2>&1; then
    echo "F133 check REPROVADO d=$d (ver $OUT_DIR/f133-probe-check-d${d}.log)" >> "$STATUS"
    exit 92
  fi
  echo "F133_CHECK_OK_D$d $(date -u +%H:%M:%S)" >> "$STATUS"

  # 2. GPU run, serialized.
  exec 9>"$LOCK"
  until flock -n 9; do
    sleep 60
  done
  until gpu_free; do
    echo "F133 waiting for a free GPU d=$d ($(date -u +%H:%M:%S))" >> "$STATUS"
    sleep 60
  done
  timeout 7200 "$PYTHON" -u "$REPO_ROOT/scripts/halting_probe.py" run \
    --ckpt "$ckpt" --d "$d" --tokens "$TOKENS" --device "$DEVICE" \
    --out "$OUT_DIR/f133-halting-probe-d${d}.json" \
    > "$OUT_DIR/f133-halting-probe-d${d}.log" 2>&1
  rc=$?
  flock -u 9
  echo "F133_RUN_D${d}_RC=$rc" >> "$STATUS"
  if [ "$rc" -ne 0 ]; then
    exit "$rc"
  fi
done

# 3. Aggregate and apply the F123 rule: the same reduction signal at every size.
"$PYTHON" - "$OUT_DIR" "$SUMMARY" <<'PY' >> "$STATUS"
import json, pathlib, sys
out_dir = pathlib.Path(sys.argv[1])
summary_path = pathlib.Path(sys.argv[2])
sizes = {}
for path in sorted(out_dir.glob("f133-halting-probe-d*.json")):
    data = json.loads(path.read_text(encoding="utf-8"))
    sizes[str(data.get("d"))] = data
reduced = {}
for d, data in sizes.items():
    chosen = data.get("chosen")
    base = data.get("forced", {}).get("depth4", {})
    if chosen and base:
        reduced[d] = {
            "eps": chosen.get("eps"),
            "avg_depth": chosen.get("avg_depth"),
            "depth4_val_loss": base.get("val_loss"),
            "val_loss": chosen.get("val_loss"),
            "acc": chosen.get("acc"),
            "reduction": round(base.get("avg_depth", 4) - chosen.get("avg_depth", 4), 3)
            if isinstance(base.get("avg_depth"), (int, float)) else None,
        }
# The probe's own gate: chosen must exist and the average depth must be <=3.2.
passes = {
    d: bool(data.get("chosen")) and data["chosen"].get("avg_depth", 4) <= 3.2
    for d, data in sizes.items()
}
same_signal = len(reduced) == len(sizes) and len(sizes) >= 3 and all(
    reduced[d].get("avg_depth") is not None for d in reduced
)
summary = {
    "gate": "F123",
    "sizes": sizes,
    "chosen_per_size": reduced,
    "passes_per_size": passes,
    "same_signal_all_sizes": bool(same_signal),
    "verdict": "PASSA" if (same_signal and all(passes.values())) else "NAO PASSA",
}
summary_path.write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
print("F133_SUMMARY " + json.dumps({"verdict": summary["verdict"],
                                    "passes": passes,
                                    "avg_depth": {d: v.get("avg_depth") for d, v in reduced.items()}}))
PY
printf 'F133_DONE\n' >> "$STATUS"
