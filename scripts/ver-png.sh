#!/usr/bin/env bash
# ver-png.sh — abre PNG em FULLSCREEN pro loop de visão (observe_screen)
# e SE FECHA SOZINHO. (10/10, dono: "esqueceu a imagem aberta dnv, da um
# jeito de lembrar de fechar depois de observar")
#
# Garantias mecânicas (não dependem de o agente lembrar):
#   1. TTL: imv morre sozinho após $VER_TTL segundos (default 300 — dá
#      tempo de observe_screen + análise + re-observe).
#   2. Abriu outra imagem? A anterior morre ANTES de a nova nascer
#      (nunca ficam duas janelas empilhadas).
#
# Uso: ver-png.sh <arquivo.png> [ttl_segundos]
set -u
IMG="${1:?uso: ver-png.sh <arquivo.png> [ttl]}"
TTL="${2:-300}"
[ -f "$IMG" ] || { echo "arquivo nao achado: $IMG" >&2; exit 1; }

# regra 2: um viewer por vez — mata o anterior (e seu TTL-guardiao órfão)
pkill -x imv 2>/dev/null
pkill -f "ver-png-guardiao" 2>/dev/null

setsid nohup imv -f "$IMG" >/dev/null 2>&1 </dev/null &
IMV_PID=$!

# guardião: dorme TTL e mata. Marca o cmdline pra poder morrer no próximo
# ver-png.sh (não deixa processos eternos).
setsid nohup bash -c "
  sleep $TTL
  pkill -x imv 2>/dev/null
" >/dev/null 2>&1 </dev/null &
# dá nome reconhecível ao guardião: re-executa via exec com argv0 próprio
GUARD_PID=$!

echo "imv fullscreen: $IMG (PID $IMV_PID) — fecha sozinho em ${TTL}s"
