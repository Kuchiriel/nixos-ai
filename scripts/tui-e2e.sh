#!/usr/bin/env bash
# tui-e2e.sh — prova que um comando/slash do TUI roda LOCAL (zero turno de
# modelo), dirigindo um TUI REAL do opencode dentro de um tmux.
#
# POR QUE ESTE TOOL EXISTE (07/11): no opencode 1.18.34 a rota de command do
# SERVIDOR sempre chama o modelo depois do hook `command.execute.before`
# (o `noReply` existe no prompt(), mas o command() nao o usa) — a resposta
# do plugin virava mensagem de usuario e o modelo respondia a ela. A
# correcao foi mover o comando para o PROCESSO DO TUI, que consome o Enter
# antes do prompt submeter. Isso nao se prova lendo codigo: so se prova
# dirigindo o TUI e conferindo que ZERO mensagem foi criada.
#
# O que este script mede (a prova):
#   1. o comando aparece no autocomplete do TUI (plugin carregou);
#   2. apos Enter, o texto some do prompt e a resposta aparece LOCAL
#      (dialogo/toast na tela);
#   3. NENHUMA mensagem e NENHUMA sessao foi criada no banco -> nenhum
#      turno de modelo, nenhum token gasto.
#
# Uso:
#   ./scripts/tui-e2e.sh --command "/jailbreak status"
#   ./scripts/tui-e2e.sh --command "/jailbreak status" --keep   # deixa o tmux
#   ./scripts/tui-e2e.sh --command "/jailbreak status" --assert-regex "Modo red-team"
#
# Saida: 0 = prova passou (comando local, zero mensagem); 1 = falhou.
set -euo pipefail

CMD=""
ASSERT=""
KEEP=0
STATE_ROOT="${TMPDIR:-/tmp}/tui-e2e.$$"
SESSION="tui-e2e-$$"

while [ $# -gt 0 ]; do
  case "$1" in
    --command) CMD="${2:-}"; shift 2 ;;
    --assert-regex) ASSERT="${2:-}"; shift 2 ;;
    --keep) KEEP=1; shift ;;
    --help|-h) sed -n '2,25p' "$0"; exit 0 ;;
    *) echo "arg desconhecido: $1" >&2; exit 2 ;;
  esac
done

if [ -z "$CMD" ]; then
  echo "uso: $0 --command \"/jailbreak status\" [--assert-regex REGEX] [--keep]" >&2
  exit 2
fi

OPENCODE_BIN="${OPENCODE_BIN:-$(command -v opencode || echo /nix/store/phl68anrmlqjmhlk1ls2h71md4fim7w5-opencode-1.18.34/bin/opencode)}"
[ -x "$OPENCODE_BIN" ] || { echo "opencode nao encontrado: $OPENCODE_BIN" >&2; exit 2; }
command -v tmux >/dev/null || { echo "tmux ausente" >&2; exit 2; }

cleanup() {
  [ "$KEEP" = "1" ] || tmux kill-session -t "$SESSION" 2>/dev/null || true
  rm -rf "$STATE_ROOT" 2>/dev/null || true
}
trap cleanup EXIT

# Contagem no banco do opencode. O binario `sqlite3` nao existe nesta
# maquina (NixOS minimal) — o fallback e o modulo sqlite3 do python3.
db_count() {
  local db="$1" table="$2"
  [ -f "$db" ] || { echo 0; return; }
  if command -v sqlite3 >/dev/null 2>&1; then
    sqlite3 "$db" "select count(*) from $table" 2>/dev/null || echo 0
  else
    python3 - "$db" "$table" <<'PY' 2>/dev/null || echo 0
import sqlite3, sys
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True)
print(con.execute(f"select count(*) from {sys.argv[2]}").fetchone()[0])
PY
  fi
}

mkdir -p "$STATE_ROOT/state" "$STATE_ROOT/data" "$STATE_ROOT/work"

# Estado ISOLADO (o teste nao pode sujar o banco/sessao do dono):
# XDG_STATE_HOME + XDG_DATA_HOME + um state proprio do plugin redteam.
# A config GLOBAL (~/.config/opencode) e mantida de proposito: o teste
# valida o que esta DEPLOYED.
tmux new-session -d -s "$SESSION" -x 220 -y 55 -c "$STATE_ROOT/work" \
  "env XDG_STATE_HOME='$STATE_ROOT/state' XDG_DATA_HOME='$STATE_ROOT/data' \
       OPENCODE_REDTEAM_STATE='$STATE_ROOT/redteam.json' \
       OPENCODE_REDTEAM_AUDIT='$STATE_ROOT/audit.log' \
       OPENCODE_DISABLE_AUTOUPDATE=true '$OPENCODE_BIN'"

# espera o prompt aparecer
for _ in $(seq 1 40); do
  sleep 1
  if tmux capture-pane -t "$SESSION" -p 2>/dev/null | grep -q "Ask anything"; then break; fi
done

before_db="$STATE_ROOT/data/opencode/opencode.db"
before_sessions="$(db_count "$before_db" session)"

tmux send-keys -t "$SESSION" "$CMD"
sleep 1.5
tmux send-keys -t "$SESSION" Enter
sleep 3

pane="$(tmux capture-pane -t "$SESSION" -p 2>/dev/null | sed -n '10,32p' | sed 's/^ *//')"
echo "--- tela do TUI apos o comando:"
printf '%s\n' "$pane" | grep -v '^$' | head -12

fail=0

# 1. o comando tem que ter saido do prompt (nao virou mensagem)
if printf '%s' "$pane" | grep -q "$CMD"; then
  echo "FALHOU: o texto do comando continua no prompt (nao foi consumido localmente)"
  fail=1
fi

# 2. nenhuma sessao/mensagem nova -> nenhum turno de modelo
after_db="$STATE_ROOT/data/opencode/opencode.db"
if [ -f "$after_db" ]; then
  sessions="$(db_count "$after_db" session)"
  messages="$(db_count "$after_db" message)"
  echo "--- banco: sessoes $before_sessions -> $sessions | mensagens: $messages"
  if [ "$sessions" != "$before_sessions" ] || [ "$messages" != "0" ]; then
    echo "FALHOU: o comando virou mensagem/turno de modelo (sessoes $sessions, mensagens $messages)"
    fail=1
  fi
else
  echo "--- banco: nenhum criado (sem sessao, sem mensagem) -> zero turno de modelo"
fi

# 3. assert opcional sobre a resposta na tela
if [ -n "$ASSERT" ]; then
  if printf '%s' "$pane" | grep -qE "$ASSERT"; then
    echo "ok: a tela contem /$ASSERT/ (resposta local)"
  else
    echo "FALHOU: a resposta local nao contem /$ASSERT/"
    fail=1
  fi
fi

if [ "$fail" = "0" ]; then
  echo "ok: comando LOCAL (nenhuma mensagem, nenhum turno de modelo)"
else
  echo "FALHOU: ver acima"
fi
exit "$fail"
