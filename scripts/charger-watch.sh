#!/usr/bin/env bash
# charger-watch.sh — detecta desplug do carregador e toca alarme alto.
# Uso: ./scripts/charger-watch.sh [intervalo_segundos]
# Poll em /sys/class/power_supply/ACAD/online (1=plugado, 0=desplugado).
# Transição plugado→desplugado: alarme 3x + repeat a cada 30s enquanto
# desplugado. PID salvo em /tmp/charger-watch.pid (kill por PID, nunca pkill).
INTERVAL="${1:-5}"
AC="/sys/class/power_supply/ACAD/online"
ALERT="$HOME/.local/state/jarvis/charger-alert.wav"
mkdir -p "$(dirname "$ALERT")"

if [[ ! -f "$ALERT" ]]; then
  ffmpeg -y -v error \
    -f lavfi -i "sine=frequency=880:duration=0.25" \
    -f lavfi -i "sine=frequency=1320:duration=0.25" \
    -f lavfi -i "sine=frequency=880:duration=0.25" \
    -f lavfi -i "sine=frequency=1760:duration=0.5" \
    -filter_complex "[0][1][2][3]concat=n=4:v=0:a=1,volume=1.5" "$ALERT"
fi

ac_status() { cat "$AC" 2>/dev/null || echo 1; }

echo $$ > /tmp/charger-watch.pid
LAST=$(ac_status)
echo "charger-watch: monitorando $AC (intervalo ${INTERVAL}s, pid $$)"

while true; do
  ON=$(ac_status)
  if [[ "$LAST" == "1" && "$ON" == "0" ]]; then
    echo "[$(date +%H:%M:%S)] DESCPLUGADO — alarme"
    for _ in 1 2 3; do
      aplay -q "$ALERT" 2>/dev/null
      sleep 0.3
    done
    while [[ "$(ac_status)" == "0" ]]; do
      sleep 30
      aplay -q "$ALERT" 2>/dev/null
    done
    echo "[$(date +%H:%M:%S)] replugado — ok"
  fi
  LAST=$ON
  sleep "$INTERVAL"
done
