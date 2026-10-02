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
# brigar com o build: o wrapper do jarvis-voice é gerado em todas as
# reinstall, então resolver em runtime é também mais robusto — não depende de
# ninguém lembrar de re-gitar o Nix depois de um rebuild.
#
# Como funciona: lê o PYTHONPATH de dentro do próprio binário `jarvis-mcp`
# (que o Nix gravou com as deps do pacote) e o reexporta. Se algum dia o Nix
# passar a gravar o prefixo, este script apenas repassa o que já está lá.
set -euo pipefail

JARVIS_PKG="${JARVIS_PKG:-$(ls -dt /nix/store/*jarvis-voice-0.1.0 2>/dev/null | head -1)}"
if [ -z "$JARVIS_PKG" ] || [ ! -d "$JARVIS_PKG" ]; then
  echo "jarvis-voice nao encontrado no store" >&2
  exit 1
fi

# O Nix passa o site-packages do env do MCP como $1 (declarado no
# home-manager/home.nix). Esse e o caminho oficial e o preferido.
ENV_SP="${1:-}"

# Fallback: se o $1 nao vier, deriva da CLOSURE do pacote.
# não do wrapper: o `dependencies` do buildPythonPackage não escreve
# PYTHONPATH no wrapper (medido: `grep -c PYTHONPATH bin/jarvis-mcp` -> 0), e
# tentar forcing por makeWrapper quebra o build. Ler a closure é à prova de
# rebuild: qualquer store path que cair for substituído no próximo `ls`.
PP="$ENV_SP"
if [ -z "$PP" ] && command -v nix-store >/dev/null 2>&1; then
  while IFS= read -r dep; do
    case "$dep" in
      *-python3.13-*)
        sp="$dep/lib/python3.13/site-packages"
        [ -d "$sp" ] && PP="${PP:+$PP:}$sp"
        ;;
    esac
  done < <(nix-store -q --references "$JARVIS_PKG" 2>/dev/null || true)
fi
# Se um dia o Nix passar a gravar o prefixo no wrapper, usa o que ele gravou.
if [ -z "$PP" ] && [ -r "$JARVIS_PKG/bin/jarvis-mcp" ]; then
  PP="$(sed -n "s/^export PYTHONPATH='\(.*\)'$/\1/p" "$JARVIS_PKG/bin/jarvis-mcp" | head -1)"
fi

SRC="${JARVIS_SRC:-/home/nixos/projects/nixos-ai/modules/ai/jarvis/src}"

export PYTHONPATH="${SRC}${PP:+:$PP}"
export JARVIS_PROJECT_ROOT="${JARVIS_PROJECT_ROOT:-/home/nixos/projects/nixos-ai}"
export JARVIS_PKG

# python do perfil do usuário: existe fora do store (profile symlink), então não
# some com o próximo GC.
PY="/etc/profiles/per-user/nixos/bin/python3"
[ -x "$PY" ] || PY="$(command -v python3)"

cd "$JARVIS_PROJECT_ROOT"
exec "$PY" -m jarvis.mcp_server