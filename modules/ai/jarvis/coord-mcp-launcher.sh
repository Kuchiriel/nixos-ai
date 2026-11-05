#!/usr/bin/env bash
# Launcher do MCP de coordenação por HTTP (streamable-http) para a tailnet.
#
# POR QUE ESTE SCRIPT (05/11): o servidor `python -m jarvis.coord_http`
# precisa de `fastmcp`, que só existe no PERFIL do JARVIS (medido: 3.2.3 em
# /etc/profiles/per-user/nixos/bin/python3) — não está no closure do Nix.
# Em vez de adicionar uma dependência ao package.nix (decisão do dono), o
# launcher resolve o PYTHONPATH em TEMPO DE EXECUÇÃO, como o
# jarvis-mcp-launcher.sh já faz: o mesmo python que o MCP do JARVIS usa.
#
# O coord_http.py vive no repo (modules/ai/jarvis/src/jarvis/) e roda a
# partir do checkout — nada é instalado no sistema.
#
# Uso:
#   coord-mcp-launcher.sh [--host <ip>] [--port <porta>]
#
# Default: escuta no IP do tailnet desta maquina (NAO 0.0.0.0: nao
# expoe na LAN; a proteção é o Tailscale). O host e o port sao passados
# pelo proprio ExecStart da unit.
set -euo pipefail

# O $1 do jarvis-env.sh e o site-packages OFICIAL (nao um perfil): aqui
# NAO passamos nada -> ele descobre o env pela config do opencode. Os
# argumentos desta launcher (--host/--port) vao direto para o coord_http.
# shellcheck source=/dev/null
. /home/nixos/projects/nixos-ai/modules/ai/jarvis/jarvis-env.sh

cd "$JARVIS_PROJECT_ROOT"
exec "$JARVIS_PY" -m jarvis.coord_http "$@"
