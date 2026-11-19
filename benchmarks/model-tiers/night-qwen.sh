#!/usr/bin/env bash
# bench noturno do DEFAULT (4B-MTP+LoRA, :8092). 04:00.
#
# TOPOLOGIA NOVA (02/11): :8092 = DEFAULT do sistema (fica DE PÉ, sobe no
# boot com o LoRA registrado); :8080 = router VAZIO (bonsai on-demand).
# O bench antigo parava o :8092 no fim e religava o router — isso deixaria
# a máquina SEM default e devolveria o bonsai ao comando. Agora:
#   1) garante o default de pé (:8092)
#   2) para o router (libera a VRAM p/ medir limpo: 1 llama-server com
#      modelo, sem contenção — regra da casa)
#   3) mede o :8092 já residente
#   4) religa o router (vazio) e VERIFICA default + router
set -u
ALERTA=/home/nixos/projects/team/ALERTA-bench.md
# (03/11) Fonte única: o registry vem do Nix (models.nix). O default, a
# porta, a unit e a porta do router saem de lá — nada de literal aqui.
# shellcheck source=/home/nixos/projects/nixos-ai/scripts/jarvis-registry.sh
. /home/nixos/projects/nixos-ai/scripts/jarvis-registry.sh
MODEL="$(reg_default)"
BASE="$(reg_endpoint "$MODEL")"
DEFAULT_UNIT="$(reg_unit "$MODEL")"
ROUTER_BASE="$(reg_endpoint bonsai)"
ok() { curl -s --max-time 15 "$1" >/dev/null 2>&1; }

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
    ss -ltnp 2>/dev/null | grep -F ":$(echo "$BASE" | sed 's#.*:##')" | sed 's/^/  /'
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

# 2) router fora (medida limpa)
sudo -n systemctl stop llama-cpp-server
sleep 5

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

# 4) router de volta (vazio) + verificação final
sudo -n systemctl start llama-cpp-server
sleep 20
if ! ok "$BASE/v1/models"; then
  echo "# ALERTA $(date): default $BASE NÃO respondeu após o bench — ver journalctl -u $DEFAULT_UNIT" > "$ALERTA"
  exit 1
fi
if ! ok "$ROUTER_BASE/v1/models"; then
  echo "# ALERTA $(date): router $ROUTER_BASE NÃO voltou após bench — ver journalctl -u llama-cpp-server" > "$ALERTA"
  exit 1
fi
echo "[bench] default $BASE OK + router $ROUTER_BASE OK; resultados em benchmarks/model-tiers/results/qwen4bmtp-lora.json"
