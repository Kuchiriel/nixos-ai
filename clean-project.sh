#!/bin/bash
# clean-project.sh — Remove código morto e backups commitados
# Executar ANTES de commitar para manter o repo limpo
set -e

cd "$(dirname "$0")"

echo "🧹 Limpando __pycache__..."
find . -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true

echo "🧹 Limpando .pytest_cache..."
find . -type d -name .pytest_cache -exec rm -rf {} + 2>/dev/null || true

echo "🧹 Limpando .hypothesis..."
find . -type d -name .hypothesis -exec rm -rf {} + 2>/dev/null || true

echo "🧹 Removendo backups..."
rm -f modules/ai/jarvis/src/jarvis/core/agent.py.bak
rm -f rag.py.bkp

echo "✅ Limpeza concluída!"
echo ""
echo "📊 Arquivos alterados:"
git status --short | head -20
