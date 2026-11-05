#!/usr/bin/env bash
# Launcher do MCP do JARVIS — resolve o PYTHONPATH em TEMPO DE EXECUÇÃO.
#
# POR QUE ESTE SCRIPT EXISTE (2026-10-02): o opencode.json apontava o MCP para
# um PYTHONPATH com store path fixo:
#
#   PYTHONPATH=/nix/store/z2p11driyn7fxkr6az114za6zsqxj1z1-...site-packages:...
#
# Esse caminho NÃO tem PIL (medido: `ls .../site-packages/PIL` → nada), e
# `dependencies` do buildPythonPackage não põe pillow/pytesseract no sys.path do
# wrapper. Resultado: o MCP rodava sem PIL, o vision.py caía no PNG cru de
# 1,5MB, o Gemini respondia "Unable to process input image", e o
# `observe_screen` passava do `mcp_timeout` (30s) — 2 de 3 medições deram
# 21s e 48s.
#
# Tentar corrigir dentro do Nix deu em `makeWrapper doesn't understand the arg
# MCP_NIXOS_CHANNEL_CACHE` (dois `--prefix` no mesmo wrapProgram). Não vale
# brigar com o build: o wrapper do jarvis é gerado em todas as
# reinstall, então resolver em runtime é também mais robusto — não depende de
# ninguém lembrar de re-gitar o Nix depois de um rebuild.
#
# Como funciona: lê o PYTHONPATH de dentro do próprio binário `jarvis-mcp`
# (que o Nix gravou com as deps do pacote) e o reexporta. Se algum dia o Nix
# passar a gravar o prefixo, este script apenas repassa o que já está lá.
set -euo pipefail

# (28/10, fix432) Fonte de verdade das keys = /etc/litellm.env (legível).
# A sessão desktop pode ter TAVILY_API_KEY antiga no environ; sem este
# source, o MCP herda a key podre e recebe HTTP 432 mesmo com o arquivo
# atualizado. Source ANTES do PYTHONPATH p/ garantir precedência.
# Env COMPARTILHADO com a CLI (jarvis-env.sh): keys de /etc/litellm.env,
# PYTHONPATH (src + site-packages do store + local) e o python do perfil.
# A logica vivia aqui e foi extraida p/ o script ser a UNICA fonte (2026-10-30):
# a CLI rodava em env diferente (sem requests, sem keys) e o rag-index pendurava.
# shellcheck source=/dev/null
. /home/nixos/projects/nixos-ai/modules/ai/jarvis/jarvis-env.sh "${1:-}"

cd "$JARVIS_PROJECT_ROOT"
exec "$JARVIS_PY" -m jarvis.mcp_server