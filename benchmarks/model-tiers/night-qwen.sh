#!/usr/bin/env bash
# bench noturno qwen4b-mtp: cicla serviços com verificação (nunca sai com o router morto).
# 04:00: stop router -> start 8092 -> bench -> stop 8092 -> start router -> VERIFICA tudo.
set -u
ALERTA=/home/nixos/projects/team/ALERTA-bench.md
ok() { curl -s --max-time 15 "$1" >/dev/null 2>&1; }

echo "[bench] parando router (libera VRAM p/ 8092)"
sudo -n systemctl stop llama-cpp-server
sleep 5
sudo -n systemctl start llama-uncensored-4b
for i in $(seq 1 30); do ok http://127.0.0.1:8092/v1/models && break; sleep 10; done
if ! ok http://127.0.0.1:8092/v1/models; then
  echo "# ALERTA $(date): 8092 não subiu; router será religado" > "$ALERTA"
  sudo -n systemctl start llama-cpp-server
  exit 1
fi
/home/nixos/projects/nixos-ai/benchmarks/model-tiers/bench.py \
  --endpoint http://127.0.0.1:8092 --model qwen4b --tag qwen4bmtp-0710 \
  > /tmp/opencode/bench-qwen.log 2>&1
sudo -n systemctl stop llama-uncensored-4b
sudo -n systemctl start llama-cpp-server
sleep 20
if ok http://127.0.0.1:8080/v1/models; then
  echo "[bench] router OK; resultado em benchmarks/model-tiers/results/qwen4bmtp-0710.json"
else
  echo "# ALERTA $(date): router NÃO voltou após bench qwen — ver journalctl -u llama-cpp-server" > "$ALERTA"
  exit 1
fi
