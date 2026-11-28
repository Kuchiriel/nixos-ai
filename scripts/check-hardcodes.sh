#!/usr/bin/env bash
# check-hardcodes.sh — reporta literais IP/hostname fora da allowlist canônica.
# Uso: ./scripts/check-hardcodes.sh [repo-root]
set -euo pipefail
ROOT="${1:-$(git rev-parse --show-toplevel 2>/dev/null || pwd)}"
cd "$ROOT"
PAT='100\.104\.175\.123|100\.121\.100\.103'
# Allowlist canônica (ver docs/auditoria/HARDCODES-ALLOWLIST-2026-11-28.md)
allow() {
  case "$1" in
    scripts/agent-config.json) return 0;;
    hosts/nitro-v15/*) return 0;;
    home-manager/home.nix) return 0;;
    home-manager/modules/agent-hub.nix) return 0;;
    home-manager/modules/services/coord-mcp.nix) return 0;;
    home-manager/modules/services/jarvis-knowledge-mcp.nix) return 0;;
    home-manager/modules/services/opencode-serve.nix) return 0;;
    tests/test_agent_msg_channel.py) return 0;;
    docs/auditoria/HARDCODES-REMANESCENTES-2026-11-28.md) return 0;;
    docs/auditoria/HARDCODES-ALLOWLIST-2026-11-28.md) return 0;;
    # env-first fallbacks documentados (exceção 28/11)
    modules/ai/jarvis/src/jarvis/coord_http.py) return 0;;
    scripts/async-fleet.py) return 0;;
    scripts/async-fleet2.py) return 0;;
    scripts/async-fleet3.py) return 0;;
    scripts/fleet-milestone.py) return 0;;
    *) return 1;;
  esac
}
mapfile -t hits < <(git ls-files '*.py' '*.sh' '*.mjs' '*.js' '*.nix' '*.json' '*.toml' '*.yaml' '*.yml' | xargs grep -lE "$PAT" 2>/dev/null | sort -u)
total=${#hits[@]}
ok=0; bad=0; bad_files=()
for f in "${hits[@]}"; do
  if allow "$f"; then ok=$((ok+1))
  else bad=$((bad+1)); bad_files+=("$f"); fi
done
echo "total_hits=$total allowlisted=$ok outside_allowlist=$bad"
for f in "${bad_files[@]}"; do echo "OUT $f"; done
[ "$bad" -eq 0 ]
