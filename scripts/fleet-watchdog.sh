#!/usr/bin/env bash
# fleet-watchdog — promove itens de inbox presos em queue para steer.
#
# Rodar a cada 10 min no host. Se promover algo, publica 1 linha no bus
# (issue #12) para a frota saber que a entrega tinha travado.
set -uo pipefail
cd /home/nixos/projects/nixos-ai || exit 1

OUT=$(timeout 90 python3 scripts/wake-fix-inbox.py 2>&1)
printf '%s\n' "$OUT"
N=$(printf '%s\n' "$OUT" | grep -oE 'total promovidos: [0-9]+' | grep -oE '[0-9]+' | tail -1)
[ "${N:-0}" -gt 0 ] || exit 0

TS=$(date -u +%Y-%m-%dT%H:%M:%SZ)
BODY=$(mktemp)
cat > "$BODY" <<EOF
**status** de \`fleet-watchdog\` na lane \`host/frota\` → todos

\`\`\`coord-json
{"kind":"status","agent":"fleet-watchdog","to":"","lane":"host/frota","files":[],"intent":"inbox preso promovido: $N item(ns) queue -> steer","note":"wake-monitor sozinho nao destrava; PATCH /inbox/<id> steer acorda a execucao (OpenAPI V2). $TS","pr":null,"head":"","ts":"$TS"}
\`\`\`
EOF
timeout 60 gh api repos/Kuchiriel/mt5/issues/12/comments -F body=@"$BODY" >/dev/null 2>&1 || true
rm -f "$BODY"
