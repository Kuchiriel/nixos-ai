#!/usr/bin/env bash
# harbor-lite.sh — bateria Lite fixa p/ regressão do harness.
# Set mínimo que separa sinal de ruído (29/09): bytecopy + bin + extract-line.
# Uso: ./scripts/harbor-lite.sh [bonsai|fast]  (default: bonsai)
# Requer: router no ar, /tmp/harbor-env + /tmp/harbor-work intactos.
set -u
MODEL="${1:-bonsai}"
cd "$(dirname "$0")/.." || exit 1
source /tmp/harbor-env/ldenv.sh
export PYTHONPATH="$PWD/modules/ai/jarvis/src"
export JARVIS_STATE_DIR=/tmp/harbor-work/jarvis-state
export JARVIS_TRIAL_TOOLS=bash-first
if [ "$MODEL" = "fast" ]; then
  export JARVIS_MODEL_REQUIREMENTS='{"tier":"fast"}'
  # Fast (2.6GB :8083) não coexiste com bonsai (4.3GB :8080): ensure com
  # evicção despeja o competidor sozinho (validado 29/09, ida e volta).
  export JARVIS_ENSURE_EVICT=1
fi
STAMP="lite-$(date +%H%M)"
for job in job-one.json job-bin.json job-task3.json; do
  name="$STAMP-$(basename "$job" .json)"
  sg docker -c "/tmp/harbor-env/bin/harbor job start --config /tmp/harbor-work/$job --job-name $name" \
    2>&1 | tail -1
done
nix develop --command python3 scripts/grade-harbor.py 2>&1 | grep -E "^$STAMP|job " | head -12
if [ "$MODEL" = "fast" ]; then
  # Devolve o residente padrão do bot (a bateria despejou o bonsai).
  nix develop --command python3 -c "
from jarvis.core.model_lifecycle import ensure_model
r = ensure_model('bonsai', base_url='http://127.0.0.1:8080')
print('restore bonsai:', r.selected, r.reason.get('evicted'))" 2>&1 | tail -1
fi
