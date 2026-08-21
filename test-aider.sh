#!/usr/bin/env bash
# test-aider.sh — Benchmark do aider com nosso modelo local
# Testa diferentes configs e mede comportamento
set -uo pipefail

RESULTS_DIR="logs/aider-tests"
mkdir -p "$RESULTS_DIR"
TIMESTAMP=$(date +%Y-%m-%d_%H-%M-%S)

echo "═══════════════════════════════════════════════"
echo "🧪 Aider Benchmark — $(date)"
echo "═══════════════════════════════════════════════"

# Verificar se servidor está rodando
if ! curl -sf http://localhost:8080/health > /dev/null 2>&1; then
    echo "❌ Servidor llama.cpp não está rodando!"
    exit 1
fi

# Verificar VRAM antes
echo "📊 VRAM antes:"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader

# Função para rodar uma tarefa
run_task() {
    local name="$1"
    local prompt="$2"
    local extra_flags="$3"
    local outfile="${RESULTS_DIR}/${TIMESTAMP}_${name}.txt"
    
    echo ""
    echo "─── $name ───"
    echo "Prompt: $prompt"
    
    local start_time=$(date +%s%N)
    
    timeout 120 aider \
        --model openai/custom-model \
        --openai-api-base http://localhost:8080/v1 \
        --no-git \
        --no-auto-commits \
        --no-show-model-warnings \
        --no-check-model-accepts-settings \
        --no-cache-prompts \
        --no-stream \
        --yes-always \
        --message "$prompt" \
        --no-dirty-commits \
        $extra_flags \
        --file modules/ai/models.nix \
        2>&1 | tee "$outfile"
    
    local end_time=$(date +%s%N)
    local duration_ms=$(( (end_time - start_time) / 1000000 ))
    
    echo ""
    echo "⏱️  Duração: ${duration_ms}ms"
    echo "📄 Output salvo em: $outfile"
    
    # Contar tokens se possível
    local output_lines=$(wc -l < "$outfile")
    echo "📏 Linhas de output: $output_lines"
    
    # VRAM depois
    nvidia-smi --query-gpu=memory.used --format=csv,noheader
}

echo ""
echo "═══ Teste 1: Leitura simples (edit-format diff) ═══"
run_task "t1-leitura-diff" \
    "Read the file modules/ai/models.nix and tell me what gpuLayers is set to" \
    "--edit-format diff"

echo ""
echo "═══ Teste 2: Leitura simples (edit-format whole) ═══"
run_task "t2-leitura-whole" \
    "Read the file modules/ai/models.nix and tell me what gpuLayers is set to" \
    "--edit-format whole"

echo ""
echo "═══ Teste 3: Leitura (architect mode) ═══"
run_task "t3-architect-read" \
    "Read the file modules/ai/models.nix and tell me what gpuLayers is set to" \
    "--architect"

echo ""
echo "═══ Teste 4: Edição simples (diff) ═══"
run_task "t4-edicao-diff" \
    "In modules/ai/models.nix, add a comment '# test benchmark' right after the line that says 'gpuLayers = 50'" \
    "--edit-format diff"

echo ""
echo "═══ Teste 5: Edição simples (architect) ═══"
run_task "t5-edicao-architect" \
    "In modules/ai/models.nix, add a comment '# test benchmark' right after the line that says 'gpuLayers = 50'" \
    "--architect"

echo ""
echo "═══ Teste 6: Comprehensão de código (diff) ═══"
run_task "t6-comprehensao" \
    "Look at modules/ai/models.nix. What is the VRAM budget for the host profile? List the components and their sizes." \
    "--edit-format diff"

echo ""
echo "═══ Resumo ═══"
echo "Todos os resultados em: $RESULTS_DIR/$TIMESTAMP_*.txt"
echo ""
echo "📊 VRAM final:"
nvidia-smi --query-gpu=memory.used,memory.total --format=csv,noheader
