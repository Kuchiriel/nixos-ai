#!/usr/bin/env bash
# dungeon-lab.sh — o teste DO ZERO: criar o JOGO INTEIRO do nada.
#
# (15/11, corrigido depois de 3 tentativas minhas que mediram nada)
# O QUE ESTE TESTE E (e o que o legado provou):
#   1. DIRETORIO VAZIO: sem repo, sem commit, sem arquivo, sem baseline —
#      o agente cria TUDO do zero;
#   2. PEDIDO HUMANO VAGO, EM PT-BR, SEM INSTRUCAO: nada de A*, nada de
#      "faça X em Y", nada de checker. So "faz um jogo de dungeon crawler";
#   3. O PIPELINE DO LEGADO: `jarvis dev --autopilot --max-turns 30` (o
#      agente COM ferramentas: read_file/str_replace/execute_shell) + a
#      persona do legado (o playbook "pode ver / nao pode / entrega /
#      handoff", portado em jarvis/playbooks/);
#   4. VEREDITO OBJETIVO: o checker (escrito antes, travado 444) mede se o
#      JOGO existe, compila, importa, tem mapa+inimigo e roda.
#
# USO:
#   dungeon-lab.sh --model mtp-code      # Qwen 4B MTP perfil de coding (:8096)
#   dungeon-lab.sh --model bonsai        # o modelo do legado (:8080)
set -uo pipefail

REPO=/home/nixos/projects/nixos-ai
DEV_PY=/nix/store/jy00n3jp5xj8s40n1fbldmkcr5n7avxc-python3-3.13.15/bin/python3
GIT_BIN=/nix/store/b1wn5clix1mz4vpfih7x9cnj9qfh7c6h-git-2.54.0/bin
CORE_BIN=$(ls -d /nix/store/*coreutils-*/bin 2>/dev/null | head -1)

MODEL=mtp-code
BASE_URL=http://127.0.0.1:8096/v1
while [ $# -gt 0 ]; do
  case "$1" in
    --model) MODEL="$2"; shift 2 ;;
    *) echo "uso: dungeon-lab.sh --model <mtp-code|bonsai>"; exit 2 ;;
  esac
done
case "$MODEL" in
  mtp-code) BASE_URL=http://127.0.0.1:8096/v1 ;;
  bonsai)   BASE_URL=http://127.0.0.1:8080/v1 ;;
  *) echo "modelo desconhecido: $MODEL"; exit 2 ;;
esac

LAB=/home/nixos/projects/jogo-zero-$MODEL
LOG=/tmp/jogo-zero-$MODEL.log

# O PEDIDO HUMANO (vago, EM INGLES, sem instrucao nenhuma) — o legado rodou em
# EN e o bonsai falha em PT-BR: prompt em PT-BR seria um viés contra ele.
PEDIDO="Make me a dungeon crawler game."

log() { printf '%s\n' "$*"; }
log "== LAB: JOGO DO ZERO | modelo $MODEL ($BASE_URL) =="

# 1) DIRETORIO VAZIO (sem repo, sem commit, sem nada)
rm -rf "$LAB"
mkdir -p "$LAB"
log "  lab: $LAB (vazio, sem git, sem commit)"

# 2) o CHECKER: escrito antes, dentro do lab, travado
CHECKER_SRC="$REPO/scripts/dungeon-checker-jogo.py"
cp "$CHECKER_SRC" "$LAB/test_jogo_zero.py"
chmod 444 "$LAB/test_jogo_zero.py"
log "  checker: test_jogo_zero.py (travado 444) — mede: codigo, compila, importa, mapa+inimigo, roda"

# 3) o baseline do checker (vazio = tudo deve falhar)
log "  -- baseline (vazio):"
(cd "$LAB" && timeout 240 nix develop "$REPO" --ignore-env -c bash -c \
  "export PATH='$GIT_BIN:$CORE_BIN:/usr/bin:/bin:\$PATH'; LAB_ROOT=$LAB python3 -m pytest -q test_jogo_zero.py" 2>&1 | tail -3 | sed 's/^/     /')

# 4) A EXECUCAO (pipeline do legado: autopilot com ferramentas, 30 turnos)
log "  -- rodando o autopilot (30 turnos, pedido: '$PEDIDO')"
export JARVIS_LLM_BASE_URL="$BASE_URL"
export JARVIS_LLM_MODEL="$MODEL"
export JARVIS_LLM_NATIVE_TOOLS=1
cd "$REPO"
export PATH="$GIT_BIN:$CORE_BIN:/usr/bin:/bin:$PATH"
export PYTHONPATH="$REPO/modules/ai/jarvis/src"
timeout 1500 "$DEV_PY" -m jarvis.cli.main dev --project "$LAB" \
  --autopilot --max-turns 30 --once "$PEDIDO" > "$LOG" 2>&1
log "  -- o autopilot saiu (rc=$?), log: $LOG"

# 5) VEREDITO
log "  -- VEREDITO (o checker travado):"
(cd "$LAB" && timeout 300 nix develop "$REPO" --ignore-env -c bash -c \
  "export PATH='$GIT_BIN:$CORE_BIN:/usr/bin:/bin:\$PATH'; LAB_ROOT=$LAB python3 -m pytest -q test_jogo_zero.py" 2>&1 | tail -8 | sed 's/^/     /')

log "  -- o que o agente criou:"
find "$LAB" -type f -not -path "*/.git/*" -not -path "*__pycache__*" | head -20 | sed "s#$LAB#  #"
log "  -- linhas de codigo:"
find "$LAB" -name "*.py" -not -path "*__pycache__*" -exec cat {} + 2>/dev/null | wc -l | sed 's/^/     /'
