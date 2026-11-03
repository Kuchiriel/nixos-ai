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
  echo "# ALERTA $(date): default $BASE não subiu — ver journalctl -u $DEFAULT_UNIT" > "$ALERTA"
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
