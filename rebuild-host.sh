#!/usr/bin/env bash
# Rebuild do sistema NixOS a partir do flake local.
# Valida avaliação ANTES de executar o switch.
# Uso: ./rebuild-host.sh
set -e

FLAKE_DIR="$HOME/projects/nixos-ai"
TARGET_HOST="nitro-v15"

# nh 4.4.2+: usa NH_FLAKE; o FLAKE antigo (sessão pré-upgrade) dispara warning.
export NH_FLAKE="$FLAKE_DIR"
unset FLAKE

echo "===================================================="
echo "INICIANDO VALIDAÇÃO DA CONFIGURAÇÃO"
echo "===================================================="

# 1. Validação da avaliação do Flake (sem efeitos colaterais).
#    Testa se a expressão nixosConfigurations.<host> avalia sem erro.
#    IMPORTANTE: nix eval é validação de avaliação, NÃO garante proteção
#    contra OOM por infinite recursion — mas é a melhor barreira disponível.
if ! nix eval "$FLAKE_DIR#nixosConfigurations.$TARGET_HOST.config.system.build.toplevel" \
    --show-trace > /dev/null 2>&1; then
  echo ""
  echo "[ERRO CRÍTICO] Falha durante avaliação da configuração!"
  echo "Executando novamente com trace detalhado:"
  echo "----------------------------------------------------"
  nix eval "$FLAKE_DIR#nixosConfigurations.$TARGET_HOST.config.system.build.toplevel" \
    --show-trace 2>&1 || true
  echo "----------------------------------------------------"
  echo ""
  echo "Avaliação FRACASSOU. Corrija os erros acima ANTES de fazer rebuild."
  echo "O rebuild NÃO será executado."
  exit 1
fi

echo "✅ Avaliação concluída com sucesso."
echo ""

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

nh os switch "$FLAKE_DIR" -H "$TARGET_HOST" -- --option binary-caches-parallel-connections 4 --option http-connections 5

echo ""
echo "===================================================="
echo "✅ SISTEMA ATUALIZADO COM SUCESSO"
echo "===================================================="
