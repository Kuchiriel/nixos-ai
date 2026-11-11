#!/usr/bin/env bash
# voice-watchdog.sh — verifica se a pilha de voz esta de pe, e levanta se nao.
#
# POR QUE (10/11, coord-naming): o cliente de voz e' AVULSO (nao e' uma
# unit) e o jarvis-heal so vigia units => qualquer crash da voz a deixa muda
# sem ninguem levantar. Medido: o cliente morreu em 10/11 as 17:27:23 (uma
# tool abriu um wav meio escrito) e nao voltou; o unico registro era
# "dormindo", que fez o crash parecer um sono planejado. O conserto do crash
# ja esta no codigo (8363d8be); este script cobre a classe maior: qualquer
# outra queda.
#
# Este script NAO instala nada e NAO muda config: ele apenas verifica e,
# com --restart, sobe a pilha pelo runner (que resolve o LD_LIBRARY_PATH pelo
# scripts/asrd_env.py, senao o cliente morre no import do numpy). A DECISAO
# de apontar um timer do systemd (ou cron) para ele e' do dono.
#
# USO
#   scripts/voice-watchdog.sh              # so verifica (exit 1 se estiver caido)
#   scripts/voice-watchdog.sh --restart    # levanta se estiver caido
#   scripts/voice-watchdog.sh --quiet      # nao imprime (para timer)
#
# EXEMPLO
#   $ scripts/voice-watchdog.sh
#   voice: UP (cliente 2551160, asrd 2551618)
#   $ scripts/voice-watchdog.sh --restart
#   voice: DOWN (sem cliente) -> levantando...
set -uo pipefail

HERE="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
RESTART=0
QUIET=0
for a in "$@"; do
  case "$a" in
    --restart) RESTART=1 ;;
    --quiet) QUIET=1 ;;
    -h|--help) sed -n '2,28p' "$0"; exit 0 ;;
    *) echo "arg desconhecido: $a" >&2; exit 2 ;;
  esac
done

# O padrao entre colchetes evita que o proprio comando case com ele.
_client="$(pgrep -f 'duplex-[v]oice\.py' | head -1)"
_asrd="$(pgrep -f 'duplex-[a]srd\.py' | head -1)"

say() { [ "$QUIET" = "1" ] || echo "$1"; }

if [ -n "$_client" ] && [ -n "$_asrd" ]; then
  say "voice: UP (cliente $_client, asrd $_asrd)"
  exit 0
fi

if [ "$RESTART" != "1" ]; then
  say "voice: DOWN (cliente=${_client:-nenhum}, asrd=${_asrd:-nenhum})"
  exit 1
fi

say "voice: DOWN (cliente=${_client:-nenhum}, asrd=${_asrd:-nenhum}) -> levantando..."
# o runner mata orfaos ao subir (pkill) e resolve o LD_LIBRARY_PATH
cd "$REPO" || exit 1
setsid nohup ./scripts/duplex-voice-run.sh --gate intent \
  >> /tmp/opencode/voice-watchdog.log 2>&1 &
sleep 20
_client="$(pgrep -f 'duplex-[v]oice\.py' | head -1)"
_asrd="$(pgrep -f 'duplex-[a]srd\.py' | head -1)"
if [ -n "$_client" ] && [ -n "$_asrd" ]; then
  say "voice: UP de novo (cliente $_client, asrd $_asrd)"
  exit 0
fi
say "voice: NAO voltou (veja /tmp/opencode/voice-watchdog.log)"
exit 1
