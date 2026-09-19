#!/usr/bin/env bash
# Rebuild do sistema NixOS a partir do flake local.
# Valida avaliação ANTES de executar o switch.
# Uso: ./rebuild-host.sh [--host-only] [--debug]
#   --host-only: valida host+HM sem flake-check total (lab quebrado não trava o host).
#   --debug:    executa tudo com output redirecionado para log e exibe o log ao final.
set -e

DEBUG=false
VALIDATE_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --debug) DEBUG=true ;;
        *) VALIDATE_ARGS+=("$arg") ;;
    esac
done

if [ "$DEBUG" = true ]; then
    LOG_FILE="/tmp/rebuild-$(date +%Y%m%d-%H%M%S).log"
    exec > >(tee "$LOG_FILE") 2>&1
    echo "🔍 Modo DEBUG ativo. Log: $LOG_FILE"
fi

FLAKE_DIR="$HOME/projects/nixos-ai"
TARGET_HOST="nitro-v15"

# nh 4.4.2+: usa NH_FLAKE; o FLAKE antigo (sessão pré-upgrade) dispara warning.
export NH_FLAKE="$FLAKE_DIR"
unset FLAKE

# ═══ Multi-Layer Validation ═══
# Roda validação completa antes de qualquer rebuild.
# Se qualquer camada falhar, o rebuild NÃO é executado.

echo "===================================================="
echo "EXECUTANDO VALIDAÇÃO MULTI-CAMADA"
echo "===================================================="

if ! "$FLAKE_DIR/scripts/nix-validate.sh" --host "$TARGET_HOST" "${VALIDATE_ARGS[@]}"; then
  echo ""
  echo "[ERRO CRÍTICO] Validação falhou!"
  echo "Corrija os erros acima ANTES de fazer rebuild."
  echo "O rebuild NÃO será executado."
  exit 1
fi

echo ""
echo "===================================================="

echo "===================================================="
echo "INDEXANDO ALTERAÇÕES NO GIT"
echo "===================================================="
cd "$FLAKE_DIR"
git add -A
# Flakes só enxergam arquivos versionados no Git.
if git diff --cached --quiet; then
  echo "      (nenhuma alteração pendente)"
else
  N_FILES=$(git diff --cached --name-only | wc -l)
  git commit -m "chore: update $N_FILES file(s)"
fi
cd - > /dev/null

echo ""
echo "===================================================="
echo "EXECUTANDO REBUILD"
echo "===================================================="

if [ "$DEBUG" = true ]; then
  nh os switch "$FLAKE_DIR" -H "$TARGET_HOST" -- --show-trace --option binary-caches-parallel-connections 4 --option http-connections 5 2>&1 | tee -a "$LOG_FILE"
else
  nh os switch "$FLAKE_DIR" -H "$TARGET_HOST" -- --option binary-caches-parallel-connections 4 --option http-connections 5
fi

echo ""
echo "===================================================="
echo "✅ SISTEMA ATUALIZADO COM SUCESSO"
echo "===================================================="