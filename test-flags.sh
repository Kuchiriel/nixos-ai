#!/usr/bin/env bash
# test-flags.sh — Testa flags do llama.cpp individualmente
# Uso: ./test-flags.sh [--flag "FLAG EXTRA"] [--desc "descrição"]
#
# O script:
# 1. Salva config atual
# 2. Adiciona flag testada ao extraArgs
# 3. Rebuild + espera servidor
# 4. Roda benchmark 3x
# 5. Restaura config original

set -euo pipefail

MODELS_NIX="modules/ai/models.nix"
BACKUP="${MODELS_NIX}.bak"
RESULTS_DIR="logs/flag-tests"
mkdir -p "$RESULTS_DIR"

# Parse args
EXTRA_FLAG=""
DESC=""
while [[ $# -gt 0 ]]; do
    case "$1" in
        --flag) EXTRA_FLAG="$2"; shift 2 ;;
        --desc) DESC="$2"; shift 2 ;;
        *) echo "Uso: $0 --flag \"FLAG\" --desc \"descrição\""; exit 1 ;;
    esac
done

if [[ -z "$EXTRA_FLAG" ]]; then
    echo "ERRO: precise de --flag \"FLAG\" para testar"
    exit 1
fi

TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
SAFE_NAME=$(echo "$DESC" | tr ' ' '-' | tr -cd '[:alnum:]-')
RESULT_FILE="${RESULTS_DIR}/${TIMESTAMP}_${SAFE_NAME}.json"

echo "═══════════════════════════════════════════════"
echo "🧪 Testando: $DESC"
echo "   Flag: $EXTRA_FLAG"
echo "═══════════════════════════════════════════════"

# Backup
cp "$MODELS_NIX" "$BACKUP"

# Injetar flag no extraArgs (antes do último ])
sed -i "s|\"--prio-batch\" \"3\"|\"--prio-batch\" \"3\"\n            ${EXTRA_FLAG}|" "$MODELS_NIX"

echo "📝 Flag injetada no models.nix"

# Rebuild
echo "🔨 Rebuild..."
git add -A
./rebuild-host.sh 2>&1 | tail -3

# Esperar servidor
echo "⏳ Esperando servidor..."
sleep 25

# Verificar se servidor subiu
if ! curl -sf http://localhost:8080/health > /dev/null 2>&1; then
    echo "❌ Servidor não subiu! Restaurando..."
    cp "$BACKUP" "$MODELS_NIX"
    git add -A && ./rebuild-host.sh 2>&1 | tail -3
    exit 1
fi

# Verificar warnings
echo "📋 Log do start:"
journalctl -u llama-cpp-server --since "30 sec ago" --no-pager 2>&1 | grep -E "warn|error|fit_params|tensor|override" | head -5

# Benchmark
echo ""
echo "📊 Benchmark (3 runs + warmup)..."
./benchmark.sh --warmup --repeat 3 2>&1 | tee "${RESULTS_DIR}/${TIMESTAMP}_${SAFE_NAME}_raw.txt" | grep -E "Run|Resultado|Decode|Prefill|DRIFT|RAM"

# Salvar resultado consolidado
LATEST_CONSOLIDATED=$(ls -t logs/benchmark/*_consolidated.json 2>/dev/null | head -1)
if [[ -n "$LATEST_CONSOLIDATED" ]]; then
    cp "$LATEST_CONSOLIDATED" "$RESULT_FILE"
fi

# Restaurar
echo ""
echo "🔄 Restaurando config original..."
cp "$BACKUP" "$MODELS_NIX"
rm -f "$BACKUP"
git add -A
./rebuild-host.sh 2>&1 | tail -3

echo ""
echo "✅ Teste concluído: $DESC"
echo "   Resultado: $RESULT_FILE"
echo "   Raw: ${RESULTS_DIR}/${TIMESTAMP}_${SAFE_NAME}_raw.txt"
