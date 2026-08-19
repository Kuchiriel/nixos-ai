#!/usr/bin/env bash
# Rebuild do sistema NixOS a partir do flake local.
# Uso: ./rebuild.sh
set -e

FLAKE_DIR="$HOME/nixos-config-reborn"
TARGET_HOST="nixos-lab"

# nh 4.4.2+: usa NH_FLAKE; o FLAKE antigo (sessão pré-upgrade) dispara warning.
export NH_FLAKE="$FLAKE_DIR"
unset FLAKE

echo "[1/3] Indexando alterações no Git para o Nix Flakes..."
cd "$FLAKE_DIR"
git add -A
# Flakes só enxergam arquivos versionados no Git.
# Se não houver alteração, não cria commit.
if git diff --cached --quiet; then
  echo "      (nenhuma alteração pendente)"
else
  N_FILES=$(git diff --cached --name-only | wc -l)
  git commit -m "chore: update $N_FILES file(s)"
fi
cd - > /dev/null

echo "[2/3] Executando Rebuild..."
nh os switch "$FLAKE_DIR" -H "$TARGET_HOST" -- --option binary-caches-parallel-connections 4 --option http-connections 5 | grep -E "error:|at .*\.nix" || true

echo "[3/3] Sistema atualizado!"
