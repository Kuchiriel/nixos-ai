#!/usr/bin/env bash
# run_tune.sh — Self-contained runner for fast_tune
# Activates nix dev environment and runs the optimizer
set -euo pipefail
cd "$(dirname "$0")"

# Find python3 from nix store
PYTHON3=$(nix develop --command which python3 2>/dev/null | tail -1)
export PYTHONPATH="$(pwd)/modules/ai/jarvis/src:${PYTHONPATH:-}"

echo "Using: $PYTHON3"
echo "PYTHONPATH: $PYTHONPATH"

exec "$PYTHON3" fast_tune.py \
    --runs "${RUNS:-1}" \
    --ctx-size "${CTX_SIZE:-196608}" \
    --log-dir logs/fast-tune
