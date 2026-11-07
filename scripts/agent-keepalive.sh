#!/usr/bin/env bash
# =====================================================================
#  agent-keepalive.sh - o guard do BUS (nenhum agente morre sozinho)
#  ---------------------------------------------------------------------
#  POR QUE (07/11/2026, dono): "ela criou um heartbeat mas nao sei se foi
#  so pra ela ou todo mundo - pra todas as IAs nunca pararem, a menos q
#  humano precise fazer algo".
#
#  O QUE ISTO FAZ (e o que NAO faz):
#    - LE o bus (a issue #12 do GitHub, label coord) e ve quais lanes
#      anunciaram claim viva;
#    - se uma lane tem CLAIM VIVA mas nao produz nada ha muito tempo
#      (claim sem mensagem, sem commit, sem tool call), manda uma msg
#      de "reemerge" pro bus daquela lane;
#    - NAO acorda o dono, NAO abre janela, NAO escreve no input do
#      humano (a regra do AGENTS.md: nunca wtype/focus no input dele);
#    - NAO roda turno de ninguem sem o bus pedir: a msg é um NOTE
#      (o watcher da outra ponta decide se roda).
#
#  O QUE ISTO NAO FAZ (deliberado):
#    - nao é o agents-watcher.sh (que é o acordar de agentes de projeto
#      e foi desligado pelo dono em 07/11 pra nao incomodar). Este aqui
#      só existe para o BUS: se um agente de coord parou, ele volta.
#
#  USO:
#    ./agent-keepalive.sh            # roda uma vez (verifica e reemite)
#    ./agent-keepalive.sh --status   # só mostra o estado, não emite nada
#
#  EXEMPLO:
#    systemd --user timer: a cada 15 min chama este script; ele detecta
#    a lane parada e publica a msg de reemerge no bus.
# =====================================================================
set -uo pipefail

# ── config (ambiente; sem path hardcoded) ─────────────────────────────
MT5_REPO="${MT5_REPO:-$HOME/projects/mt5}"
BUS_REPO="${BUS_REPO:-$MT5_REPO/.worktrees/infra-coord}"
STALE_MIN="${STALE_MIN:-45}"      # claim viva sem sinal por N min = parada
STATUS=0

[[ "${1:-}" == "--status" ]] && STATUS=1

command -v gh >/dev/null || { echo "keepalive: sem gh" >&2; exit 2; }
[[ -d "$BUS_REPO" ]] || { echo "keepalive: bus repo nao encontrado: $BUS_REPO" >&2; exit 2; }

# ── 1. as claims vivas do roster local ───────────────────────────────
ROSTER="$HOME/projects/.agents/roster.json"
[[ -f "$ROSTER" ]] || { echo "keepalive: roster ausente: $ROSTER" >&2; exit 2; }

now=$(date +%s)
declare -A LANE_LAST CLAIM_LANE
while IFS=$'\t' read -r name lane claimed; do
  [[ -z "$lane" ]] && continue
  LANE_LAST["$lane"]="${LANE_LAST[$lane]:-0}"
  CLAIM_LANE["$name"]="$lane"
done < <(python3 - "$ROSTER" <<'PY'
import json, sys
d = json.load(open(sys.argv[1]))
for e in d.get("agents", []):
    print(f"{e.get('name','')}\t{e.get('lane','')}\t{e.get('claimed_at',0)}")
PY
)

# ── 2. a última atividade por lane (do bus: msg/commit/ts) ───────────
bus_json=$(cd "$BUS_REPO" && gh issue view 12 --json comments --jq '.comments[].body' 2>/dev/null || true)
while IFS=$'\t' read -r ts lane; do
  [[ -z "$lane" ]] && continue
  ep=$(date -d "$ts" +%s 2>/dev/null || echo 0)
  [[ "$ep" -gt "${LANE_LAST[$lane]:-0}" ]] && LANE_LAST["$lane"]="$ep"
done < <(printf '%s\n' "$bus_json" | python3 - <<'PY'
import json, re, sys
for body in sys.stdin.read().split("```coord-json"):
    m = re.search(r"\{.*\}", body, re.S)
    if not m:
        continue
    try:
        p = json.loads(m.group(0))
    except Exception:
        continue
    if p.get("ts") and p.get("lane"):
        print(f"{p['ts']}\t{p['lane']}")
PY
)

# ── 3. lanes claims vivas sem sinal → reemerge ───────────────────────
stale_s=0
stale_s=$((STALE_MIN * 60))
emitted=0
for lane in "${!LANE_LAST[@]}"; do
  [[ -z "$lane" ]] && continue
  last="${LANE_LAST[$lane]}"
  age=$((now - last))
  (( age < stale_s )) && continue
  if (( STATUS == 1 )); then
    printf "PARADA  %-42s %4d min sem sinal\n" "$lane" $((age / 60))
  else
    cd "$BUS_REPO" || continue
    node tools/coord.mjs post --kind status --agent opencode-matheus --lane "$lane" \
      --intent "reemerge: a lane '$lane' tem claim viva ha ${age}s sem sinal no bus" \
      --note "GUARD DO BUS (agent-keepalive.sh): a lane '${lane}' tem claim viva no roster mas nao produz nada no bus ha $((age / 60)) min (limite: ${STALE_MIN} min). Se voce esta vivo: poste seu status no bus (coord.mjs post --kind status) e siga a tarefa. Se voce morreu: o turno precisa ser retomado por quem coordena - e o wake e' pelo watcher da outra ponta (nota no bus, sem digitar no input do humano). Esta mensagem NAO exige acao do dono." >/dev/null 2>&1 \
      && emitted=$((emitted + 1)) && echo "keepalive: lane parada detectada: $lane (${age}s) - msg de reemerge publicada"
  fi
done

(( STATUS == 1 )) && exit 0
echo "keepalive: $emitted msg(s) de reemerge emitida(s)"
exit 0
