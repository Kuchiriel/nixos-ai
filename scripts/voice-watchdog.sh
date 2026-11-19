#!/usr/bin/env bash
# voice-watchdog.sh — verifica a pilha de voz e delega start/stop a duplex-voice.service (systemd e' o dono unico; sem orfaos).
#
# POR QUE (13/11, coord-naming): o cliente de voz era AVULSO e o jarvis-heal
# so vigia units => qualquer crash deixava a voz muda sem ninguem levantar.
# (19/11) DONO UNICO: a unit `duplex-voice.service` (systemd de usuario,
# declarada em home-manager/modules/services/duplex-voice.nix) e a dona do
# cliente. Este watchdog NAO relanca mais com `setsid nohup` (isso criava
# orfaos que o systemd nao via): ele delega start/stop a unit.
# Consequencia: `--pause` usa `systemctl --user stop` (stop explicito NAO
# dispara o Restart=always da unit); matar pid so, nao bastava.
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
VOICE_UNIT="duplex-voice.service"   # dono unico do cliente desde 19/11

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
  # Stop explicito primeiro: com Restart=always, matar somente o pid faz
  # a unit reanimar o cliente 5 s depois (medido 19/11).
  systemctl --user stop "$VOICE_UNIT" >/dev/null 2>&1 || true
  for pid in $(_asrd_pids) $(_client_pids); do
    kill "$pid" 2>/dev/null || true
  done
  sleep 2
  for pid in $(_asrd_pids) $(_client_pids); do
    kill -9 "$pid" 2>/dev/null || true
  done
}

start_stack() {
  # Nada de setsid nohup: o systemd e' o dono unico (d3047102).
  if ! systemctl --user start "$VOICE_UNIT" >/dev/null 2>&1; then
    echo "voice: falha ao start $VOICE_UNIT (systemctl --user)" >&2
    return 1
  fi
  for _i in $(seq 1 20); do
    [ "$(systemctl --user is-active "$VOICE_UNIT" 2>/dev/null)" = "active" ] && return 0
    sleep 1
  done
  return 1
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
  # 4) dono unico: --restart delega ao systemd, nunca ao setsid nohup
  rm -f "$TMP/state/VOICE_PAUSED" "$TMP/state/PAUSED"
  FAKEBIN="$TMP/bin"; mkdir -p "$FAKEBIN"
  cat > "$FAKEBIN/systemctl" <<'EOS'
#!/usr/bin/env bash
printf 'systemctl %s\n' "$*" >> "$FAKECTL_LOG"
if [ "${1:-}" = "--user" ] && [ "${2:-}" = "is-active" ]; then echo active; fi
exit 0
EOS
  cat > "$FAKEBIN/pgrep" <<'EOS'
#!/usr/bin/env bash
exit 1
EOS
  cat > "$FAKEBIN/setsid" <<'EOS'
#!/usr/bin/env bash
printf 'setsid %s\n' "$*" >> "$FAKECTL_LOG"
exit 0
EOS
  chmod +x "$FAKEBIN/systemctl" "$FAKEBIN/pgrep" "$FAKEBIN/setsid"
  export FAKECTL_LOG="$TMP/ctl.log"; : > "$FAKECTL_LOG"
  PATH="$FAKEBIN:$PATH" JARVIS_STATE_DIR="$TMP/state" "$0" --restart >/dev/null 2>&1 || true
  if grep -q 'start duplex-voice.service' "$FAKECTL_LOG"; then
    echo "ok: --restart delega ao systemd"
  else
    echo "FALHOU: --restart nao chamou systemctl start"; fail=1
  fi
  if grep -q 'setsid' "$FAKECTL_LOG"; then
    echo "FALHOU: --restart ainda cria orfao via setsid"; fail=1
  else
    echo "ok: --restart nao cria orfao"
  fi
  # 5) --pause para a unit (stop explicito vence Restart=always)
  : > "$FAKECTL_LOG"
  PATH="$FAKEBIN:$PATH" JARVIS_STATE_DIR="$TMP/state" "$0" --pause --reason=teste >/dev/null 2>&1 || true
  if grep -q 'stop duplex-voice.service' "$FAKECTL_LOG"; then
    echo "ok: --pause usa systemctl stop"
  else
    echo "FALHOU: --pause nao parou a unit"; fail=1
  fi
  rm -rf "$TMP"
  [ "$fail" = "0" ] && echo "SELF-TEST ok: pausa, dono unico e delegate systemd" || exit 1
  exit 0
fi

# respeita a pausa: nao levanta, nao reclama, nao gasta turno de ninguem
if reason="$(paused_reason)"; then
  echo "voice: PAUSADO (${reason})"
  exit 0
fi

# (15/11, dono) PERFIL DE CODIGO CARREGADO -> a voz NAO pode ficar no ar.
# O 4B-MTP tem DOIS perfis (exclusivos por VRAM, 6 GB): o COM o LoRA
# microturn (:8092, jarvis-mtp-lora, PHONE CALL) e o de CODING (:8096,
# jarvis-mtp-code, SEM LoRA). Com o perfil de CODIGO carregado nao ha VRAM
# para o duplex — e o dono NAO quer o MTP+LoRA em coding/testes. Entao o
# watchdog nao re-arma a voz E derruba a que estiver no ar.
PERFIL_DE_CODIGO=""
for _pid in $(pgrep -f "llama-server.*jarvis-mtp-code" 2>/dev/null); do
  PERFIL_DE_CODIGO="$_pid"
done
if [ -n "$PERFIL_DE_CODIGO" ]; then
  echo "voice: PARADA (perfil de CODING do MTP carregado, pid=$PERFIL_DE_CODIGO) — o duplex nao cabe na VRAM (6 GB) e o MTP+LoRA e para phone call, nao para coding"
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
