#!/usr/bin/env bash
# voice-watchdog.sh — verifica se a pilha de voz esta de pe e levanta se nao.
#
# POR QUE (13/11, coord-naming): o cliente de voz e' AVULSO (nao e' unit), e
# o jarvis-heal so vigia units => qualquer crash da voz a deixa muda sem ninguem
# levantar (medido: caiu varias vezes num dia, sempre por rebuild do host).
#
# PAUSA (13/11, pedido do dono): o watchdog RESPEITA a pausa. Sem isso, dar
# "systemctl stop" (ou querer a voz quieta) nao adiantava: o proximo ciclo
# do timer levantava a voz de novo. Agora:
#   - o pauseiro da CASA (~/.local/state/jarvis/PAUSED, o mesmo do
#     nightwatch: conteudo "<origin>:<motivo>") pausa a voz tambem;
#   - um pauseiro SO DA VOZ (~/.local/state/jarvis/VOICE_PAUSED) pausa so a
#     voz, sem mexer no resto da casa.
# E o "--pause" ainda DERRIBA a voz que estiver no ar (pausar e' pausar).
#
# USO
#   scripts/voice-watchdog.sh                 # so verifica (exit 1 se caiu)
#   scripts/voice-watchdog.sh --restart       # levanta se caiu (respeita a pausa)
#   scripts/voice-watchdog.sh --pause "dormindo"   # pausa a voz e derruba ela
#   scripts/voice-watchdog.sh --resume       # tira a pausa e levanta a voz
#   scripts/voice-watchdog.sh --self-test     # prova a logica da pausa
#
# EXEMPLO
#   $ scripts/voice-watchdog.sh
#   voice: UP (cliente 2551160, asrd 2551618)
#   $ scripts/voice-watchdog.sh --pause "dormindo"
#   voice: PAUSADO (manual:dormindo) — derrubei a pilha
#   $ scripts/voice-watchdog.sh
#   voice: PAUSADO (manual:dormindo)
set -uo pipefail

HERE="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
STATE_DIR="${JARVIS_STATE_DIR:-$HOME/.local/state/jarvis}"
VOICE_PAUSE="$STATE_DIR/VOICE_PAUSED"
HOUSE_PAUSE="$STATE_DIR/PAUSED"

RESTART=0
PAUSE=0
RESUME=0
SELF_TEST=0
REASON="manual:pausa pedida"

for a in "$@"; do
  case "$a" in
    --restart) RESTART=1 ;;
    --pause) PAUSE=1 ;;
    --resume) RESUME=1 ;;
    --self-test) SELF_TEST=1 ;;
    --reason=*) REASON="manual:${a#--reason=}" ;;
    -h|--help) sed -n '2,30p' "$0"; exit 0 ;;
    *) echo "arg desconhecido: $a" >&2; exit 2 ;;
  esac
done

# O padrao entre colchetes evita que o proprio comando case com ele.
_client_pids() { pgrep -f 'duplex-[v]oice\.py' 2>/dev/null; }
_asrd_pids() { pgrep -f 'duplex-[a]srd\.py' 2>/dev/null; }

paused_reason() {
  if [ -f "$VOICE_PAUSE" ]; then
    head -c 200 "$VOICE_PAUSE"; echo; return 0
  fi
  if [ -f "$HOUSE_PAUSE" ]; then
    echo "casa:$(head -c 200 "$HOUSE_PAUSE" | tr -d '\n')"; return 0
  fi
  return 1
}

kill_stack() {
  for pid in $(_asrd_pids) $(_client_pids); do
    kill "$pid" 2>/dev/null || true
  done
  sleep 2
  for pid in $(_asrd_pids) $(_client_pids); do
    kill -9 "$pid" 2>/dev/null || true
  done
}

start_stack() {
  cd "$REPO" || exit 1
  setsid nohup ./scripts/duplex-voice-run.sh --gate intent \
    >> /tmp/opencode/voice-watchdog.log 2>&1 &
  sleep 20
}

report_state() {
  local c a
  c="$(_client_pids | head -1)"
  a="$(_asrd_pids | head -1)"
  if [ -n "$c" ] && [ -n "$a" ]; then
    echo "voice: UP (cliente $c, asrd $a)"
    return 0
  fi
  echo "voice: DOWN (cliente=${c:-nenhum}, asrd=${a:-nenhum})"
  return 1
}

if [ "$PAUSE" = "1" ]; then
  mkdir -p "$STATE_DIR"
  printf '%s' "$REASON" > "$VOICE_PAUSE"
  kill_stack
  echo "voice: PAUSADO ($REASON) — derrubei a pilha"
  exit 0
fi

if [ "$RESUME" = "1" ]; then
  rm -f "$VOICE_PAUSE"
  echo "voice: pausa removida"
  RESTART=1
fi

if [ "$SELF_TEST" = "1" ]; then
  TMP="$(mktemp -d)"
  export JARVIS_STATE_DIR="$TMP/state"
  mkdir -p "$JARVIS_STATE_DIR"
  fail=0
  # 1) sem pauseiro: o watchdog nao pode dizer PAUSADO
  out="$(JARVIS_STATE_DIR="$TMP/state" "$0" 2>/dev/null | head -1)"
  case "$out" in
    *PAUSADO*) echo "FALHOU: disse PAUSADO sem pauseiro"; fail=1 ;;
    *) echo "ok: sem pauseiro, nao diz PAUSADO ($out)" ;;
  esac
  # 2) pauseiro da voz: tem de dizer PAUSADO e nao levantar nada
  printf 'manual:dormindo' > "$TMP/state/VOICE_PAUSED"
  out="$(JARVIS_STATE_DIR="$TMP/state" "$0" --restart 2>/dev/null | head -1)"
  case "$out" in
    *PAUSADO*) echo "ok: com pauseiro da voz, disse PAUSADO" ;;
    *) echo "FALHOU: com pauseiro da voz disse: $out"; fail=1 ;;
  esac
  # 3) pauseiro da casa tambem pausa a voz
  rm -f "$TMP/state/VOICE_PAUSED"
  printf 'watchdog:memoria' > "$TMP/state/PAUSED"
  out="$(JARVIS_STATE_DIR="$TMP/state" "$0" 2>/dev/null | head -1)"
  case "$out" in
    *PAUSADO*) echo "ok: pauseiro da casa tambem pausa a voz" ;;
    *) echo "FALHOU: pauseiro da casa disse: $out"; fail=1 ;;
  esac
  rm -rf "$TMP"
  [ "$fail" = "0" ] && echo "SELF-TEST ok: pausa da voz e da casa respeitadas" || exit 1
  exit 0
fi

# respeita a pausa: nao levanta, nao reclama, nao gasta turno de ninguem
if reason="$(paused_reason)"; then
  echo "voice: PAUSADO (${reason})"
  exit 0
fi

if [ "$RESTART" != "1" ]; then
  report_state
  exit $?
fi

c="$(_client_pids | head -1)"
a="$(_asrd_pids | head -1)"
if [ -n "$c" ] && [ -n "$a" ]; then
  echo "voice: UP (cliente $c, asrd $a)"
  exit 0
fi
echo "voice: DOWN (cliente=${c:-nenhum}, asrd=${a:-nenhum}) -> levantando..."
start_stack
report_state
