#!/usr/bin/env bash
# test-aider-benchmark.sh — Benchmark E2E do aider com nosso modelo
# Tarefas de dificuldade crescente: leitura → edição → multi-step → shell
set -uo pipefail

RESULTS_DIR="logs/aider-benchmark"
mkdir -p "$RESULTS_DIR"
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)
SUMMARY="${RESULTS_DIR}/${TIMESTAMP}_summary.txt"

echo "═══════════════════════════════════════════════" | tee "$SUMMARY"
echo "🧪 Aider E2E Benchmark — $(date)" | tee -a "$SUMMARY"
echo "═══════════════════════════════════════════════" | tee -a "$SUMMARY"

# Verificar servidor
if ! curl -sf http://localhost:8080/health > /dev/null 2>&1; then
    echo "❌ Servidor offline!" | tee -a "$SUMMARY"
    exit 1
fi

# Config padrão para todos os testes
AIDER_BASE="OPENAI_API_KEY=sk-dummy aider \
    --model openai/custom-model \
    --openai-api-base http://localhost:8080/v1 \
    --no-git --no-auto-commits --no-show-model-warnings \
    --no-check-model-accepts-settings --no-cache-prompts \
    --yes-always --no-stream"

TOTAL=0
PASSED=0
FAILED=0

run_test() {
    local num="$1"
    local name="$2"
    local difficulty="$3"
    local prompt="$4"
    local file="$5"
    local validate_cmd="$6"
    local extra_flags="${7:-}"
    
    TOTAL=$((TOTAL + 1))
    echo "" | tee -a "$SUMMARY"
    echo "─── Test $num: $name [$difficulty] ───" | tee -a "$SUMMARY"
    echo "Prompt: $prompt" | tee -a "$SUMMARY"
    
    # Backup do arquivo
    if [[ -n "$file" && -f "$file" ]]; then
        cp "$file" "/tmp/aider_test_backup_$$"
    fi
    
    local start_time=$(date +%s%N)
    
    local output
    output=$(timeout 120 env $AIDER_BASE $extra_flags \
        --message "$prompt" \
        ${file:+--file "$file"} \
        2>&1)
    
    local end_time=$(date +%s%N)
    local duration_ms=$(( (end_time - start_time) / 1000000 ))
    
    # Extrair tokens
    local tokens_line=$(echo "$output" | grep "Tokens:" | tail -1)
    local tokens_sent=$(echo "$tokens_line" | grep -oP '\d+\.?\d*k sent' | head -1)
    local tokens_recv=$(echo "$tokens_line" | grep -oP '\d+ received' | head -1)
    
    # Validar resultado
    local result="❓"
    if [[ -n "$validate_cmd" ]]; then
        if eval "$validate_cmd" > /dev/null 2>&1; then
            result="✅"
            PASSED=$((PASSED + 1))
        else
            result="❌"
            FAILED=$((FAILED + 1))
        fi
    else
        # Sem validação — verificar se output tem resposta
        if echo "$output" | grep -q "Applied edit\|ANSWER"; then
            result="✅"
            PASSED=$((PASSED + 1))
        else
            result="⚠️"
            FAILED=$((FAILED + 1))
        fi
    fi
    
    echo "$result ${duration_ms}ms | ${tokens_sent:-?} sent | ${tokens_recv:-?} recv" | tee -a "$SUMMARY"
    
    # Salvar output detalhado
    echo "$output" > "${RESULTS_DIR}/${TIMESTAMP}_test${num}.txt"
    
    # Restaurar arquivo
    if [[ -f "/tmp/aider_test_backup_$$" && -n "$file" ]]; then
        cp "/tmp/aider_test_backup_$$" "$file"
        rm -f "/tmp/aider_test_backup_$$"
    fi
    
    sleep 2
}

# ══════════════════════════════════════════════════════════════
# NÍVEL 1: LEITURA (fácil)
# ══════════════════════════════════════════════════════════════
echo "" | tee -a "$SUMMARY"
echo "═══ NÍVEL 1: LEITURA ═══" | tee -a "$SUMMARY"

run_test 1 "Leitura simples" "Fácil" \
    "What is gpuLayers set to in the host profile?" \
    "modules/ai/models.nix" \
    'grep -q "gpuLayers = 50" modules/ai/models.nix'

run_test 2 "Leitura com contexto" "Fácil" \
    "Read modules/ai/models.nix and list all the extraArgs flags used in the host profile" \
    "modules/ai/models.nix" \
    'grep -q "no-mmproj-offload" modules/ai/models.nix'

# ══════════════════════════════════════════════════════════════
# NÍVEL 2: EDIÇÃO SIMPLES (média)
# ══════════════════════════════════════════════════════════════
echo "" | tee -a "$SUMMARY"
echo "═══ NÍVEL 2: EDIÇÃO SIMPLES ═══" | tee -a "$SUMMARY"

run_test 3 "Mudar valor numérico" "Média" \
    "Change gpuLayers from 50 to 51 in the host profile" \
    "modules/ai/models.nix" \
    'grep -q "gpuLayers = 51" modules/ai/models.nix'

run_test 4 "Adicionar comentário" "Média" \
    "Add a comment '# TEST BENCHMARK' right after the line 'gpuLayers = 50;' in the host profile" \
    "modules/ai/models.nix" \
    'grep -A1 "gpuLayers = 50" modules/ai/models.nix | grep -q "TEST BENCHMARK"'

run_test 5 "Trocar string" "Média" \
    "In modules/ai/models.nix, change the comment after gpuLayers from 'OTIMIZADO' to 'OPTIMIZED'" \
    "modules/ai/models.nix" \
    'grep -q "OPTIMIZED" modules/ai/models.nix'

# ══════════════════════════════════════════════════════════════
# NÍVEL 3: EDIÇÃO MULTI-STEP (difícil)
# ══════════════════════════════════════════════════════════════
echo "" | tee -a "$SUMMARY"
echo "═══ NÍVEL 3: EDIÇÃO MULTI-STEP ═══" | tee -a "$SUMMARY"

run_test 6 "Duas edições no mesmo arquivo" "Difícil" \
    "In modules/ai/models.nix, do two changes: 1) Change gpuLayers from 50 to 52, 2) Change batchSize from 1024 to 2048" \
    "modules/ai/models.nix" \
    'grep -q "gpuLayers = 52" modules/ai/models.nix && grep -q "batchSize = 2048" modules/ai/models.nix'

# ══════════════════════════════════════════════════════════════
# NÍVEL 4: COMPREENSÃO + RACIOCÍNIO (expert)
# ══════════════════════════════════════════════════════════════
echo "" | tee -a "$SUMMARY"
echo "═══ NÍVEL 4: COMPREENSÃO ═══" | tee -a "$SUMMARY"

run_test 7 "Análise de VRAM budget" "Expert" \
    "Read modules/ai/models.nix and calculate the total VRAM budget for the host profile. List each component and its size in MiB." \
    "modules/ai/models.nix" \
    'grep -q "gpuLayers = 50" modules/ai/models.nix'

# ══════════════════════════════════════════════════════════════
# RESUMO
# ══════════════════════════════════════════════════════════════
echo "" | tee -a "$SUMMARY"
echo "═══════════════════════════════════════════════" | tee -a "$SUMMARY"
echo "📊 RESUMO: $PASSED/$TOTAL passed, $FAILED failed" | tee -a "$SUMMARY"
echo "═══════════════════════════════════════════════" | tee -a "$SUMMARY"
echo "" | tee -a "$SUMMARY"
echo "VRAM:" | tee -a "$SUMMARY"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader | tee -a "$SUMMARY"
echo "" | tee -a "$SUMMARY"
echo "Detalhes em: $RESULTS_DIR/${TIMESTAMP}_test*.txt" | tee -a "$SUMMARY"
