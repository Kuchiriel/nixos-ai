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

# (08/11, bug reportado pelo agent-2721289) O opencode 2.2.6 sobe um
# "background server" numa porta de servico GERENCIADA. Se ela estiver
# ocupada (o TUI do dono, ou outro teste isolado), o processo do opencode
# morre na hora -> a sessao tmux morre junto -> o capture falha com
# "can't find pane: tui-e2e-<pid>", que nao diz nada. Aqui a instancia
# isolada recebe uma porta LIVRE propria, configurada no state isolado.
pick_port() {
  python3 -c "
import socket
for port in range(49700, 49999):
    with socket.socket() as s:
        try:
            s.bind(('127.0.0.1', port))
        except OSError:
            continue
    print(port)
    break
else:
    print(0)
"
}
PORT="$(pick_port)"
if [ "$PORT" = "0" ]; then
  echo "sem porta livre para a instancia isolada" >&2
  exit 2
fi
env XDG_STATE_HOME="$STATE_ROOT/state" XDG_DATA_HOME="$STATE_ROOT/data" \
  "$OPENCODE_BIN" service set port "$PORT" >/dev/null 2>&1 || true

# Estado ISOLADO (o teste nao pode sujar o banco/sessao do dono):
# XDG_STATE_HOME + XDG_DATA_HOME + um state proprio do plugin redteam.
# A config GLOBAL (~/.config/opencode) e mantida de proposito: o teste
# valida o que esta DEPLOYED.
tmux new-session -d -s "$SESSION" -x 220 -y 55 -c "$STATE_ROOT/work" \
  "env XDG_STATE_HOME='$STATE_ROOT/state' XDG_DATA_HOME='$STATE_ROOT/data' \
       OPENCODE_REDTEAM_STATE='$STATE_ROOT/redteam.json' \
       OPENCODE_REDTEAM_AUDIT='$STATE_ROOT/audit.log' \
       OPENCODE_LOG_LEVEL=debug \
       OPENCODE_DISABLE_AUTOUPDATE=true '$OPENCODE_BIN' \
       > '$STATE_ROOT/opencode.log' 2>&1"

# espera o prompt aparecer
READY=0
for _ in $(seq 1 40); do
  sleep 1
  if tmux capture-pane -t "$SESSION" -p 2>/dev/null | grep -q "Ask anything"; then
    READY=1
    break
  fi
  # o processo do opencode morreu? A sessao tmux morre com ele: nesse caso
  # o capture devolve "can't find pane" e o motivo sumiu.
  if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    echo "FALHOU: a sessao tmux '$SESSION' morreu antes do prompt." >&2
    echo "--- saida do opencode (a causa real):" >&2
    tail -n 20 "$STATE_ROOT/opencode.log" 2>/dev/null >&2 || true
    exit 1
  fi
done
if [ "$READY" != "1" ]; then
  echo "FALHOU: o prompt (Ask anything) nao apareceu em 40s." >&2
  tmux capture-pane -t "$SESSION" -p 2>/dev/null | tail -20 >&2 || true
  if [ -z "$(tmux capture-pane -t "$SESSION" -p 2>/dev/null | tr -d '[:space:]')" ]; then
    # (08/11) Causa medida: o TUI do opencode 2.2.6 usa o renderer "opentui",
    # que interroga o terminal (cursor position, cores, graphics) e ESPERA as
    # respostas antes de pintar. No tmux o handshake nao fecha => o pane fica
    # vazio, mesmo com o processo vivo. Entao o probe de texto do pane
    # ("Ask anything", do 1.18.34) nao serve no 2.2.6: o assertion tem que
    # ler o EFEITO do comando (o state/audit do plugin), nao a tela.
    echo "" >&2
    echo "DIAGNOSTICO: o pane esta VAZIO com o processo vivo." >&2
    echo "  Causa medida: o TUI 2.2.6 (renderer opentui) interroga o terminal" >&2
    echo "  e espera as respostas antes de pintar; no tmux o handshake nao" >&2
    echo "  fecha. O probe de texto ('Ask anything') e do 1.18.34." >&2
    echo "  Para provar comando local no 2.2.6: assert no STATE do plugin" >&2
    echo "  (redteam.json / audit.log), nao na tela." >&2
  fi
  exit 1
fi

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
