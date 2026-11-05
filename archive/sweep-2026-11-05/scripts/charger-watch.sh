#!/usr/bin/env bash
# charger-watch.sh — anuncia plug/desplug do carregador na voz do JARVIS.
# Uso: ./scripts/charger-watch.sh [intervalo_segundos]
# Poll em /sys/class/power_supply/ACAD/online (1=plugado, 0=desplugado).
# Toca 1x por transição (sem intervalo): desconectado OU conectado.
# Vozes geradas via: jarvis speak --clone --rvc jarvis (Jarvis_300e + CPU).
# PID salvo em /tmp/charger-watch.pid (kill por PID, nunca pkill).
INTERVAL="${1:-5}"
AC="/sys/class/power_supply/ACAD/online"
OFF="$HOME/.local/state/jarvis/charger-desconectado.wav"
ON_MSG="$HOME/.local/state/jarvis/charger-conectado.wav"

ac_status() { cat "$AC" 2>/dev/null || echo 1; }

echo $$ > /tmp/charger-watch.pid
LAST=$(ac_status)
echo "charger-watch: monitorando $AC (intervalo ${INTERVAL}s, pid $$)"

while true; do
  ON=$(ac_status)
  if [[ "$LAST" == "1" && "$ON" == "0" ]]; then
    echo "[$(date +%H:%M:%S)] DESCONECTADO"
    aplay -q "$OFF" 2>/dev/null
  elif [[ "$LAST" == "0" && "$ON" == "1" ]]; then
    echo "[$(date +%H:%M:%S)] CONECTADO"
    aplay -q "$ON_MSG" 2>/dev/null
  fi
  LAST=$ON
  sleep "$INTERVAL"
done
