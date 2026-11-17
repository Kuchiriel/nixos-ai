#!/bin/bash
# llm-swap.sh <modelo> — sobe o modelo pedido na porta que o nightwatch espera
# (bonsai -> 8080, mtp -> 8096). So um cabe na VRAM por vez (6 GB), entao
# cada troca mata o anterior, ESPERA a VRAM liber (a memoria CUDA so volta
# depois que o processo morre de vez) e sobe o novo.
set -uo pipefail

LLAMA=/home/nixos/projects/llama.cpp/build-stock/bin/llama-server
export LD_LIBRARY_PATH=/run/opengl-driver/lib:/run/current-system/sw/share/nix-ld/lib

case "${1:-}" in
    bonsai)
        PORT=8080
        MODEL=/nix/store/nc3rnnsmz17mnhbqfry1xiw3lk5sni0x-Ternary-Bonsai-8B-Q2_0_g64.gguf
        # -ngl 30 (nao 35) + ctx/batch menores: VRAM cai de 4560 -> 2260 MiB e
        # ainda sobra espaco pros servicos da casa (reranker :8082, embeddings
        # :8081, whisper :8097 = ~1,4 GB). Medido 16/11.
        NEED=2600
        ARGS="-ngl 30 -t 6 -c 4096 -b 64 -ub 64"
        ;;
    mtp)
        PORT=8096
        MODEL=/var/lib/ai/models/Qwen3.5-4B-MTP-Q4_K_M.gguf
        # ctx 12288: o patcher precisa caber (o LoRA dava timeout em 4k)
        NEED=3600
        ARGS="-ngl 99 -t 6 -c 12288 -b 128 -ub 128 -fa off -ctk f16 -ctv f16"
        ;;
    *)
        echo "uso: llm-swap.sh <bonsai|mtp>" >&2
        exit 2
        ;;
esac

vram_used() {
    nvidia-smi --query-gpu=memory.used --format=csv,noheader,nounits 2>/dev/null | head -1
}
vram_total() {
    nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1
}

mata_portas() {
    for P in 8080 8096; do
        for PID in $(ss -ltnp 2>/dev/null | grep ":$P " | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u); do
            kill -9 "$PID" 2>/dev/null
        done
    done
}

if [ ! -f "$MODEL" ]; then
    echo "  ERRO: modelo ausente: $MODEL" >&2
    exit 1
fi

TOTAL=$(vram_total)
[ -z "$TOTAL" ] && TOTAL=6141

# 1) mata por PID (nunca pkill -f: casa com o shell).
#    SIGKILL direto: o llama-server finishes a geracao antes de sair no
#    SIGTERM, e isso custava ~100s de espera de VRAM por swap (medido 16/11).
mata_portas
sleep 4
mata_portas

# 2) espera a VRAM VOLTAR. A memoria CUDA do processo morto so e devolvida
#    quando ele realmente sai — sem essa espera o novo modelo falha com
#    "unable to allocate CUDA0 buffer" (medido 16/11).
ESPEROU=0
for i in $(seq 1 40); do
    U=$(vram_used)
    [ -z "$U" ] && U=0
    LIVRE=$((TOTAL - U))
    if [ "$LIVRE" -ge "$NEED" ]; then
        echo "  VRAM: ${U} MiB usados, ${LIVRE} MiB livres (precisa ${NEED}) apos ${i}x3s"
        break
    fi
    sleep 3
    ESPEROU=$((ESPEROU + 3))
done

U=$(vram_used); [ -z "$U" ] && U=0
LIVRE=$((TOTAL - U))
if [ "$LIVRE" -lt "$NEED" ]; then
    echo "  ERRO: VRAM insuficiente: ${LIVRE} MiB livres, preciso ${NEED}"
    nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader 2>/dev/null | sed 's/^/    /'
    exit 1
fi

# 3) sobe o servidor (com 1 retry se o load estourar VRAM na corrida)
TENT=1
while [ "$TENT" -le 2 ]; do
    nohup "$LLAMA" -m "$MODEL" --host 127.0.0.1 --port "$PORT" $ARGS \
        > "/home/nixos/logs/llm-$1.log" 2>&1 &
    NEW_PID=$!
    echo "  servidor $1: pid=$NEW_PID porta=$PORT (tentativa $TENT)"

    for i in $(seq 1 70); do
        sleep 3
        CODE=$(timeout 8 curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/v1/models" 2>/dev/null)
        if [ "$CODE" = "200" ]; then
            echo "  $1 pronto na porta $PORT (${i}x3s)"
            echo "  VRAM: $(vram_used) MiB usados"
            exit 0
        fi
        if ! kill -0 "$NEW_PID" 2>/dev/null; then
            break
        fi
    done

    echo "  $1 nao respondeu; ultimas linhas do log:"
    tail -3 "/home/nixos/logs/llm-$1.log" | cut -c1-140 | sed 's/^/    /'
    if [ "$TENT" -eq 1 ]; then
        echo "  retentando em 20s (deixa a VRAM assentar)"
        sleep 20
        mata_portas
        sleep 8
    fi
    TENT=$((TENT + 1))
done

echo "  ERRO: $1 nao subiu na porta $PORT"
exit 1
