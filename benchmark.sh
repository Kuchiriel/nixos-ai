#!/usr/bin/env bash
# benchmark.sh — Benchmark E2E do llama-server com lock e logging
#
# Uso:
#   ./benchmark.sh                # executa 1x (lock contra concorrência)
#   ./benchmark.sh --repeat N     # executa N vezes com intervalo de 5s
#   ./benchmark.sh --warmup       # 1 run descartado antes do benchmark real
#
# Logs ficam em logs/benchmark/YYYY-MM-DD_HH-MM-SS.json

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_DIR="${SCRIPT_DIR}/logs/benchmark"
LOCK_FILE="/tmp/jarvis-benchmark.lock"
SERVER_URL="http://127.0.0.1:8080"
PROMPT_SIZE=60  # repetições da frase-base

# ─── Parse args ───
REPEAT=1
WARMUP=false
while [[ $# -gt 0 ]]; do
    case "$1" in
        --repeat) REPEAT="$2"; shift 2 ;;
        --warmup) WARMUP=true; shift ;;
        *) echo "Uso: $0 [--repeat N] [--warmup]"; exit 1 ;;
    esac
done

mkdir -p "$LOG_DIR"

# ─── Lock com flock (evita concorrência) ───
exec 200>"$LOCK_FILE"
if ! flock -n 200; then
    echo "ERRO: Outro benchmark já está rodando (lock: $LOCK_FILE)" >&2
    echo "Se isso é um erro, delete $LOCK_FILE" >&2
    exit 1
fi

# ─── Verificar servidor ───
if ! curl -sf "${SERVER_URL}/health" > /dev/null 2>&1; then
    echo "ERRO: llama-server não está respondendo em ${SERVER_URL}" >&2
    exit 1
fi

# ─── Gerar prompt ───
PROMPT=$(python3 -c "print('O rápido raposa marrom pula sobre o cão preguiçoso. ' * ${PROMPT_SIZE})")

# ─── Função de um run ───
run_once() {
    local start_ts
    start_ts=$(date +%s%N)

    local result
    result=$(curl -s "${SERVER_URL}/completion" \
        -H "Content-Type: application/json" \
        -d "{
            \"prompt\": \"${PROMPT}\n\nResuma o texto acima em uma frase.\",
            \"n_predict\": 128,
            \"cache_prompt\": false,
            \"temperature\": 0,
            \"seed\": 42,
            \"ignore_eos\": true
        }")

    local end_ts
    end_ts=$(date +%s%N)

    local wall_ms=$(( (end_ts - start_ts) / 1000000 ))

    # Extrair timings
    echo "$result" | python3 -c "
import json, sys

data = json.load(sys.stdin)
timings = data.get('timings', {})

output = {
    'timestamp': '$(date -Iseconds)',
    'wall_ms': ${wall_ms},
    'prompt_n': timings.get('prompt_n', 0),
    'prompt_ms': timings.get('prompt_ms', 0),
    'prompt_per_second': timings.get('prompt_per_second', 0),
    'predicted_n': timings.get('predicted_n', 0),
    'predicted_ms': timings.get('predicted_ms', 0),
    'predicted_per_second': timings.get('predicted_per_second', 0),
    'cache_n': timings.get('cache_n', 0),
    'model': data.get('model', 'unknown'),
    'gpu_info': None
}

# Verificar VRAM
import subprocess
try:
    smi = subprocess.run(
        ['nvidia-smi', '--query-gpu=memory.used,memory.total,temperature.gpu,utilization.gpu',
         '--format=csv,noheader,nounits'],
        capture_output=True, text=True, timeout=5
    )
    if smi.returncode == 0:
        parts = smi.stdout.strip().split(', ')
        output['gpu_info'] = {
            'vram_used_mb': int(parts[0]),
            'vram_total_mb': int(parts[1]),
            'temperature_c': int(parts[2]),
            'gpu_util_pct': int(parts[3])
        }
except Exception:
    pass

# Verificar RAM
try:
    with open('/proc/meminfo') as f:
        lines = f.readlines()
    for line in lines:
        if line.startswith('MemAvailable:'):
            avail_kb = int(line.split()[1])
            output['ram_available_mb'] = avail_kb // 1024
        elif line.startswith('SwapFree:'):
            swap_kb = int(line.split()[1])
            output['swap_free_mb'] = swap_kb // 1024
except Exception:
    pass

print(json.dumps(output, indent=2))
"
}

# ─── Warmup (descarta primeiro run) ───
if $WARMUP; then
    echo "🔥 Warmup..." >&2
    run_once > /dev/null 2>&1
    sleep 3
fi

# ─── Executar runs ───
echo "📊 Benchmark: ${REPEAT} run(s)..." >&2

ALL_RESULTS="[]"
for i in $(seq 1 "$REPEAT"); do
    echo "  Run ${i}/${REPEAT}..." >&2
    RESULT=$(run_once)

    # Salvar cada run individual
    RUN_FILE="${LOG_DIR}/$(date +%Y-%m-%d_%H-%M-%S)_run${i}.json"
    echo "$RESULT" > "$RUN_FILE"

    # Print resumo
    echo "$RESULT" | python3 -c "
import json, sys
d = json.load(sys.stdin)
gpu = d.get('gpu_info') or {}
print(f'  Run {$i}: Prefill {d[\"prompt_per_second\"]:.1f} t/s | Decode {d[\"predicted_per_second\"]:.1f} t/s | VRAM {gpu.get(\"vram_used_mb\",\"?\")}/{gpu.get(\"vram_total_mb\",\"?\")}MiB | Temp {gpu.get(\"temperature_c\",\"?\")}°C | RAM avail {d.get(\"ram_available_mb\",\"?\")}MB')
" >&2

    # Acumular para resultado consolidado
    ALL_RESULTS=$(echo "$ALL_RESULTS" | python3 -c "
import json, sys
arr = json.load(sys.stdin)
arr.append(json.loads('''${RESULT}'''))
print(json.dumps(arr))
")

    # Intervalo entre runs
    if [[ $i -lt $REPEAT ]]; then
        sleep 5
    fi
done

# ─── Salvar resultado consolidado ───
CONSOLIDATED="${LOG_DIR}/$(date +%Y-%m-%d_%H-%M-%S)_consolidated.json"
echo "$ALL_RESULTS" > "$CONSOLIDATED"

# ─── Estatísticas finais ───
echo ""
echo "$ALL_RESULTS" | python3 -c "
import json, sys

results = json.load(sys.stdin)
n = len(results)

prefills = [r['prompt_per_second'] for r in results]
decodes = [r['predicted_per_second'] for r in results]

print(f'═══ Resultado ({n} runs) ═══')
print(f'Prefill:  min={min(prefills):.1f} avg={sum(prefills)/n:.1f} max={max(prefills):.1f} t/s')
print(f'Decode:   min={min(decodes):.1f} avg={sum(decodes)/n:.1f} max={max(decodes):.1f} t/s')

if n > 1:
    drift = abs(decodes[-1] - decodes[0]) / decodes[0] * 100
    if drift > 10:
        print(f'⚠️  DRIFT: decode variou {drift:.1f}% entre primeiro e último run')
    else:
        print(f'✅ Estável: decode drift de {drift:.1f}%')

last = results[-1]
gpu = last.get('gpu_info') or {}
print(f'Último run: VRAM {gpu.get(\"vram_used_mb\",\"?\")}/{gpu.get(\"vram_total_mb\",\"?\")}MiB | Temp {gpu.get(\"temperature_c\",\"?\")}°C | RAM avail {last.get(\"ram_available_mb\",\"?\")}MB')
print(f'Logs salvos em: ${LOG_DIR}/')
print(f'Consolidado: ${CONSOLIDATED}')
"

# ─── Output JSON no stdout (para piping) ───
echo "$ALL_RESULTS"
