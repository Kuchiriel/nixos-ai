#!/usr/bin/env bash
# kaggle-conta — alterna entre contas Kaggle sem imprimir token.
# Uso: kaggle-conta <kuchiriel|magbeatles|use> [comandos do kaggle...]
#   kaggle-conta use kuchiriel        # salva conta ativa (so o nome, nunca token)
#   kaggle-conta kuchiriel quota -v   # roda com a conta escolhida
#   kaggle-conta magbeatles competitions list
# Seguranca: token fica so em ~/.kaggle (chmod 600); nunca vai para log/repo/bus.
set -uo pipefail

KAGGLE_BIN="${KAGGLE_BIN:-/home/nixos/kvenv/bin/kaggle}"
STATE="/home/nixos/.kaggle/conta-ativa"
DEFAULT_TIMEOUT=120

usage() {
  cat <<'EOF'
uso: kaggle-conta <kuchiriel|magbeatles|use> [args do kaggle]
  use <conta>            salva a conta ativa (nome apenas, sem token)
  <conta> <comandos>     executa o CLI Kaggle com o token daquela conta
  --help                 esta ajuda
Exemplo: kaggle-conta kuchiriel competitions list
EOF
}

[ "${1:-}" = "--help" ] && { usage; exit 0; }
[ $# -ge 1 ] || { usage >&2; exit 2; }

if [ "$1" = "use" ]; then
  case "${2:-}" in
    kuchiriel|magbeatles) printf '%s\n' "$2" > "$STATE"; echo "conta ativa: $2"; exit 0 ;;
    *) echo "conta invalida: ${2:-vazia}" >&2; exit 2 ;;
  esac
fi

case "$1" in
  kuchiriel)
    # token novo entregue pelo dono: ~/.kaggle/access_token (600)
    TOKEN_FILE="/home/nixos/.kaggle/access_token"
    ACCOUNT="kuchiriel"
    ;;
  magbeatles)
    TOKEN_FILE="/home/nixos/.kaggle/kaggle.json.bak-magbeatles-20261124"
    ACCOUNT="magbeatles"
    ;;
  *)
    echo "conta desconhecida: $1 (use kuchiriel ou magbeatles)" >&2
    exit 2
    ;;
esac

if [ ! -r "$TOKEN_FILE" ]; then
  echo "arquivo de token ausente para $ACCOUNT" >&2
  exit 3
fi

# kaggle.json guarda o token em "key"; access_token e' texto puro.
case "$TOKEN_FILE" in
  *.json|*.json.*)
    TOKEN="$(python3 - "$TOKEN_FILE" <<'PY'
import json, sys
print(json.load(open(sys.argv[1]))['key'])
PY
)"
    ;;
  *)
    TOKEN="$(head -1 "$TOKEN_FILE" | tr -d '\r\n')"
    ;;
esac

if [ -z "$TOKEN" ]; then
  echo "token vazio para $ACCOUNT" >&2
  exit 3
fi

unset KAGGLE_USERNAME KAGGLE_KEY KAGGLE_CONFIG_DIR
export KAGGLE_API_TOKEN="$TOKEN"
# Nunca imprimir TOKEN; saida e' apenas a do CLI.
timeout "${KAGGLE_TIMEOUT:-$DEFAULT_TIMEOUT}" "$KAGGLE_BIN" "${@:2}"
