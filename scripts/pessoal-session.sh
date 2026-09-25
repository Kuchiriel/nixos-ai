#!/usr/bin/env bash
# pessoal-session.sh — perfil PROTEGIDO p/ documentos e diário pessoal.
#
# Por que existe (24/09): o RAG principal indexava ~/Pessoal inteiro
# (604 pontos: processo do erro médico, laudos, receitas, carteira de
#，难怪). Dono decidiu: o que é sensível tem porta própria, com cifragem e
# coleções separadas — e o agente normal NÃO enxerga nada daqui.
#
# Isolamento (por construção):
#   state_dir  = ~/.local/state/jarvis-pessoal   (vault cifrado)
#   chave      = /etc/jarvis-secrets/pessoal-vault.fernet.key (600, separada
#               da chave do perfil Qwen 4B — uma chave comprometida não abre
#               a outra)
#   RAG        = coleções pessoal_code / pessoal_memories (nunca code_index)
#   SEM JARVIS_EXTRA_READ_ROOTS → este perfil é o ÚNICO que pode ler
#   ~/Pessoal; o resto do jarvis não tem esse direito.
#
# Uso:
#   ./scripts/pessoal-session.sh                 → REPL com o perfil protegido
#   ./scripts/pessoal-session.sh note "nome"      → abre $EDITOR p/ escrever a nota (cifrada ao salvar)
#   ./scripts/pessoal-session.sh show "nome"      → mostra a nota decifrada
#   ./scripts/pessoal-session.sh list            → lista as notas
#   ./scripts/pessoal-session.sh index [DIR]     → indexa DIR no RAG pessoal (default: ~/Pessoal)
#   ./scripts/pessoal-session.sh stop            → derruba o router (libera VRAM) e restaura
set -euo pipefail

STATE="$HOME/.local/state/jarvis-pessoal"
KEYFILE=/etc/jarvis-secrets/pessoal-vault.fernet.key
NIXAI=/home/nixos/projects/nixos-ai
PESSOAL_DIR="${PESSOAL_DIR:-$HOME/Pessoal}"

profile_env() {
  export JARVIS_STATE_DIR="$STATE"
  export JARVIS_VAULT_DIR="$STATE/vault"
  export JARVIS_VAULT_ENC=1
  export JARVIS_VAULT_KEY_FILE="$KEYFILE"
  export JARVIS_QDRANT_COLLECTION_CODE=pessoal_code
  export JARVIS_QDRANT_COLLECTION_MEMORIES=pessoal_memories
  export JARVIS_QDRANT_COLLECTION_BOOKS=pessoal_books
  # ÚNICO perfil com direito de leitura sobre ~/Pessoal.
  export JARVIS_EXTRA_READ_ROOTS="$PESSOAL_DIR"
  unset JARVIS_TELEGRAM_TOKEN JARVIS_TELEGRAM_CHAT_ID
  mkdir -p "$STATE/vault"; chmod 700 "$STATE"
}

jarvis_py() {
  profile_env
  nix develop "$NIXAI" --command python3 -c "$1" "${2:-}"
}

case "${1:-repl}" in
  note)
    name="${2:?uso: note NOME}"
    profile_env
    tmp=$(mktemp /tmp/pessoal-note-XXXX.md)
    "${EDITOR:-nano}" "$tmp"
    nix develop "$NIXAI" --command python3 - "$name" "$tmp" <<'PY'
import sys
from pathlib import Path
from jarvis.core import vault_cipher as vc
name, src = sys.argv[1], Path(sys.argv[2])
p = vc.note_path(Path.home() / ".local/state/jarvis-pessoal/vault", f"{name}.md")
vc.write_text(p, src.read_text(encoding="utf-8"))
src.unlink()
print(f"nota cifrada: {p}")
PY
    ;;
  show)
    name="${2:?uso: show NOME}"
    jarvis_py "
import sys
from pathlib import Path
from jarvis.core import vault_cipher as vc
p = vc.note_path(Path.home() / '.local/state/jarvis-pessoal/vault', f'{sys.argv[1]}.md')
print(vc.read_text(p))
" "$name"
    ;;
  list)
    jarvis_py "
from pathlib import Path
from jarvis.core import vault_cipher as vc
from jarvis.core.vault import MemoryVault
for n in MemoryVault().list_notes(): print(n)
"
    ;;
  index)
    dir="${2:-$PESSOAL_DIR}"
    profile_env
    echo "indexando $dir nas coleções pessoais (isso NÃO toca no code_index)…"
    nix develop "$NIXAI" --command jarvis rag index "$dir"
    ;;
  stop)
    sudo systemctl stop llama-cpp-server 2>/dev/null || true
    sleep 2
    sudo systemctl start llama-cpp-server 2>/dev/null || true
    echo "router reiniciado"
    ;;
  repl)
    profile_env
    [ -f "$KEYFILE" ] || { echo "chave ausente: $KEYFILE" >&2; exit 1; }
    nix develop "$NIXAI" --command jarvis dev
    ;;
  *) echo "uso: $0 {repl|note NOME|show NOME|list|index [DIR]|stop}" >&2; exit 1 ;;
esac
