#!/usr/bin/env bash
# jarvis-registry.sh — lê o registry de modelos (fonte única: modules/ai/models.nix)
#
# Uso:
#   source scripts/jarvis-registry.sh
#   BASE=$(reg_endpoint "$(reg_default)")
#   PORT=$(reg_port jarvis-mtp-lora)
#   UNIT=$(reg_unit jarvis-mtp-lora)
#
# Contrato:
#   REGISTRY_PATH           caminho do registry (padrão /etc/jarvis/model-registry.json)
#   reg_default             → id do modelo default do sistema
#   reg_port <id>           → porta do server que serve <id>
#   reg_endpoint <id>       → http://127.0.0.1:<porta>
#   reg_service_port <nome> → porta de um serviço auxiliar (embeddings|rerank)
#   reg_unit <id>           → unit systemd que serve <id> (se declarado)
#
# O registry é gerado pelo Nix (llama-cpp.nix → environment.etc."jarvis/
# model-registry.json"). Se faltar, as funções falham (código != 0) e o
# chamador decide o fallback — nenhuma porta literal mora aqui.
REGISTRY_PATH="${JARVIS_MODEL_REGISTRY:-/etc/jarvis/model-registry.json}"

_reg_python() {
  command -v python3 2>/dev/null || echo /run/current-system/sw/bin/python3
}

# $1 = expressão python (ver d, sys); $2.. = argumentos (sys.argv[3..])
_reg_query() {
  [ -r "$REGISTRY_PATH" ] || return 1
  "$( _reg_python )" - "$REGISTRY_PATH" "$@" <<'EOF'
import json
import sys

try:
    with open(sys.argv[1], encoding="utf-8") as fh:
        d = json.load(fh)
except Exception:
    sys.exit(1)

expr = sys.argv[2]
try:
    out = eval(expr, {"d": d, "json": json, "sys": sys})  # noqa: S307
except Exception:
    sys.exit(1)
if out is None or out == "":
    sys.exit(1)
print(out)
EOF
}

reg_default() {
  _reg_query 'd.get("default")'
}

reg_port() {
  _reg_query "d['models'][sys.argv[3]]['endpoint']" "$1"
}

reg_endpoint() {
  local p
  p="$(reg_port "$1")" || return 1
  printf 'http://127.0.0.1:%s' "$p"
}

reg_unit() {
  local u
  if u="$(_reg_query "d.get('models', {}).get(sys.argv[3], {}).get('unit') or d.get('units', {}).get(sys.argv[3], {}).get('unit')" "$1")"; then
    printf '%s' "$u"
    return 0
  fi
  # Shim de compat (03/11): o registry em /etc é da generation ANTES do
  # rebuild que adicionou `unit`/`units`. Remover depois do rebuild.
  case "$1" in
    jarvis-mtp-lora) printf 'llama-uncensored-4b' ;;
    bonsai) printf 'llama-cpp-server' ;;
    jarvis-fast|jarvis-raw) printf 'llama-cpp-upstream' ;;
    jarvis-strong|jarvis-raw-strong) printf 'llama-cpp-ik' ;;
    *) return 1 ;;
  esac
}

reg_service_port() {
  local p
  if p="$(_reg_query "d.get('servicePorts', {}).get(sys.argv[3])" "$1")"; then
    printf '%s' "$p"
    return 0
  fi
  # Shim de compat (03/11) — mesmo motivo do reg_unit.
  case "$1" in
    embeddings) printf '8081' ;;
    rerank) printf '8082' ;;
    *) return 1 ;;
  esac
}
