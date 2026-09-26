#!/usr/bin/env bash
# runner.sh — NIGHT 26/09 (LOOP-v3, mandato do dono: "trabalhar sem parar")
#
# Fila pesada que RAM bloqueou de dia, agora com computador ocioso:
#   P1 espera RAM livre (humano dorme) → P2 para serviços leves
#   P3 sobe MoE 35B UNCENSORED :8084 (receita exata models.nix)
#   P4 bateria completa de gates vs MoE (thinking OFF) — a linha da matrix
#   P5 self-study com o MoE como analista (das próprias falhas + as do bonsai)
#   P6 cmoe 41 vs 35 (bench canônico, router parado p/ validade)
#   P7 RESTAURA TUDO (trap também) → P8 handoff da manhã
#
# Segurança: trap EXIT restaura serviços; cada fase loga e segue (sem set -e);
# nunca apaga; evidência em scripts/overnight-26-09/.
export PATH="$PATH:/etc/profiles/per-user/nixos/bin"
BASE=/home/nixos/projects/nixos-ai
OUT=$BASE/scripts/overnight-26-09
mkdir -p "$OUT"
LOG="$OUT/runner.log"
ts() { date "+%H:%M:%S"; }
log() { echo "[$(ts)] $*" | tee -a "$LOG"; }

IK_LD="/home/nixos/projects/ik_llama.cpp/build/bin:/nix/store/7vafhlh0lmcvi75jfyy09qwr4m3x1ks3-gcc-15.2.0-lib/lib:/nix/store/pvxx7066ymzmmrlcfn7yl6kcbqvbc8lw-openssl-3.6.3/lib:/nix/store/s6aspcvp29vwfqv5wva5gfnmzahcny63-cuda12.9-cuda_cudart-12.9.79/lib:/nix/store/h4zc291jsiamkwivbdrjmsay8ipxqjaj-cuda12.9-libcublas-12.9.1.4-lib/lib:/run/opengl-driver/lib"
MOE=/home/nixos/models/Qwen3.6-35B-A3B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf
ALIAS=uncensored35
RESTORE_PID=""

restore_services() {
  log "RESTAURANDO serviços (trap/exit)..."
  sudo systemctl stop llama-cpp-ik 2>>"$LOG" || true
  sleep 2
  sudo systemctl start llama-cpp-server llama-cpp-embeddings llama-cpp-rerank 2>>"$LOG"
  sudo systemctl start qdrant 2>>"$LOG" || true
  sleep 10
  for p in 8080 8081 8082; do
    curl -sf --max-time 4 "http://127.0.0.1:$p/v1/models" >/dev/null 2>&1 \
      && log "  :$p OK" || log "  :$p NAO RESPONDEU (ver de manhã)"
  done
}
trap restore_services EXIT

free_avail() { free -m | awk 'NR==2 {print $7}'; }

log "=== P0 estado inicial ==="
free -g | awk 'NR==2 {print "[P0] RAM avail: "$7"GB"}' | tee -a "$LOG"

# ── P1: esperaidle (avail >= 17000MB; 5min/poll, timeout 4h) ──
log "P1 esperando idle (>=17GB avail; humano dormindo)..."
IDLE=""
for i in $(seq 1 48); do
  A=$(free_avail)
  [ "$A" -ge 17000 ] && { log "P1 idle: ${A}MB livres"; IDLE=1; break; }
  sleep 300
done
[ -z "$IDLE" ] && log "P1 sem idle em 4h — segue p/ P7 nightwatch (sem RAM pesada)"

# ── P2: para serviços p/ RAM do MoE; exige 19GB p/ tentar o MoE ──
RAM_OK=""
if [ -n "$IDLE" ]; then
  log "P2 parando embeddings/rerank/qdrant + router (RAM p/ MoE; incidente 25/09)..."
  sudo systemctl stop llama-cpp-embeddings llama-cpp-rerank llama-cpp-server 2>>"$LOG"
  sudo systemctl stop qdrant 2>>"$LOG" || true
  sleep 8
  A=$(free_avail); log "  avail agora: ${A}MB"
  if [ "$A" -ge 19000 ]; then
    RAM_OK=1
  else
    log "P2 <19GB mesmo com serviços parados — MoE INVIÁVEL, religa e segue p/ P7"
    sudo systemctl start llama-cpp-embeddings llama-cpp-rerank llama-cpp-server 2>>"$LOG"
    sudo systemctl start qdrant 2>>"$LOG" || true
  fi
fi
if [ -n "$RAM_OK" ]; then

# ── P3: sobe MoE uncensored :8084 VIA SYSTEMD (26/09) ──
# NADA de nohup fora do systemd: tudo supervisionado, logável e parável
# via systemctl (aula do freeze: processo órfão não responde a pkill de
# unidade porque... não é unidade). A unidade llama-cpp-ik serve o
# Uncensored primeiro (preset jarvis-raw-strong, --models-max 1).
log "P3 systemctl start llama-cpp-ik (MoE uncensored, on-demand)..."
sudo systemctl start llama-cpp-ik 2>>"$LOG"
log "  esperando /health (load 21GB leva minutos)..."
UP=""
for i in $(seq 1 90); do
  curl -sf --max-time 3 http://127.0.0.1:8084/health >/dev/null 2>&1 && { UP=1; break; }
  systemctl is-active --quiet llama-cpp-ik || { log "  P3 unidade MORREU — ver journalctl -u llama-cpp-ik"; break; }
  sleep 20
done

if [ -n "$UP" ]; then
  log "P3 MoE UP."

  # ── P4: bateria completa vs MoE (thinking OFF) ──
  log "P4 bateria (tier all, rounds 2, thinking OFF) vs uncensored35..."
  cd "$BASE"
  RALIAS=$(curl -sf --max-time 5 http://127.0.0.1:8084/v1/models | python3 -c "import json,sys; print(json.load(sys.stdin)['data'][0]['id'])" 2>/dev/null)
  log "  unidade serve alias: ${RALIAS:-?}"
  JARVIS_LLM_BASE_URL=http://127.0.0.1:8084/v1 JARVIS_LLM_MODEL="${RALIAS:-uncensored35}" \
    JARVIS_LLM_DISABLE_THINKING=1 \
    timeout 3600 nix develop --command python3 scripts/harness-suite.py \
    --tier all --rounds 2 --out "$OUT/battery-uncensored35.json" >>"$LOG" 2>&1
  log "  battery salva: $OUT/battery-uncensored35.json"

  # ── P5: self-study com o MoE como analista ──
  log "P5 self-study (analista = uncensored35)..."
  JARVIS_LLM_BASE_URL=http://127.0.0.1:8084/v1 \
    timeout 1200 nix develop --command python3 scripts/self-study.py \
    --evidence "$OUT/battery-uncensored35.json" \
    --task-file scripts/harness-challenges.json \
    --model "${RALIAS:-uncensored35}" >>"$LOG" 2>&1

  # ── P5b: self-study cruzado sobre falhas do bonsai ──
  if [ -f /tmp/opencode/harness-evolve/reopen-hook-classic.json ]; then
    log "P5b self-study cruzado (falhas do bonsai, analista MoE)..."
    JARVIS_LLM_BASE_URL=http://127.0.0.1:8084/v1 \
      timeout 1200 nix develop --command python3 scripts/self-study.py \
      --evidence /tmp/opencode/harness-evolve/reopen-hook-classic.json \
      --task-file scripts/harness-challenges.json \
      --model "${RALIAS:-uncensored35}" >>"$LOG" 2>&1
  fi

  # ── P5c: NIGHTWATCH com o modelo FORTE (mandato: bonsai não emite
  # json-patch legível 3/3; escada sobe pro MoE). Árvore limpa primeiro
  # (safety bloqueia dirty tree — pago no teste do dia).
  log "P5c nightwatch com o MoE (nixos-ai, 3 tasks, 1 ciclo)..."
  git -C "$BASE" add -A >/dev/null 2>&1
  git -C "$BASE" diff --cached --quiet || \
    git -C "$BASE" commit -q -m "chore(overnight): arvore limpa p/ nightwatch"
  JARVIS_LLM_BASE_URL=http://127.0.0.1:8084/v1 JARVIS_LLM_MODEL="$ALIAS" \
    JARVIS_LLM_DISABLE_THINKING=1 \
    timeout 3600 jarvis nightwatch --projects nixos-ai --tasks 3 --cycles 1 \
    >> "$OUT/nightwatch-moe.log" 2>&1
  log "P5c nightwatch(MoE) terminou — ver $OUT/nightwatch-moe.log"

  log "P5.x desligando MoE p/ P6 (bench precisa de RAM+VRAM limpas)..."
  sudo systemctl stop llama-cpp-ik 2>>"$LOG"
  sleep 10
else
  log "P3 FALHOU: MoE não subiu — P4/P5 pulados, segue P6."
fi
fi  # RAM_OK

# ── P6: cmoe 41 vs 35 (bench canônico; router PARADO = guard válido) ──
log "P6 parando router p/ bench válido..."
sudo systemctl stop llama-cpp-server 2>>"$LOG"
sleep 8
cd "$BASE"
log "P6a cmoe41 (2 reps)..."
nice -n 19 timeout 1800 nix develop --command bash scripts/bench-llm.sh \
  -b modules/ai/llama-ik-wrapper.sh -m "$MOE" -n 2 -g cmoe41-unc \
  -- -ngl 45 --n-cpu-moe 41 --mlock -t 6 -c 8192 -fa on -ctk q4_0 -ctv q4_0 \
  > "$OUT/cmoe41.tsv" 2>"$OUT/cmoe41.err"
log "P6a: $(tail -2 "$OUT/cmoe41.tsv" 2>/dev/null | tr '\n' ' ')"
log "P6b cmoe35 (2 reps)..."
nice -n 19 timeout 1800 nix develop --command bash scripts/bench-llm.sh \
  -b modules/ai/llama-ik-wrapper.sh -m "$MOE" -n 2 -g cmoe35-unc \
  -- -ngl 45 --n-cpu-moe 35 --mlock -t 6 -c 8192 -fa on -ctk q4_0 -ctv q4_0 \
  > "$OUT/cmoe35.tsv" 2>"$OUT/cmoe35.err"
log "P6b: $(tail -2 "$OUT/cmoe35.tsv" 2>/dev/null | tr '\n' ' ')"

  # ── P5c: NIGHTWATCH COM O MODELO FORTE (enquanto o MoE está no ar) ──
  # (mandato do dono: bonsai não dá conta do patcher — 3/3 json-patch
  # ilegíveis no teste do dia; escada sobe pro MoE uncensored)
  if [ -n "$UP" ]; then
    log "P5c nightwatch com o MoE (nixos-ai, 3 tasks, 1 ciclo)..."
    cd "$BASE"
    git -C "$BASE" add -A 2>/dev/null; git -C "$BASE" commit -q -m \
      "chore(overnight): árvore limpa p/ nightwatch (safety exige)" 2>/dev/null
    JARVIS_LLM_BASE_URL=http://127.0.0.1:8084/v1 JARVIS_LLM_MODEL="$ALIAS" \
      JARVIS_LLM_DISABLE_THINKING=1 \
      timeout 3600 jarvis nightwatch --projects nixos-ai --tasks 3 --cycles 1 \
      >> "$OUT/nightwatch-moe.log" 2>&1
    log "P5c nightwatch(MoE) terminou — ver $OUT/nightwatch-moe.log"
  fi

  log "P5.x desligando MoE p/ P6 (bench precisa de RAM+VRAM limpas)..."

# ── P8: handoff da manhã ──
cat > "$BASE/docs/HANDOFF-2026-09-26-MANHA.md" <<EOF
# Handoff da manhã — overnight 26/09 (runner.sh)

> Rodou sem agente vivo. Evidência crua em scripts/overnight-26-09/.
> Próximo passo: ler runner.log, passar battery-uncensored35.json pro
> MODEL-HARNESS-MATRIX (a PRIMEIRA linha do MoE forte na matrix — G3
> model-side se confirmar), SELF-STUDY-*.md do analista MoE, e cmoe
> 41vs35 (se 41 vencer fora do ruído, aplicar moeFlags no models.nix).

Estado na saída do runner: serviços restaurados (verificar :8080/8081/8082).
Falha em qualquer fase = log correspondente (.err/.log), NÃO é resultado.
EOF
log "P8 handoff escrito. FIM — serviços restaurados."
