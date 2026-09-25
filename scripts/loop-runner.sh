#!/usr/bin/env bash
# loop-runner.sh — executor do LOOP-v2 (o agente raciocina; isto executa).
#
# Uso:  nohup ./scripts/loop-runner.sh <ciclos> <modelo> [tier] [rounds]
#   modelo: bonsai | fast | strong | moe
#   tier:   all | easy | medium | hard | ptbr   (default: all)
#
# O que este runner faz por ciclo (mecânico, sem Julgamento):
#   1. preflight do LLM (se não estiver no ar, REGISTRA e pula — nunca
#      mede com infra caída; nunca briga por VRAM)
#   2. roda o harness no modelo pedido e grava JSON datado
#   3. roda o probe de prompt (full/lean/minimal) no mesmo modelo
#   4. roda o probe de factual (CRPS) e de repetição (temp 0 vs 0.7)
#   5. anexa um resumo ao log e marca o estado
#
# O que o runner NÃO faz (proibido por design):
#   - não muda serviço, não rebuild, não muda rota/default
#   - não faz push (só commit local quando o agente mandar)
#   - não purga o code_index (604 pts pessoais) — só depois da perícia
#   - não sobe 2 LLMs: se a VRAM está ocupada, registra e espera
set -uo pipefail

NIXAI=/home/nixos/projects/nixos-ai
OUT_DIR="$NIXAI/scripts/overnight-24-09"
LOG=/tmp/overnight/loop-runner.log
STATE="$OUT_DIR/loop-STATE.md"
mkdir -p /tmp/overnight "$OUT_DIR"
CYCLES="${1:-6}"
MODEL="${2:-bonsai}"
TIER="${3:-all}"
ROUNDS="${4:-2}"
TS() { date +%Y%m%d-%H%M%S; }

log() { echo "[$(date +%H:%M:%S)] $*" | tee -a "$LOG"; }

endpoint_for() {
  case "$1" in
    bonsai) echo "http://127.0.0.1:8080/v1|bonsai" ;;
    fast)   echo "http://127.0.0.1:8083/v1|jarvis-fast" ;;
    strong) echo "http://127.0.0.1:8084/v1|jarvis-strong" ;;
    moe)    echo "http://127.0.0.1:8092/v1|qwen35-uncensored" ;;
    *) echo "" ;;
  esac
}

vram_busy() {  # >1 LLM na GPU?
  nvidia-smi --query-compute-apps=used_memory --format=csv,noheader,nounits 2>/dev/null \
    | awk '$1>1200' | grep -q .
}

for c in $(seq 1 "$CYCLES"); do
  log "=== ciclo $c/$CYCLES · modelo=$MODEL tier=$TIER rounds=$ROUNDS"
  IFS='|' read -r BASE MID <<< "$(endpoint_for "$MODEL")"
  if [ -z "$BASE" ]; then log "modelo desconhecido: $MODEL — pulando"; break; fi

  # 1) preflight: completion real (não só /health)
  if ! curl -sf --max-time 20 "$BASE/chat/completions" \
        -H 'Content-Type: application/json' \
        -d "{\"model\":\"$MID\",\"max_tokens\":4,\"chat_template_kwargs\":{\"enable_thinking\":false},\"messages\":[{\"role\":\"user\",\"content\":\"ok\"}]}" \
        -o /dev/null 2>/dev/null; then
    log "preflight FALHOU em $BASE (infra, não é resultado)"
    if vram_busy; then
      log "VRAM ocupada por outro LLM: esperando o ciclo seguinte"
      sleep 120; continue
    fi
    # sem VRAM ocupada e o modelo pedido fora = caiu sozinho (OOM?):
    # aproveita a noite e mede o router, que é o braço de referência.
    if [ "$MODEL" != "bonsai" ] && curl -sf --max-time 8 \
         http://127.0.0.1:8080/chat/completions \
         -H 'Content-Type: application/json' \
         -d '{"model":"bonsai","max_tokens":4,"chat_template_kwargs":{"enable_thinking":false},"messages":[{"role":"user","content":"ok"}]}' \
         -o /dev/null 2>/dev/null; then
      log "fallback: medindo o router (bonsai) neste ciclo"
      BASE="http://127.0.0.1:8080/v1"; MID="bonsai"; MODEL="bonsai"
    else
      log "nada medível agora (VRAM ocupada e modelo fora) — dormindo 120s"
      sleep 120; continue
    fi
  fi

  STAMP=$(TS)
  # 1b) o REPL/harness TEM de rodar dentro do env do SPACE: sem isso a
  # persona (uncensored) e o thinking-off não chegam, e o resultado é
  # inválido (25/09: 6/12 era o MoE SEM framing e COM thinking).
  SPACE_ENV=""
  case "$MODEL" in
    moe) SPACE_ENV="JARVIS_PERSONA=uncensored JARVIS_LLM_DISABLE_THINKING=1" ;;
    qwen4b) SPACE_ENV="JARVIS_PERSONA=uncensored JARVIS_LLM_DISABLE_THINKING=1" ;;
  esac
  # 2) harness
  log "harness…${SPACE_ENV:+ (env do space)}"
  (cd "$NIXAI" && nix develop --command bash -c \
    "cd $NIXAI && $SPACE_ENV JARVIS_LLM_BASE_URL=$BASE JARVIS_LLM_MODEL=$MID \
     python3 scripts/harness-suite.py --tier $TIER --rounds $ROUNDS \
     --out /tmp/overnight/loop-$MODEL-$STAMP.json" 2>&1) \
    | grep -E "world_ok|TOTAL|PREFLIGHT" | tee -a "$LOG"
  cp -f "/tmp/overnight/loop-$MODEL-$STAMP.json" "$OUT_DIR/" 2>/dev/null || true

  # 3) prompt profile A/B (mesmo modelo, 3 prompts) — só mede, não decide
  for P in full lean minimal; do
    (cd "$NIXAI" && nix develop --command bash -c \
      "cd $NIXAI && JARVIS_PROMPT_PROFILE=$P JARVIS_LLM_BASE_URL=$BASE \
       JARVIS_LLM_MODEL=$MID python3 scripts/harness-suite.py --tier easy --rounds 1 \
       --out /tmp/overnight/loop-$MODEL-$STAMP-p$P.json" 2>&1) \
      | grep -E "TOTAL|PREFLIGHT" | sed "s/^/  prompt=$P /" | tee -a "$LOG"
    cp -f "/tmp/overnight/loop-$MODEL-$STAMP-p$P.json" "$OUT_DIR/" 2>/dev/null || true
  done

  # 4) probe factual + repetição (rápido, sem harness)
  (cd "$NIXAI" && nix develop --command python3 - "$BASE" "$MID" "$STAMP" <<'PY' 2>&1) | tee -a "$LOG"
import json, sys, urllib.request, urllib.error
base, mid, stamp = sys.argv[1], sys.argv[2], sys.argv[3]
def ask(msg, temp, think=False, mt=160):
    b = {"model": mid, "max_tokens": mt, "temperature": temp,
         "messages": [{"role": "user", "content": msg}]}
    if not think:
        b["chat_template_kwargs"] = {"enable_thinking": False}
    r = urllib.request.Request(base.rstrip("/") + "/chat/completions",
                               data=json.dumps(b).encode(),
                               headers={"Content-Type": "application/json"})
    try:
        d = json.load(urllib.request.urlopen(r, timeout=300))
    except Exception as e:
        return f"ERRO {type(e).__name__}"
    m = d["choices"][0]["message"]
    return (m.get("content") or "") + " ||REASONING=" + str(len(m.get("reasoning_content") or ""))
out = {"stamp": stamp, "model": mid}
out["crps_think_off"] = ask("o que é CRPS?", 0.7)[:160]
out["crps_think_on"] = ask("o que é CRPS?", 1.0, think=True)[:160]
# 3 amostras por temperatura: distinct != total => está repetindo
# (25/09: media 1 amostra sempre dava 1 — probe mentia)
probe = "me dá 2 dicas de organização, lista curta."
for t in (0.0, 0.7):
    outs = [ask(probe, t) for _ in range(3)]
    uniq = len({o.split("||")[0].strip() for o in outs})
    out[f"distinct_{t}"] = f"{uniq}/3"
print("PROBE " + json.dumps(out, ensure_ascii=False)[:900])
PY

  if ! curl -sf --max-time 8 "$BASE/chat/completions" -H 'Content-Type: application/json' \
       -d "{\"model\":\"$MID\",\"max_tokens\":4,\"messages\":[{\"role\":\"user\",\"content\":\"ok\"}]}" \
       -o /dev/null 2>/dev/null; then
    log "AVISO: o modelo ficou indisponivel no fim do ciclo (provavel OOM: ~18GB de experts na CPU)"
    sudo dmesg 2>/dev/null | grep -i "Killed process" | tail -1 >> "$LOG" || true
  fi
  log "ciclo $c finalizado"
  # 5) estado
  {
    echo ""
    echo "## ciclo $c — $(date '+%Y-%m-%d %H:%M') · modelo=$MODEL"
    echo "- harness: /tmp/overnight/loop-$MODEL-$STAMP.json (evidência copiada em scripts/overnight-24-09/)"
    echo "- prompt A/B: loop-$MODEL-$STAMP-p{full,lean,minimal}.json"
  } >> "$STATE"
  sleep 60
done
log "LOOPRunner terminou ($CYCLES ciclos)"
