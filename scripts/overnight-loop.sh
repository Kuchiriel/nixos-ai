#!/usr/bin/env bash
# overnight-loop.sh — a semente germinando (F-supervisor, 26/09).
#
#   mede → arquiva → MoE patcha → re-mede → gate (reverte se regredir)
#
# Gate com dentes: HEAD pré-patch gravado; se o easy pós < pré,
# `git reset --hard` volta TUDO (a árvore é do loop de madrugada).
# Nunca push. Relatório da manhã em /tmp/opencode/.
#
# Uso: ./scripts/overnight-loop.sh [--max-tasks 3] [--max-minutes 150]
set -u
cd "$HOME/projects/nixos-ai"

MAX_TASKS=3
MAX_MINUTES=150
for arg in "$@"; do
  case "$arg" in
    --max-tasks=*) MAX_TASKS="${arg#*=}" ;;
    --max-minutes=*) MAX_MINUTES="${arg#*=}" ;;
  esac
done

STAMP=$(date +%Y-%m-%d__%H-%M-%S)
REPORT="/tmp/opencode/overnight-$STAMP.md"
{
echo "# Overnight loop $STAMP"
echo
echo "## Fase 1 — medida pré (engine runtime, easy+medium)"
nix develop --command python3 scripts/loop-close.py \
  --tier easy --rounds 1 --apply-lessons --file-tasks \
  --out /tmp/opencode/loop-pre-easy.json
nix develop --command python3 scripts/loop-close.py \
  --tier medium --rounds 1 --apply-lessons --file-tasks \
  --out /tmp/opencode/loop-pre-medium.json
} 2>&1 | tail -4
PRE_HEAD=$(git rev-parse HEAD)
PRE_EASY=$(python3 -c "import json;print(json.load(open('/tmp/opencode/loop-pre-easy.json'))['results'][0]['world_ok'])" 2>/dev/null || echo "?")
echo "PRE_HEAD=$PRE_HEAD PRE_EASY_SUM=$(python3 -c "import json;d=json.load(open('/tmp/opencode/loop-pre-easy.json'));print(sum(1 for r in d['results'] if r['world_ok']),'/',len(d['results']))")"

echo "## Fase 2 — MoE patcha (max_tasks=$MAX_TASKS, ${MAX_MINUTES}min)"
nix develop --command python3 -c "
import sys; sys.path.insert(0, 'modules/ai/jarvis/src')
from nightwatch.harness import run_nightwatch
run_nightwatch(max_tasks=$MAX_TASKS, max_minutes=$MAX_MINUTES, report_telegram=False)
" 2>&1 | tail -4

echo "## Fase 3 — re-medida + GATE"
nix develop --command python3 scripts/loop-close.py \
  --tier easy --rounds 1 --out /tmp/opencode/loop-post-easy.json 2>&1 | tail -3
POST_SUM=$(python3 -c "import json;d=json.load(open('/tmp/opencode/loop-post-easy.json'));print(sum(1 for r in d['results'] if r['world_ok']),'/',len(d['results']))")
PRE_SUM=$(python3 -c "import json;d=json.load(open('/tmp/opencode/loop-pre-easy.json'));print(sum(1 for r in d['results'] if r['world_ok']),'/',len(d['results']))")

PRE_N=$(echo "$PRE_SUM" | cut -d/ -f1); POST_N=$(echo "$POST_SUM" | cut -d/ -f1)
{
echo "# Overnight loop $STAMP"
echo
echo "- PRE_HEAD: $PRE_HEAD"
echo "- easy pré: $PRE_SUM | easy pós: $POST_SUM"
echo
if [ "$POST_N" -lt "$PRE_N" ]; then
  echo "## GATE: REGREDIU ($PRE_SUM → $POST_SUM) — revertendo p/ $PRE_HEAD"
  git reset --hard "$PRE_HEAD" 2>&1 | tail -1
  echo "- revertido. Patches do MoE descartados (ver git reflog)."
elif [ "$POST_N" -gt "$PRE_N" ]; then
  echo "## GATE: MELHOROU ($PRE_SUM → $POST_SUM) — mantido."
  git log --oneline "$PRE_HEAD..HEAD" 2>/dev/null | head -6
else
  echo "## GATE: MANTEVE ($PRE_SUM) — mantido."
  git log --oneline "$PRE_HEAD..HEAD" 2>/dev/null | head -6
fi
echo
echo "- pré: /tmp/opencode/loop-pre-easy.json, /tmp/opencode/loop-pre-medium.json"
echo "- pós: /tmp/opencode/loop-post-easy.json"
} | tee "$REPORT"
echo "RELATÓRIO: $REPORT"
