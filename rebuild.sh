#!/usr/bin/env bash
set -e

FLAKE_DIR="$HOME/nixos-config-reborn"
TARGET_HOST="nixos-lab"

echo "[1/4] Reiniciando nix-daemon..."
sudo systemctl restart nix-daemon

echo "[2/4] Indexando e salvando alterações no Git para o Nix Flakes..."
cd "$FLAKE_DIR"
git add -A
git commit -m "chore: update system configuration" || true
cd - > /dev/null

echo "[3/4] Executando Rebuild..."
nh os switch "$FLAKE_DIR" -H "$TARGET_HOST" -- --option binary-caches-parallel-connections 4 --option http-connections 5

echo "[4/4] Sistema atualizado!"
