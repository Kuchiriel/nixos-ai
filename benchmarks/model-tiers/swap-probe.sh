#!/usr/bin/env bash
# swap-probe (05:00) — virou PROBE DO DEFAULT (02/11).
#
# POR QUE MUDOU: o hot-swap medido antes (bonsai↔jarvis-fast no router
# :8080) não existe mais na topologia nova:
#   - :8080 tem UM preset só (bonsai, prism) — jarvis-fast mora no :8083;
#   - o default agora é o 4B-MTP+LoRA (:8092, 4474MiB) e o bonsai (4.3GB)
#     NÃO cabe junto (VRAM 6.1GB) → o probe media "0s" e alarmava falso
#     ("bonsai não responde pós-swap", 29/10) porque o curl não usava
#     --fail e engolia o erro HTTP.
# AGORA: verifica o que importa — o DEFAULT responde (id = alias, chat OK)
# — e, se não, reinicia o service (fail-safe: nunca deixa a máquina sem
# default). Mede latência de resposta do default.
set -u
ALERTA=/home/nixos/projects/team/ALERTA-swap.md
BASE=http://127.0.0.1:8092
MODEL=jarvis-mtp-lora
OUT=/home/nixos/projects/nixos-ai/benchmarks/model-tiers/results/default-probe.json

models_id() {
  curl -s --fail --max-time 20 "$BASE/v1/models" 2>/dev/null \
    | grep -q "\"id\":\"$MODEL\"\|\"id\": \"$MODEL\""
}

chat_ok() {
  curl -s --fail --max-time 90 "$BASE/v1/chat/completions" \
    -H 'Content-Type: application/json' \
    -d "{\"model\":\"$MODEL\",\"messages\":[{\"role\":\"user\",\"content\":\"diga ok\"}],\"max_tokens\":5}" \
    2>/dev/null | grep -q choices
}

alerta() { echo "# ALERTA $(date): $1" > "$ALERTA"; }

T0=$(date +%s%3N)
if ! models_id; then
  alerta "default :8092 não anuncia o alias $MODEL — reiniciando llama-uncensored-4b"
  sudo -n systemctl restart llama-uncensored-4b
  for _ in $(seq 1 30); do models_id && break; sleep 10; done
fi
if ! models_id; then
  alerta "default :8092 NÃO voltou após restart — ver journalctl -u llama-uncensored-4b"
  echo '{"date":"'"$(date '+%F %H:%M')"'","default_model":"'"$MODEL"'","models_ok":false,"chat_ok":false,"recovered":false}' > "$OUT"
  exit 1
fi

RECOVERED=false
if ! chat_ok; then
  alerta "default :8092 não responde chat — reiniciando llama-uncensored-4b"
  sudo -n systemctl restart llama-uncensored-4b
  for _ in $(seq 1 30); do models_id && break; sleep 10; done
  RECOVERED=true
  if ! chat_ok; then
    alerta "default :8092 NÃO respondeu chat após restart — ver journalctl -u llama-uncensored-4b"
    echo '{"date":"'"$(date '+%F %H:%M')"'","default_model":"'"$MODEL"'","models_ok":true,"chat_ok":false,"recovered":true}' > "$OUT"
    exit 1
  fi
fi
T1=$(date +%s%3N)
echo '{"date":"'"$(date '+%F %H:%M')"'","default_model":"'"$MODEL"'","models_ok":true,"chat_ok":true,"recovered":'"$RECOVERED"',"latency_ms":'$((T1-T0))'}' > "$OUT"
echo "[probe] default $MODEL OK ($((T1-T0))ms) — $OUT"
