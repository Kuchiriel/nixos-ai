#!/usr/bin/env bash
# llama-swap.sh — troca o modelo LOCAL RESIDENTE em idle (hot-swap da casa).
#
# POR QUE (15/11, medido): a VRAM da casa tem 6 GB (RTX 4050). Medido:
#   6141 MiB total · 5276 usados · **578 MiB livres**
# O Qwen3.5-4B-MTP (:8092) segura **3.874 MiB**; o Bonsai (8B ternario,
# 2,3 GB) nao cabe junto -> o router (:8080) tenta spawnar o llama-server e
# devolve **500** em toda /v1/chat/completions. Sem troca de residente so
# existe UM modelo local utilizavel por vez.
#
# MEDIDO (na casa, 15/11):
#   :8092 MTP  = llama-server -m /var/lib/ai/models/Qwen3.5-4B-MTP-Q4_K_M.gguf
#                --port 8092 -ngl 99 -t 6 -c 12288 --alias jarvis-mtp-lora
#                --spec-type draft-mtp --lora .../microturn-4b-lora-v9.gguf
#   :8080      = router prism (spawna sob demanda; nao segura VRAM)
#   :8081      = embeddings (nomic, 446 MiB)
#   :8097      = whisper-server (STT, 934 MiB)
#
# (19/11) DONO UNICO: os perfis do 4B-MTP sao units do systemd
# (`llama-uncensored-4b.service` :8092 / `llama-uncensored-4b-code.service`
# :8096, geradas de models.nix). `--free` e `--start-mtp` usam systemctl —
# `nohup llama-server` criava orfaos sem restart e competia com a unit.
#
# USO:
#   llama-swap.sh --list                 # quem roda, com VRAM e modelo
#   llama-swap.sh --self-test            # prova que nao cria orfaos
#   llama-swap.sh --free [--also-stt]    # larga a VRAM (mata o MTP)
#   llama-swap.sh --start-mtp            # religa o MTP identico
#   llama-swap.sh --wait-model bonsai    # espera o router carregar o modelo
set -uo pipefail

MODELS_DIR="/var/lib/ai/models"
MTP_CMD="/home/nixos/projects/llama.cpp/build-stock/bin/llama-server"
MTP_MODEL="${MODELS_DIR}/Qwen3.5-4B-MTP-Q4_K_M.gguf"
MTP_LORA="${MODELS_DIR}/loras/microturn-4b/microturn-4b-lora-v9.gguf"
MTP_PORT=8092
MTP_ALIAS="jarvis-mtp-lora"

log() { printf '%s\n' "$*"; }

vram() { nvidia-smi --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1 | tr -d ' '; }
endpoint_ok() { timeout 12 curl -s -m 10 "http://127.0.0.1:$1/v1/models" 2>/dev/null | grep -q '"id"'; }

mtp_pid() {
  pgrep -f "llama-server -m ${MTP_MODEL}" 2>/dev/null | head -1
}

case "${1:---list}" in
  --list)
    log "== VRAM =="
    nvidia-smi --query-gpu=name,memory.total,memory.used,memory.free --format=csv,noheader 2>/dev/null | sed 's/^/  /'
    log ""
    log "== processos com VRAM =="
    nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader 2>/dev/null | while IFS=, read -r pid mem; do
      pid=$(echo "$pid" | tr -d ' '); mem=$(echo "$mem" | tr -d ' ')
      [ -z "$pid" ] && continue
      m=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | sed -n 's/.*-m \([^ ]*\).*/\1/p')
      p=$(tr '\0' ' ' < "/proc/$pid/cmdline" 2>/dev/null | sed -n 's/.*--port \([0-9]*\).*/\1/p')
      log "  pid=$pid ${mem}MiB porta=${p:-?} modelo=$(basename "${m:-?}")"
    done
    log ""
    log "== endpoints =="
    for p in 8080 8081 8084 8085 8087 8092 8094 8097; do
      if endpoint_ok "$p"; then log "  :$p responde"; else log "  :$p NAO responde"; fi
    done
    ;;

  --free)
    log "VRAM livre antes: $(vram) MiB"
    if [ "${2:-}" = "--also-stt" ]; then
      for pid in $(pgrep -f "whisper-server" 2>/dev/null); do
        log "  parando whisper-server (pid $pid)"; kill "$pid" 2>/dev/null
      done
    fi
    # Stop pelas units: matar so o pid nao basta (Restart/Conflicts do
    # systemd) e deixa o dono do processo inconsistente.
    for u in llama-uncensored-4b.service llama-uncensored-4b-code.service; do
      if [ "$(systemctl is-active "$u" 2>/dev/null)" = "active" ]; then
        systemctl stop "$u" >/dev/null 2>&1
        log "  parando $u — o small model da frota cai ate o --start-mtp"
      fi
    done
    # Orfaos historicos (llama-server sem unit) ainda podem existir.
    pid=$(mtp_pid)
    if [ -n "$pid" ]; then
      log "  parando MTP orfao (pid $pid)"
      kill "$pid" 2>/dev/null
    fi
    for i in $(seq 1 40); do
      free=$(vram)
      [ "${free:-0}" -ge 2500 ] && break
      sleep 1
    done
    log "VRAM livre depois: $(vram) MiB"
    ;;

  --start-mtp)
    # (15/11) DOIS PERFIS do MTP (exclusivos por VRAM):
    #   lora (default): COM o LoRA microturn -> PHONE CALL (voz, :8092).
    #   code: SEM o LoRA -> CODING/TESTES (harness/nightwatch, :8096).
    # (19/11) systemd e' o dono: start da unit, nunca nohup orfao.
    PERFIL="${2:-lora}"
    if [ "$PERFIL" = "code" ]; then
      PORTA=8096; UNIT="llama-uncensored-4b-code.service"
    else
      PORTA="$MTP_PORT"; UNIT="llama-uncensored-4b.service"
    fi
    log "subindo o MTP perfil=$PERFIL (porta $PORTA) via $UNIT..."
    if ! systemctl start "$UNIT" >/dev/null 2>&1; then
      log "  falha no start de $UNIT (systemctl)"
      exit 1
    fi
    log "  $UNIT: $(systemctl is-active "$UNIT" 2>/dev/null)"
    for i in $(seq 1 120); do
      if endpoint_ok "$PORTA"; then
        log "  :$PORTA responde (${i}s) | VRAM livre: $(vram) MiB"
        exit 0
      fi
      sleep 1
    done
    log "  :$PORTA NAO respondeu em 120s"
    exit 1
    ;;

  --self-test)
    # Prova, com systemctl/curl/nohup FALSOS, que --start-mtp nao cria orfao.
    fail=0
    TMP="$(mktemp -d)"; FAKEBIN="$TMP/bin"; mkdir -p "$FAKEBIN"
    cat > "$FAKEBIN/systemctl" <<'EOS'
#!/usr/bin/env bash
printf 'systemctl %s\n' "$*" >> "$FAKECTL_LOG"
if [ "${1:-}" = "is-active" ]; then echo inactive; fi
exit 0
EOS
    cat > "$FAKEBIN/curl" <<'EOS'
#!/usr/bin/env bash
printf '{"data":[{"id":"fake"}]}'
EOS
    cat > "$FAKEBIN/nohup" <<'EOS'
#!/usr/bin/env bash
printf 'nohup %s\n' "$*" >> "$FAKECTL_LOG"
exit 0
EOS
    chmod +x "$FAKEBIN/systemctl" "$FAKEBIN/curl" "$FAKEBIN/nohup"
    export FAKECTL_LOG="$TMP/ctl.log"; : > "$FAKECTL_LOG"
    PATH="$FAKEBIN:$PATH" "$0" --start-mtp code >/dev/null 2>&1 || true
    if grep -q 'start llama-uncensored-4b-code.service' "$FAKECTL_LOG"; then
      echo "ok: --start-mtp code usa a unit"
    else
      echo "FALHOU: --start-mtp code nao chamou systemctl start"; fail=1
    fi
    if grep -q 'nohup' "$FAKECTL_LOG"; then
      echo "FALHOU: --start-mtp ainda cria orfao"; fail=1
    else
      echo "ok: --start-mtp nao cria orfao"
    fi
    rm -rf "$TMP"
    [ "$fail" = "0" ] && echo "SELF-TEST ok: dono unico systemd" || exit 1
    ;;

  --wait-model)
    alvo="${2:-}"
    [ -z "$alvo" ] && { log "uso: llama-swap.sh --wait-model <alias>"; exit 2; }
    for i in $(seq 1 180); do
      st=$(timeout 10 curl -s -m 8 "http://127.0.0.1:8080/v1/models" 2>/dev/null \
           | python3 -c "
import sys, json
try: d = json.load(sys.stdin)
except Exception: raise SystemExit(0)
for m in d.get('data', []):
    if m.get('id') == '$alvo':
        s = (m.get('status') or {}).get('value')
        print(s or 'unknown')
        break
" 2>/dev/null)
      if [ "$st" = "loaded" ]; then log "  $alvo carregado (${i}s) | VRAM livre: $(vram) MiB"; exit 0; fi
      sleep 2
    done
    log "  $alvo nao carregou (estado: ${st:-desconhecido})"
    exit 1
    ;;

  *)
    log "uso: llama-swap.sh --list|--free [--also-stt]|--start-mtp|--wait-model <alias>"
    exit 2
    ;;
esac
