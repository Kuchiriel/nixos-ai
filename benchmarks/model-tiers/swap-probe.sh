#!/usr/bin/env bash
# swap-probe: mede hot-swap (unload+reload) no router. 05:00, com fail-safe.
# Se qualquer passo falhar: restart do service + ALERTA (nunca deixa sem default).
set -u
ALERTA=/home/nixos/projects/team/ALERTA-swap.md
R=http://127.0.0.1:8080
fail() { echo "# ALERTA $(date): $1" > "$ALERTA"; sudo -n systemctl restart llama-cpp-server; exit 1; }
T0=$(date +%s)
curl -s --max-time 60 -X POST "$R/models/unload" -H 'Content-Type: application/json' -d '{"model":"bonsai"}' >/dev/null || fail "unload bonsai falhou"
T1=$(date +%s)
curl -s --max-time 600 -X POST "$R/models/load" -H 'Content-Type: application/json' -d '{"model":"jarvis-fast"}' >/dev/null || fail "load qwen-fast falhou"
T2=$(date +%s)
curl -s --max-time 60 -X POST "$R/models/unload" -H 'Content-Type: application/json' -d '{"model":"jarvis-fast"}' >/dev/null || fail "unload qwen-fast falhou"
curl -s --max-time 600 -X POST "$R/models/load" -H 'Content-Type: application/json' -d '{"model":"bonsai"}' >/dev/null || fail "reload bonsai falhou"
T3=$(date +%s)
curl -s --max-time 90 "$R/v1/chat/completions" -H 'Content-Type: application/json' -d '{"model":"bonsai","messages":[{"role":"user","content":"diga ok"}],"max_tokens":5}' | grep -q choices || fail "bonsai não responde pós-swap"
echo "{\"date\":\"$(date '+%F %H:%M')\",\"unload_s\":$((T1-T0)),\"load_qwen_s\":$((T2-T1)),\"reload_bonsai_s\":$((T3-T2))}" > /home/nixos/projects/nixos-ai/benchmarks/model-tiers/results/swap-0710.json
