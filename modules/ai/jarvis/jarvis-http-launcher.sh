#!/usr/bin/env bash
# Launcher do JARVIS-over-HTTP (RAG, memória, lições, vault) para a tailnet.
#
# POR QUE ESTE SCRIPT (07/11/2026): o servidor `python -m jarvis.jarvis_http`
# precisa de `fastmcp`, que só existe no PERFIL do JARVIS (medido: 3.2.3 em
# /etc/profiles/per-user/nixos/bin/python3) — não está no closure do Nix.
# Em vez de adicionar uma dependência ao package.nix (decisão do dono), o
# launcher resolve o PYTHONPATH em TEMPO DE EXECUÇÃO, exatamente como o
# coord-mcp-launcher.sh e o jarvis-mcp-launcher.sh já fazem: o mesmo python
# que o MCP do JARVIS usa (fonte única de env — nunca dois envs divergentes).
#
# O jarvis_http.py vive no repo (modules/ai/jarvis/src/jarvis/) e roda a
# partir do checkout — nada é instalado no sistema.
#
# Uso:
#   jarvis-http-launcher.sh [--host <ip>] [--port <porta>]
#
# Default: escuta no IP do tailnet desta maquina (NAO 0.0.0.0: nao expoe
# na LAN; a proteção é o Tailscale + a ACL da tailnet). O host e o port sao
# passados pelo proprio ExecStart da unit.
set -euo pipefail

# shellcheck source=/dev/null
. "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/jarvis-env.sh"

cd "$JARVIS_PROJECT_ROOT"
exec "$JARVIS_PY" -m jarvis.jarvis_http "$@"
