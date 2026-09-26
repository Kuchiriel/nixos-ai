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
  [ -n "$RESTORE_PID" ] && kill "$RESTORE_PID" 2>/dev/null
  sleep 2
  sudo systemctl start llama-cpp-server llama-cpp-embeddings llama-cpp-rerank 2>>"$LOG"
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

# ── P1: espera idle (avail >= 22000MB) — timeout 5h ──
log "P1 esperando idle (>=22GB avail; humano dormindo)..."
for i in $(seq 1 60); do
  A=$(free_avail)
  [ "$A" -ge 22000 ] && { log "P1 idle: ${A}MB livres"; break; }
  [ $i -eq 60 ] && { log "P1 TIMEOUT 5h sem idle — PULA bateria MoE (sem RAM não há veredito válido)"; exit 0; }
  sleep 300
done

# ── P2: para serviços p/ RAM do MoE (incidente 25/09 documentado) ──
log "P2 parando embeddings/rerank (RAM p/ MoE)..."
sudo systemctl stop llama-cpp-embeddings llama-cpp-rerank 2>>"$LOG"
sleep 5
A=$(free_avail); log "  avail agora: ${A}MB"

# ── P3: sobe MoE uncensored :8084 ──
log "P3 subindo MoE uncensored :8084 (receita models.nix)..."
LD_LIBRARY_PATH="$IK_LD" nohup /home/nixos/projects/ik_llama.cpp/build/bin/llama-server \
  -m "$MOE" --host 127.0.0.1 --port 8084 --jinja --alias "$ALIAS" \
  -ngl 45 --n-cpu-moe 35 --mlock -t 6 -c 8192 -fa on \
  -ctk q4_0 -ctv q4_0 -b 512 -ub 512 --parallel 1 \
  > "$OUT/moe-server.log" 2>&1 &
RESTORE_PID=$!
log "  PID $RESTORE_PID — esperando /health (load 21GB leva minutos)..."
UP=""
for i in $(seq 1 90); do
  curl -sf --max-time 3 http://127.0.0.1:8084/health >/dev/null 2>&1 && { UP=1; break; }
  kill -0 "$RESTORE_PID" 2>/dev/null || { log "  P3 server MORREU — ver moe-server.log"; break; }
  sleep 20
done
if [ -z "$UP" ]; then
  log "P3 FALHOU: MoE não subiu. Pula P4-P5, segue P6 com router parado."
else
  log "P3 MoE UP."

  # ── P4: bateria completa vs MoE (thinking OFF) ──
  log "P4 bateria (tier all, rounds 2, thinking OFF) vs uncensored35..."
  cd "$BASE"
  JARVIS_LLM_BASE_URL=http://127.0.0.1:8084/v1 JARVIS_LLM_MODEL="$ALIAS" \
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
    --model "$ALIAS" >>"$LOG" 2>&1
  log "  self-study salvo em docs/benchmarks/SELF-STUDY-*.md (do MoE)"

  # ── P5b: self-study do MoE sobre as falhas do bonsai (analista cruzado) ──
  if [ -f /tmp/opencode/harness-evolve/reopen-hook-classic.json ]; then
    log "P5b self-study cruzado (falhas do bonsai, analista MoE)..."
    JARVIS_LLM_BASE_URL=http://127.0.0.1:8084/v1 \
      timeout 1200 nix develop --command python3 scripts/self-study.py \
      --evidence /tmp/opencode/harness-evolve/reopen-hook-classic.json \
      --task-file scripts/harness-challenges.json \
      --model "$ALIAS" >>"$LOG" 2>&1
  fi

  log "P5.x desligando MoE p/ P6 (bench precisa de RAM+VRAM limpas)..."
  kill "$RESTORE_PID" 2>/dev/null; RESTORE_PID=""
  sleep 10
fi

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

# ── P7: restaura (trap faria, mas log explícito) ──
restore_services

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
