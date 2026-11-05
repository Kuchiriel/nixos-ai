#!/usr/bin/env bash
# jarvis-env.sh — env COMPARTILHADO entre o MCP do JARVIS e a CLI (jarvis-cli.sh).
#
# POR QUE EXISTE (2026-10-30): o MCP roda com PYTHONPATH = src + site-packages
# do store + site-packages local e com as keys de /etc/litellm.env. A CLI
# (scripts/jarvis-cli.sh) rodava so com o src no PYTHONPATH e sem as keys:
#   - `import requests` falhava (ModuleNotFoundError) em rag-index/remember;
#   - o provider de LLM abria o circuit breaker (4 falhas) e o rag-index
#     ficava pendurado (timeout de 600s em `nix develop --command`).
# Divergencia de env entre o MCP e a CLI = bug de operacao silencioso.
#
# USO:
#   source jarvis-env.sh [site-packages-oficial]
#   ... depois use "$JARVIS_PY" (python com o PYTHONPATH certo)
#
# O $1 e o site-packages "oficial" que o home-manager passa ao launcher do MCP
# (python3.withPackages [pillow pytesseract requests httpx numpy evdev]).
# Se nao vier, deriva da closure do jarvis (03/11: pacote unico com a voz).
set -uo pipefail

JARVIS_PROJECT_ROOT="${JARVIS_PROJECT_ROOT:-/home/nixos/projects/nixos-ai}"
JARVIS_SRC="${JARVIS_SRC:-$JARVIS_PROJECT_ROOT/modules/ai/jarvis/src}"

# 1) keys: fonte de verdade = /etc/litellm.env (o MCP precisa; a CLI tambem).
#    Source ANTES do PYTHONPATH p/ garantir precedencia sobre o environ da sessao.
if [ -r /etc/litellm.env ]; then
  set -a
  # shellcheck disable=SC1091
  . /etc/litellm.env
  set +a
fi

# 2) site-packages do store
#    03/11: o pacote foi fundido (jarvis, com a voz). O padrao legado
#    (jarvis-voice) ainda existe no store ate o GC — aceito os dois para
#    nao quebrar o MCP/CLI entre o commit e o rebuild.
JARVIS_PKG="${JARVIS_PKG:-$(ls -dt /nix/store/*-jarvis-0.1.0 /nix/store/*-jarvis-voice-0.1.0 2>/dev/null | head -1)}"
ENV_SP="${1:-}"
# 2a) sem $1: descobre o env OFICIAL lendo a config do opencode (o mcp.jarvis
#     recebe o site-packages como 2o arg do launcher). A config e symlink
#     pro store -> acompanha o rebuild sozinha.
if [ -z "$ENV_SP" ]; then
  OC_JSON="${OC_JSON:-$HOME/.config/opencode/opencode.json}"
  if [ -r "$OC_JSON" ]; then
    ENV_SP=$(python3 - "$OC_JSON" <<'PY' 2>/dev/null || true
import json, sys
try:
    d = json.load(open(sys.argv[1]))
    cmd = (d.get("mcp") or {}).get("jarvis", {}).get("command") or []
    for a in cmd:
        if isinstance(a, str) and a.endswith("site-packages"):
            print(a)
            break
except Exception:
    pass
PY
)
  fi
fi
PP="$ENV_SP"
if [ -z "$PP" ] && command -v nix-store >/dev/null 2>&1 && [ -n "${JARVIS_PKG:-}" ]; then
  while IFS= read -r dep; do
    case "$dep" in
      *-python3.13-*)
        sp="$dep/lib/python3.13/site-packages"
        [ -d "$sp" ] && PP="${PP:+$PP:}$sp"
        ;;
    esac
  done < <(nix-store -q --references "$JARVIS_PKG" 2>/dev/null || true)
fi
# Se o Nix passar a gravar o prefixo no wrapper, usa o que ele gravou.
if [ -z "$PP" ] && [ -n "${JARVIS_PKG:-}" ] && [ -r "$JARVIS_PKG/bin/jarvis-mcp" ]; then
  PP="$(sed -n "s/^export PYTHONPATH='\(.*\)'$/\1/p" "$JARVIS_PKG/bin/jarvis-mcp" | head -1)"
fi

# 3b) ultimo recurso: algum env do store que tenha requests+PIL (o MCP usa um)
if [ -z "${PP:-}" ] || [ ! -d "${PP:-}/requests" ]; then
  for cand in $(ls -dt /nix/store/*python3-3.13*-env/lib/python3.13/site-packages 2>/dev/null | head -12); do
    if [ -d "$cand/requests" ] && [ -d "$cand/PIL" ]; then
      PP="${PP:+$PP:}$cand"
      break
    fi
  done
fi

# 4) site-packages LOCAL (fora do store): playwright (browser tool), PIL,
#    pymupdf, pytesseract. Entra JUNTO — nunca substitui o oficial.
LOCAL_SP="/home/nixos/.local/jarvis-mcp-site"
if [ -d "$LOCAL_SP" ]; then
  case ":$PP:" in
    *":$LOCAL_SP:"*) ;;
    *) PP="${LOCAL_SP}${PP:+:$PP}" ;;
  esac
fi

# 4b) 03/11 — deps do PACOTE (core + voz) para a CLI/MCP.
# O console script do jarvis embute a lista completa de site-packages (o hook
# de python do nixpkgs a monta: site.addsitedir). A CLI/MCP rodam
# `python3 -m jarvis...` e ficavam SEM faster-whisper/kokoro ->
# `jarvis stt`, `jarvis speak` e o `bench-stt` morriam com ModuleNotFoundError.
# Extrai-se a MESMA lista do console script: env idêntica, sem divergir e
# sem criar store path novo (o farm via makeSearchPathOutput quebrava o
# build: o hook do nixpkgs usa o pythonPath do input e acusava
# "build input ... does not exist").
JARVIS_DEPS_SP=""
if [ -n "${JARVIS_PKG:-}" ] && [ -d "$JARVIS_PKG/bin" ]; then
  for f in "$JARVIS_PKG"/bin/* "$JARVIS_PKG"/bin/.*-wrapped-wrapped; do
    [ -f "$f" ] || continue
    m="$(grep -m1 -o "site\.addsitedir(p, k), \[[^]]*\]" "$f" 2>/dev/null || true)"
    if [ -n "$m" ]; then
      JARVIS_DEPS_SP="$(printf '%s' "$m" | sed -e 's/.*\[//' -e 's/\].*//' -e "s/'//g" -e 's/,/:/g')"
      break
    fi
  done
fi
if [ -n "$JARVIS_DEPS_SP" ]; then
  PP="${PP:+$PP:}$JARVIS_DEPS_SP"
  # NIX_PYTHONPATH = o mesmo path, mas processado por site.addsitedir (o
  # sitecustomize do python do nix). PYTHONPATH puro NAO processa .pth.
  case ":${NIX_PYTHONPATH:-}:" in
    *":$JARVIS_DEPS_SP:"*) ;;
    *) export NIX_PYTHONPATH="${NIX_PYTHONPATH:+$NIX_PYTHONPATH:}$JARVIS_DEPS_SP" ;;
  esac
fi

export PYTHONPATH="${JARVIS_SRC}${PP:+:$PP}"
export JARVIS_PROJECT_ROOT
export JARVIS_PKG
export JARVIS_SRC

# 4) python do perfil do usuario: existe fora do store (profile symlink), entao
#    nao some com o proximo GC. Fallback: python3 do PATH.
JARVIS_PY="/etc/profiles/per-user/nixos/bin/python3"
[ -x "$JARVIS_PY" ] || JARVIS_PY="$(command -v python3)"
export JARVIS_PY
