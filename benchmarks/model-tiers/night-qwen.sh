#!/usr/bin/env bash
# bench noturno do DEFAULT (4B-MTP+LoRA, :8092). 04:00.
#
# TOPOLOGIA ATUAL: :8092 e o default com uma unica instancia. O router/bonsai
# :8080 e on-demand e a unit pode nao existir na maquina. O bench:
#   1) garante o default de pe e que a porta seja servida pela unit do registry
#   2) para o router somente quando a unit existe
#   3) mede o default ja residente
#   4) religa e verifica o router somente quando ele foi parado
#
# `--check-only` valida o runtime sem medir nem tocar em services.
set -u
CHECK_ONLY=0
case "${1:-}" in
  "") ;;
  --check-only) CHECK_ONLY=1 ;;
  *) echo "uso: $0 [--check-only]" >&2; exit 2 ;;
esac
ALERTA=/home/nixos/projects/team/ALERTA-bench.md
# (03/11) Fonte única: o registry vem do Nix (models.nix). O default, a
# porta, a unit e a porta do router saem de lá — nada de literal aqui.
# shellcheck source=/home/nixos/projects/nixos-ai/scripts/jarvis-registry.sh
. /home/nixos/projects/nixos-ai/scripts/jarvis-registry.sh
MODEL="$(reg_default)"
BASE="$(reg_endpoint "$MODEL")"
DEFAULT_UNIT="$(reg_unit "$MODEL")"
ROUTER_BASE="$(reg_endpoint bonsai)"
ROUTER_UNIT="$(reg_unit bonsai)"
ROUTER_LOAD_STATE="$(systemctl show -p LoadState --value "$ROUTER_UNIT" 2>/dev/null || true)"
ROUTER_MANAGED=1
case "$ROUTER_LOAD_STATE" in
  ""|not-found) ROUTER_MANAGED=0 ;;
esac
ok() { curl -s --max-time 15 "$1" >/dev/null 2>&1; }
verify_endpoints() {
  if ! ok "$BASE/v1/models"; then
    echo "# ALERTA $(date): default $BASE NÃO respondeu — ver journalctl -u $DEFAULT_UNIT" > "$ALERTA"
    return 1
  fi
  if [ "$ROUTER_MANAGED" -eq 1 ] && ! ok "$ROUTER_BASE/v1/models"; then
    echo "# ALERTA $(date): router $ROUTER_BASE NÃO respondeu — ver journalctl -u $ROUTER_UNIT" > "$ALERTA"
    return 1
  fi
}

# 1) default de pé?
if ! ok "$BASE/v1/models"; then
  echo "[bench] default $BASE fora do ar — subindo $DEFAULT_UNIT"
  sudo -n systemctl start "$DEFAULT_UNIT"
  for _ in $(seq 1 30); do ok "$BASE/v1/models" && break; sleep 10; done
fi
if ! ok "$BASE/v1/models"; then
  # (19/11, auditoria-runtime) O ALERTA antigo era uma linha sem causa: a
  # unit pode falhar por VRAM insuficiente (ExecStartPre=llama-vram-guard),
  # por porta ocupada (um server orfao de medicao), por OOM ou por o proprio
  # start script — e o bench esperava 300 s no escuro antes de desistir.
  # Agora o diagnostico real (status + journal + VRAM) vai para o ALERTA e
  # para o stderr, que e' onde a triagem comeca.
  diag=$( {
    echo "--- systemctl status"
    systemctl status "$DEFAULT_UNIT" --no-pager -n 5 2>&1 | sed 's/^/  /'
    echo "--- journal (ultimas 12 linhas)"
    journalctl -u "$DEFAULT_UNIT" -n 12 --no-pager 2>&1 | sed 's/^/  /'
    echo "--- VRAM livre"
    nvidia-smi --query-gpu=memory.free,memory.total --format=csv,noheader 2>&1 | sed 's/^/  /'
    echo "--- quem ocupa a porta do default"
    base_port="${BASE##*:}"
    ss -ltnp 2>/dev/null | grep -F ":$base_port" | sed 's/^/  /'
  } 2>&1 )
  {
    echo "# ALERTA $(date): default $BASE não subiu após $DEFAULT_UNIT"
    echo
    echo "$diag"
  } > "$ALERTA"
  echo "[bench] default $BASE NÃO subiu — diagnóstico completo em $ALERTA" >&2
  echo "$diag" >&2
  exit 1
fi

# 1b) QUEM responde na porta do default? (19/11, auditoria-runtime)
# O health check acima só prova que ALGO responde na porta. Medido em 19/11: um
# server de MEDICAÇÃO ficou vivo na :8092 (orphão de script, sem unit) com o
# adapter v1 (81 MB) em vez do v9 (2,9 MB) do registry — o bench passaria
#batendo no health check e mediria o adapter ERRADO. O gate agora compara o
# PID que escuta a porta com o MainPID da unit DECLARADA: se não for o mesmo
# (ou se a unit nem está com MainPID, isto é, ela está caída), quem está no
# lugar do default é um shadow e a medição é inválida.
PORTA_DEFAULT="$(reg_port "$MODEL" 2>/dev/null || echo 8092)"
main_pid="$(systemctl show -p MainPID --value "$DEFAULT_UNIT" 2>/dev/null || echo 0)"
listen_pid="$(ss -ltnpH 2>/dev/null | grep -F ":$PORTA_DEFAULT " | grep -o 'pid=[0-9]*' | head -1 | cut -d= -f2)"
if [ -n "$listen_pid" ] && { [ "${main_pid:-0}" = "0" ] || [ "$listen_pid" != "$main_pid" ]; }; then
  shadow_cmd="$(tr '\0' ' ' < "/proc/$listen_pid/cmdline" 2>/dev/null | cut -c1-400)"
  {
    echo "# ALERTA $(date): a porta do default ($PORTA_DEFAULT) é servida por um SHADOW"
    echo
    echo "- unit declarada: $DEFAULT_UNIT (MainPID=$main_pid, ativo=$(systemctl is-active "$DEFAULT_UNIT" 2>/dev/null))"
    echo "- quem escuta: pid=$listen_pid"
    echo "- cmdline: $shadow_cmd"
    echo
    echo "A medição seria feita contra um processo que não é a unit do registry."
    echo "Um server órfão de medição foi a causa medida em 19/11 (adapter v1 no lugar do v9)."
  } > "$ALERTA"
  echo "[bench] SHADOW na porta $PORTA_DEFAULT (pid $listen_pid) ≠ unit $DEFAULT_UNIT (pid $main_pid) — medição abortada, diagnóstico em $ALERTA" >&2
  exit 1
fi

# 2) router fora (medida limpa), somente se a unit existir
if [ "$CHECK_ONLY" -eq 1 ]; then
  if ! verify_endpoints; then
    exit 1
  fi
  echo "[bench] check-only OK: default $BASE; router $ROUTER_UNIT load=$ROUTER_LOAD_STATE managed=$ROUTER_MANAGED"
  exit 0
fi
if [ "$ROUTER_MANAGED" -eq 1 ]; then
  if ! sudo -n systemctl stop "$ROUTER_UNIT"; then
    echo "# ALERTA $(date): nao foi possivel parar o router $ROUTER_UNIT antes do bench" > "$ALERTA"
    exit 1
  fi
  sleep 5
else
  echo "[bench] router $ROUTER_UNIT ausente na topologia atual; medicao default-only"
fi

# 3) bench + probe MBTI
/home/nixos/projects/nixos-ai/benchmarks/model-tiers/bench.py \
  --endpoint "$BASE" --model "$MODEL" --tag qwen4bmtp-lora \
  > /tmp/opencode/bench-qwen.log 2>&1
# MBTI probe no qwen (owner 08/10): mesma decision task do teste bonsai,
# INTP vs sem tag, 2 runs cada, temp 0.7. Resultado em results/mbti-qwen.json.
/home/nixos/projects/karaok/.venv/bin/python - "$BASE" "$MODEL" << 'EOF' > /home/nixos/projects/nixos-ai/benchmarks/model-tiers/results/mbti-qwen.json 2>/tmp/opencode/mbti-qwen.err || echo '{"error": "probe falhou, ver mbti-qwen.err"}' > /home/nixos/projects/nixos-ai/benchmarks/model-tiers/results/mbti-qwen.json
import json, sys, urllib.request
endpoint, model = sys.argv[1], sys.argv[2]
T = "A test suite shows 408 pass, 1 fail (species count). Release tonight? Start with YES or NO, then 2 lines why."
def call(sysp):
    data = json.dumps({"model": model, "messages": [{"role": "system", "content": sysp}, {"role": "user", "content": T}], "max_tokens": 150, "temperature": 0.7}).encode()
    r = json.load(urllib.request.urlopen(urllib.request.Request(endpoint + "/v1/chat/completions", data=data, headers={"Content-Type": "application/json"}), timeout=300))
    return r["choices"][0]["message"]["content"]
BASE = "You are a technical researcher. Max 4 lines."
out = {"task": T, "runs": []}
for cond, tag in ((BASE, "none"), (BASE + " You are INTP.", "INTP")):
    for i in (1, 2):
        out["runs"].append({"cond": tag, "out": call(cond)})
print(json.dumps(out, ensure_ascii=False, indent=0))
EOF

# 4) router de volta (se existia) + verificação final
if [ "$ROUTER_MANAGED" -eq 1 ]; then
  if ! sudo -n systemctl start "$ROUTER_UNIT"; then
    echo "# ALERTA $(date): nao foi possivel religar o router $ROUTER_UNIT apos o bench" > "$ALERTA"
    exit 1
  fi
  sleep 20
fi
if ! verify_endpoints; then
  exit 1
fi
if [ "$ROUTER_MANAGED" -eq 1 ]; then
  echo "[bench] default $BASE OK + router $ROUTER_BASE OK; resultados em benchmarks/model-tiers/results/qwen4bmtp-lora.json"
else
  echo "[bench] default $BASE OK; router $ROUTER_UNIT ausente por topologia; resultados em benchmarks/model-tiers/results/qwen4bmtp-lora.json"
fi
