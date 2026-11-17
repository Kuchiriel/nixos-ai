#!/usr/bin/env bash
# dungeon-lab.sh — o teste DO ZERO do dungeon (15/11, criado do nada).
#
# POR QUE ESTE SCRIPT (e nao o nightwatch): o legado rodou o agente pelo
# `jarvis dev --autopilot --once "<pedido>"` — um agente COM FERRAMENTAS
# (read_file/str_replace/execute_shell), nao pelo patcher de json-patch.
# O primeiro A/B meu usou o patcher (outro pipeline) + task invalida (o repo
# ja tinha a solucao) + checker com caminho hardcoded (testava o repo
# original) = mediu NADA. Este script faz o teste CERTO:
#
#   1. LANE DO ZERO: copia o dungeon no commit ANTERIOR a solucao do legado
#      (baseline: sem A*, sem teste) — o agente faz TUDO;
#   2. CHECKER PRIMEIRO: o checker (comportamento, nao implementacao) e
#      escrito antes e TRAVADO (444) — o agente nao ve nem mexe;
#   3. PEDIDO ORIGINAL: o texto do dono, como um humano pediria (PT-BR),
#      sem os "passos" refinados pelo pipeline;
#   4. EXECUCAO: `jarvis dev --autopilot --max-turns 30` (o pipeline do
#      legado), com o modelo escolhido (MTP :8096 / bonsai :8080);
#   5. VEREDITO OBJETIVO: roda o checker travado no lane + confere que a
#      PRODUCAO (~/projects/jarvis-dungeon) ficou intacta + o lane e
#      separado da producao (os 4 pontos do video).
#
# USO:
#   dungeon-lab.sh --model mtp-code     # ou bonsai
#   dungeon-lab.sh --model mtp-code --keep   # nao apaga o lane anterior
set -uo pipefail

REPO=/home/nixos/projects/nixos-ai
DUNGEON_SRC=/home/nixos/projects/jarvis-dungeon
BASELINE_COMMIT=343256793dc60a1a011adf360b611b1e652d7f79
DEV_PY=/nix/store/jy00n3jp5xj8s40n1fbldmkcr5n7avxc-python3-3.13.15/bin/python3
GIT_BIN=/nix/store/b1wn5clix1mz4vpfih7x9cnj9qfh7c6h-git-2.54.0/bin
CORE_BIN=$(ls -d /nix/store/*coreutils-*/bin 2>/dev/null | head -1)

MODEL=mtp-code
BASE_URL=http://127.0.0.1:8096/v1
KEEP=0
while [ $# -gt 0 ]; do
  case "$1" in
    --model) MODEL="$2"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    *) echo "uso: dungeon-lab.sh --model <mtp-code|bonsai> [--keep]"; exit 2 ;;
  esac
done
case "$MODEL" in
  mtp-code) BASE_URL=http://127.0.0.1:8096/v1 ;;
  bonsai)   BASE_URL=http://127.0.0.1:8080/v1 ;;
  *) echo "modelo desconhecido: $MODEL"; exit 2 ;;
esac

LANE=/home/nixos/projects/dungeon-lab
LOG=/tmp/dungeon-lab-$MODEL.log

# ── o PEDIDO ORIGINAL (humano, PT-BR, sem passos refinados) ──
PEDIDO="Os inimigos do jogo estao andando em linha reta e ficam presos nas paredes. Quero que eles encontrem o caminho ate o jogador contornando os obstaculos, e o jogo tem que continuar rodando (python run_game.py abre a tela)."

log() { printf '%s\n' "$*"; }

log "== LAB DO DUNGEON (do zero) | modelo: $MODEL ($BASE_URL) =="

# ── 1) o LANE do zero (baseline: sem A*, sem teste) ──
if [ "$KEEP" != "1" ]; then
  rm -rf "$LANE"
  mkdir -p "$LANE"
  for f in $(git -C "$DUNGEON_SRC" ls-tree -r --name-only "$BASELINE_COMMIT" | grep -v __pycache__); do
    mkdir -p "$LANE/$(dirname "$f")"
    git -C "$DUNGEON_SRC" show "$BASELINE_COMMIT:$f" > "$LANE/$f"
  done
  (cd "$LANE" && git init -q && git add -A &&
    git -c user.email=lab@local -c user.name=lab commit -q -m "baseline: o dungeon sem o A* (o agente faz tudo)")
  log "  lane: $LANE (baseline $BASELINE_COMMIT, sem A*, sem teste)"
fi

# ── 2) o CHECKER, escrito antes e TRAVADO ──
CHECKER_SRC=/home/nixos/projects/nixos-ai/scripts/dungeon-checker.py
if [ ! -f "$CHECKER_SRC" ]; then
  log "  ERRO: o checker nao esta em $CHECKER_SRC"
  exit 3
fi
cp "$CHECKER_SRC" "$LANE/test_dungeon_behavior.py"
chmod 444 "$LANE/test_dungeon_behavior.py"
log "  checker: test_dungeon_behavior.py copiado e TRAVADO (444)"

# ── 3) o BASELINE do checker (o que o agente tem que resolver) ──
log "  -- baseline do checker:"
(cd "$LANE" && timeout 300 nix develop "$REPO" --ignore-env -c \
   bash -c "export PATH='$GIT_BIN:$CORE_BIN:/usr/bin:/bin:\$PATH'; python3 -m pytest -q test_dungeon_behavior.py" 2>&1 | tail -4 | sed 's/^/     /')

# ── 4) a EXECUCAO (o pipeline do legado: autopilot com ferramentas) ──
log "  -- rodando o autopilot (30 turnos):"
export JARVIS_LLM_BASE_URL="$BASE_URL"
export JARVIS_LLM_MODEL="$MODEL"
export JARVIS_LLM_NATIVE_TOOLS=1
cd "$REPO"
export PATH="$GIT_BIN:$CORE_BIN:/usr/bin:/bin:$PATH"
export PYTHONPATH="$REPO/modules/ai/jarvis/src"
timeout 1200 "$DEV_PY" -m jarvis.cli.main dev --project "$LANE" \
  --autopilot --max-turns 30 --once "$PEDIDO" > "$LOG" 2>&1
RC=$?
log "  -- o autopilot saiu com rc=$RC (log: $LOG)"

# ── 5) o VEREDITO OBJETIVO ──
log "  -- veredito (o checker travado, no lane):"
(cd "$LANE" && timeout 300 nix develop "$REPO" --ignore-env -c \
   bash -c "export PATH='$GIT_BIN:$CORE_BIN:/usr/bin:/bin:\$PATH'; python3 -m pytest -q test_dungeon_behavior.py" 2>&1 | tail -6 | sed 's/^/     /')

log "  -- os 4 pontos do video:"
if git -C "$DUNGEON_SRC" status --porcelain | grep -q .; then
  log "     [X] producao intacta? NAO (o repo original foi mexido)"
else
  log "     [ok] producao intacta? SIM (git status vazio)"
fi
if [ "$(realpath "$LANE")" != "$(realpath "$DUNGEON_SRC")" ]; then
  log "     [ok] sandbox separado? SIM ($LANE != $DUNGEON_SRC)"
else
  log "     [X] sandbox separado? NAO"
fi
if [ -w "$LANE/test_dungeon_behavior.py" ]; then
  log "     [X] checker travado? NAO (o agente pode escrever)"
else
  log "     [ok] checker travado? SIM (444)"
fi
log "  -- o que o agente mudou no lane:"
(cd "$LANE" && git status --porcelain | head -8 | sed 's/^/     /')
