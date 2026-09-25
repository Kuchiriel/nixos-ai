#!/usr/bin/env bash
# qwen4b-session.sh — perfil ISOLADO + CIFRADO p/ modelo local sem filtro.
#
# Isolamento (por construção, não por convenção):
#   state_dir   = ~/.local/state/jarvis-qwen4b   (vault, memória, histórico)
#   vault       = cifrado em repouso (Fernet, chave em /etc/jarvis-secrets)
#   Qdrant      = coleções qwen4b_code / _memories / _books (RAG separado)
#   SEM JARVIS_EXTRA_READ_ROOTS → o perfil NÃO enxerga ~/Pessoal (INSS)
#   SEM Telegram/notify, SEM hooks do ambiente principal.
#
# Modelo (medido 24/09, 3 reps, mesmas flags):
#   Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf (2,7GB Q4_K_M)
#   prism b10735 56,0 t/s > wackmall 55,2 > nix upstream 54,4  → prism vence
#
# Uso:
#   ./scripts/qwen4b-session.sh            → REPL interativo (perfil isolado)
#   ./scripts/qwen4b-session.sh serve      → só sobe o modelo (fundo)
#   ./scripts/qwen4b-session.sh stop        → derruba o modelo
#   ./scripts/qwen4b-session.sh chat "msg" → 1 chamada
#   ./scripts/qwen4b-session.sh index DIR  → indexa DIR no RAG isolado
#   ./scripts/qwen4b-session.sh keygen     → (re)gera a chave do vault
set -euo pipefail

MODEL="${QWEN4B_MODEL:-/home/nixos/models/Qwen3.5-4B-Uncensored-HauhauCS-Aggressive-Q4_K_M.gguf}"
PORT="${QWEN4B_PORT:-8092}"
PRISM=/home/nixos/projects/prism-bin/run-prism-b10735.sh
LOG=/tmp/qwen4b-$$.log
STATE="$HOME/.local/state/jarvis-qwen4b"
KEYFILE=/etc/jarvis-secrets/qwen4b-vault.fernet.key
NIXAI=/home/nixos/projects/nixos-ai

# Flags vencedoras (medidas): dense Q4 no prism, KV q4_0, ctx 8k, 1 slot.
SERVER_FLAGS=(
  --host 127.0.0.1 --port "$PORT"
  -m "$MODEL"
  -ngl 99 -c 8192
  -fa on -ctk q4_0 -ctv q4_0
  -t 8 -b 512 -ub 512
  --parallel 1 --jinja
)

profile_env() {
  export JARVIS_STATE_DIR="$STATE"
  export JARVIS_VAULT_DIR="$STATE/vault"
  export JARVIS_VAULT_ENC=1
  export JARVIS_VAULT_KEY_FILE="$KEYFILE"
  export JARVIS_QDRANT_COLLECTION_CODE=qwen4b_code
  export JARVIS_QDRANT_COLLECTION_MEMORIES=qwen4b_memories
  export JARVIS_QDRANT_COLLECTION_BOOKS=qwen4b_books
  # `--pessoal` (QWEN4B_PESSOAL=1): este é o ÚNICO perfil que pode ler
  # ~/Pessoal e as coleções protegidas. Só habilite para trabalho local
  # (perícia, diário) — NUNCA com provider de nuvem, que levaria o
  # conteúdo para fora da máquina.
  if [ "${QWEN4B_PESSOAL:-0}" = "1" ]; then
    export JARVIS_EXTRA_READ_ROOTS="$HOME/Pessoal"
    export JARVIS_QDRANT_COLLECTION_CODE=pessoal_code
    export JARVIS_QDRANT_COLLECTION_MEMORIES=pessoal_memories
    echo "⚠ modo PESSOAL: RAG+litura de ~/Pessoal ativos (só local)" >&2
  else
    unset JARVIS_EXTRA_READ_ROOTS
  fi
  export JARVIS_LLM_BASE_URL="http://127.0.0.1:$PORT/v1"
  export JARVIS_LLM_MODEL="${QWEN4B_MODEL_ID:-qwen4b}"
  export JARVIS_LLM_DISABLE_THINKING="${QWEN4B_THINKING:-1}"  # H3: effort alto = 3x turnos sem ganho
  unset JARVIS_TELEGRAM_TOKEN JARVIS_TELEGRAM_CHAT_ID
  mkdir -p "$STATE"
  chmod 700 "$STATE"
}

ensure_key() {
  if [ ! -f "$KEYFILE" ]; then
    echo "AVISO: chave do vault ausente em $KEYFILE" >&2
    echo "Gere com: sudo ./scripts/qwen4b-session.sh keygen" >&2
    return 1
  fi
}

serve() {
  if curl -sf --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1; then
    echo "já está no ar em :$PORT"; return 0
  fi
  if [ ! -f "$MODEL" ]; then
    echo "ERRO: modelo ausente: $MODEL" >&2; exit 1
  fi
  # 1 LLM por vez na 6GB: derruba o router se ele estiver ocupando VRAM.
  if nvidia-smi --query-compute-apps=used_memory --format=csv,noheader,nounits 2>/dev/null | awk '$1>1200' | grep -q .; then
    echo "VRAM ocupada (outro LLM ativo) — pare-o ou use outro PRIMEIRO" >&2
    echo "dica: sudo systemctl stop llama-cpp-server" >&2
    exit 1
  fi
  echo "subindo prism b10735 em :$PORT (log: $LOG)…"
  setsid bash "$PRISM" llama-server "${SERVER_FLAGS[@]}" >"$LOG" 2>&1 < /dev/null &
  for _ in $(seq 1 60); do
    curl -sf --max-time 2 "http://127.0.0.1:$PORT/health" >/dev/null 2>&1 && { echo "PRONTO (:$PORT)"; return 0; }
    sleep 2
  done
  echo "ERRO: não subiu (veja $LOG)" >&2; exit 1
}

stop() {
  pkill -f "port $PORT" 2>/dev/null || true
  echo "derrubado"
}

case "${1:-repl}" in
  serve) serve ;;
  stop) stop ;;
  keygen)
    profile_env
    sudo install -d -m 755 -o root -g root /etc/jarvis-secrets
    nix develop "$NIXAI" --command python3 -c "
from jarvis.core.vault_cipher import generate_key
print(generate_key('$KEYFILE'))" | tail -1
    sudo chmod 600 "$KEYFILE"; sudo chown root:root "$KEYFILE"
    echo "chave escrita em $KEYFILE (600 root:root) — guarde uma cópia fora da máquina"
    ;;
  serve_and) serve; shift; profile_env; exec "$@" ;;
  chat)
    msg="${2:?uso: chat 'mensagem'}"
    serve >/dev/null
    profile_env
    nix develop "$NIXAI" --command python3 - "$msg" <<'PY'
import os, sys, urllib.request, json
msg = sys.argv[1]
body = json.dumps({"model": "qwen4b", "max_tokens": 512,
                   "chat_template_kwargs": {"enable_thinking": False},
                   "messages": [{"role": "user", "content": msg}]}).encode()
req = urllib.request.Request(f"http://127.0.0.1:{os.environ.get('QWEN4B_PORT','8092')}/v1/chat/completions",
                             data=body,
                             headers={"Content-Type": "application/json"})
with urllib.request.urlopen(req, timeout=180) as r:
    print(json.load(r)["choices"][0]["message"]["content"])
PY
    ;;
  index)
    dir="${2:?uso: index DIR}"
    profile_env
    nix develop "$NIXAI" --command python3 -m jarvis.rag_index "$dir" 2>/dev/null \
      || nix develop "$NIXAI" --command jarvis rag index "$dir"
    ;;
  repl)
    profile_env
    ensure_key
    serve
    nix develop "$NIXAI" --command jarvis dev
    ;;
  *) echo "uso: $0 {repl|serve|stop|chat MSG|index DIR|keygen}" >&2; exit 1 ;;
esac
