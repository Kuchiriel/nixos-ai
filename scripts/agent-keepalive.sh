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
# MEDIDO 07/11: dois bugs deixavam o guard INOPERANTE — (1) o ts do bus
# vem em ISO com MILISSEGUNDOS e "Z" (o `date -d` falhava -> epoch 0 ->
# toda lane parecia parada ha 58 anos); (2) o regex guloso pegava do
# primeiro { ao ultimo } do bloco -> so o ULTIMO payload era lido.
# Agora: o epoch sai direto do python e o regex nao-guloso pega 1 a 1.
bus_json=$(cd "$BUS_REPO" && gh issue view 12 --json comments --jq '.comments[].body' 2>/dev/null || true)
while IFS=$'\t' read -r ep lane; do
  [[ -z "$lane" || "$ep" == "0" ]] && continue
  [[ "$ep" -gt "${LANE_LAST[$lane]:-0}" ]] && LANE_LAST["$lane"]="$ep"
done < <(printf '%s\n' "$bus_json" | python3 - <<'PYEOF_BUS'
import calendar, json, re, sys, time
for body in sys.stdin.read().split("```coord-json"):
    m = re.search(r"\{[^{}]*\}", body, re.S)
    if not m:
        continue
    try:
        p = json.loads(m.group(0))
    except Exception:
        continue
    ts, lane = p.get("ts"), p.get("lane")
    if not ts or not lane:
        continue
    try:
        ep = calendar.timegm(time.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        continue
    print(f"{ep}\t{lane}")
PYEOF_BUS
)

# ── 3. lanes claims vivas sem sinal → reemerge ───────────────────────
# MEDIDO 07/11: o join por LANE nao funcionava — o bus anuncia lanes
# diferentes das do roster ("infra"/"matheus" no bus vs "mt5-infra"/
# "nixos-ai/..." no roster) => TODA lane parecia parada ha 58 anos e o
# guard ia spammar "reemerge" em todas. O join correto e por AGENTE
# (nome + codinome + aliases declarados no roster) — o mesmo mapa que o
# quadro (jarvis/core/comms.py) usa. Aqui o python faz o join e devolve
# as lanes REALmente paradas.
stale_s=0
stale_s=$((STALE_MIN * 60))
emitted=0
bus_tmp=$(mktemp)
printf '%s\n' "$bus_json" > "$bus_tmp"
while IFS=$'\t' read -r lane last; do
  [[ -z "$lane" || "$last" == "0" ]] && continue
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
done < <(python3 - "$ROSTER" "$now" "$bus_tmp" <<'PYEOF_JOIN'
import calendar, json, re, sys, time

roster_path, now, bus_path = sys.argv[1], int(sys.argv[2]), sys.argv[3]
try:
    roster = json.load(open(roster_path)).get("agents", [])
except Exception:
    roster = []

# alias -> lane (o bus anuncia por QUALQUER alias do roster)
alias_lane = {}
for e in roster:
    lane = e.get("lane") or ""
    if not lane:
        continue
    for key in [e.get("name"), e.get("codename")] + list(e.get("aliases") or []):
        if key:
            alias_lane.setdefault(str(key), lane)

# ultimo sinal por lane (ts do bus, por AGENTE)
last = {}
for body in open(bus_path, encoding="utf-8", errors="ignore").read().split("```coord-json"):
    m = re.search(r"\{[^{}]*\}", body, re.S)
    if not m:
        continue
    try:
        p = json.loads(m.group(0))
    except Exception:
        continue
    agent = str(p.get("agent") or "")
    ts = p.get("ts")
    if not agent or not ts:
        continue
    lane = alias_lane.get(agent)
    if not lane:
        continue
    try:
        ep = calendar.timegm(time.strptime(str(ts)[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        continue
    if ep > last.get(lane, 0):
        last[lane] = ep

for lane in sorted({e.get("lane") for e in roster if e.get("lane")}):
    print(f"{lane}\t{last.get(lane, 0)}")
PYEOF_JOIN
)

rm -f "$bus_tmp"
(( STATUS == 1 )) && exit 0
echo "keepalive: $emitted msg(s) de reemerge emitida(s)"
exit 0
