#!/bin/bash
# llm-swap.sh — sobe o modelo do braco A/B na porta que o nightwatch espera.
#
# ── POR QUE ESTE ARQUIVO MUDOU (17/11, medido) ────────────────────────────
# O residente da casa (`duplex-voice.service`, Qwen 4B-MTP com LoRA na :8092)
# ocupa 3.886 MiB. Com ele no ar sobram ~850 MiB de VRAM, e o bonsai precisa
# de 2.600: 62 de 463 ciclos do A/B morreram em "swap falhou" e o braco
# simplesmente NAO MEDIA (o resultado era um buraco no results.jsonl).
#
# Pior: o `jarvis-heal.service` (--watch --interval 60) ressuscitava o
# duplex-voice no meio do braco, entao matar o processo nao bastava.
#
# A correcao: o A/B PEDE a GPU (takeover) por um ciclo e DEVOLVE (release)
# no fim. Se alguem estiver falando com o residente (conexao estabelecida na
# :8092), o ciclo e ADIADO — a voz do dono tem prioridade sobre o laboratorio.
#
# Uso:
#   llm-swap.sh takeover        # pausa heal + residente, espera a VRAM
#   llm-swap.sh release         # devolve a GPU (residente + heal de volta)
#   llm-swap.sh <bonsai|mtp>    # takeover implicito + sobe o braco
#   llm-swap.sh status          # VRAM, portas, residente
#   llm-swap.sh idle            # 0 = ninguem usando o residente; 1 = ocupado
set -uo pipefail

LLAMA=/home/nixos/projects/llama.cpp/build-stock/bin/llama-server
export LD_LIBRARY_PATH=/run/opengl-driver/lib:/run/current-system/sw/share/nix-ld/lib
STATE=/home/nixos/.local/state/jarvis/nightwatch
NEED=0

case "${1:-}" in
    bonsai)
        PORT=8080
        MODEL=/nix/store/nc3rnnsmz17mnhbqfry1xiw3lk5sni0x-Ternary-Bonsai-8B-Q2_0_g64.gguf
        # -ngl 30 (nao 35) + ctx/batch menores: VRAM cai de 4560 -> 2260 MiB.
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
esac

vram_used()  { nvidia-smi --query-gpu=memory.used  --format=csv,noheader,nounits 2>/dev/null | head -1; }
vram_total() { nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1; }
livre() { local u t; u=$(vram_used); t=$(vram_total); [ -z "$t" ] && t=6141; echo $((t - ${u:-0})); }

mata_portas() {
    for P in 8080 8096; do
        for PID in $(ss -ltnp 2>/dev/null | grep ":$P " | grep -oE 'pid=[0-9]+' | cut -d= -f2 | sort -u); do
            kill -9 "$PID" 2>/dev/null
        done
    done
}

# 0 = livre para o laboratorio. So conta conexao ESTABELECIDA (um cliente
# falando agora); listening nao conta.
residente_em_uso() {
    local n
    # 1) cliente falando AGORA
    n=$(ss -tnH state established 2>/dev/null | grep -cE "127\.0\.0\.1:8092\b" || true)
    [ "${n:-0}" -gt 0 ] && return 0
    # 2) serviu alguma geracao nos ultimos 3 min (o telefone fala em rajada;
    #    a conexao fecha entre turnos, entao so o ESTAB nao basta)
    if command -v journalctl >/dev/null 2>&1; then
        n=$(journalctl -u "$RES_UNIT_SYS" --since "-3 min" --no-pager 2>/dev/null | grep -c "print_timing" || true)
        [ "${n:-0}" -gt 0 ] && return 0
    fi
    return 1
}

espera_vram() {
    local preciso="$1" i u l
    for i in $(seq 1 40); do
        u=$(vram_used); l=$(livre)
        if [ "$l" -ge "$preciso" ]; then
            echo "  VRAM: ${u} usados, ${l} livres (precisa ${preciso}) apos ${i}x3s"
            return 0
        fi
        sleep 3
    done
    echo "  ERRO: VRAM insuficiente: $(livre) MiB livres, preciso ${preciso}"
    nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader 2>/dev/null | sed 's/^/    /'
    return 1
}

# ── QUEM SEGURA A VRAM (medido 17/11) ────────────────────────────────────
# O servidor da :8092 NAO e o duplex-voice: e `llama-uncensored-4b.service`,
# uma unit de SISTEMA (/system.slice). Por isso `systemctl --user stop` nunca
# o derrubava e 62 ciclos morriam em "swap falhou". Quem manda aqui e o
# systemctl de sistema (sudo -n), e o duplex (user) so consome.
RES_UNIT_SYS=llama-uncensored-4b.service
RES_UNIT_USR=duplex-voice.service

takeover() {
    mkdir -p "$STATE"
    # marca o que estava no ar, para o release restaurar o MESMO estado
    systemctl is-active --quiet "$RES_UNIT_SYS" && echo 1 > "$STATE/residente-estava" || echo 0 > "$STATE/residente-estava"
    systemctl --user is-active --quiet "$RES_UNIT_USR" && echo 1 > "$STATE/duplex-estava" || echo 0 > "$STATE/duplex-estava"
    # o self-heal (60s) ressuscitaria os servicos no meio do braco
    systemctl --user stop jarvis-heal.service 2>/dev/null || true
    systemctl --user stop "$RES_UNIT_USR" 2>/dev/null || true
    # sudo -n: se pedir senha, falha limpo em vez de pendurar o loop
    sudo -n systemctl stop "$RES_UNIT_SYS" 2>/dev/null         || systemctl stop "$RES_UNIT_SYS" 2>/dev/null         || echo "  AVISO: nao consegui parar $RES_UNIT_SYS" >&2
    mata_portas
    sleep 4
    mata_portas
    echo "  GPU tomada (heal, duplex e $RES_UNIT_SYS parados)"
}

release() {
    mata_portas
    local i
    for i in $(seq 1 20); do [ "$(livre)" -ge 800 ] && break; sleep 1; done
    if [ "$(cat "$STATE/residente-estava" 2>/dev/null || echo 1)" = "1" ]; then
        # (23/11, medido) o release apos takeover deixou a unit em
        # start-limit-hit: resetar ANTES de start evita VRAM ociosa.
        sudo -n systemctl reset-failed "$RES_UNIT_SYS" 2>/dev/null || true
        sudo -n systemctl start "$RES_UNIT_SYS" 2>/dev/null             || systemctl start "$RES_UNIT_SYS" 2>/dev/null             || echo "  AVISO: nao consegui voltar $RES_UNIT_SYS" >&2
    fi
    if [ "$(cat "$STATE/duplex-estava" 2>/dev/null || echo 1)" = "1" ]; then
        systemctl --user reset-failed "$RES_UNIT_USR" 2>/dev/null || true
        systemctl --user start "$RES_UNIT_USR" 2>/dev/null || true
    fi
    systemctl --user reset-failed jarvis-heal.service 2>/dev/null || true
    systemctl --user start jarvis-heal.service 2>/dev/null || true
    for i in $(seq 1 10); do
        [ "$(systemctl --user is-active jarvis-heal.service 2>/dev/null)" = "active" ] && break
        systemctl --user start jarvis-heal.service 2>/dev/null || true
        sleep 1
    done
    echo "  GPU devolvida (residente: $(systemctl is-active "$RES_UNIT_SYS" 2>/dev/null || echo desligado))"
}

case "${1:-}" in
    status)
        echo "VRAM livre: $(livre) MiB de $(vram_total)"
        nvidia-smi --query-compute-apps=pid,used_memory --format=csv,noheader 2>/dev/null | sed 's/^/  /'
        ss -ltnp 2>/dev/null | grep -E ":80(80|92|95|96) " | sed 's/^/  /'
        echo "residente em uso: $(residente_em_uso && echo sim || echo nao)"
        echo "unidades: $RES_UNIT_SYS=$(systemctl is-active $RES_UNIT_SYS 2>/dev/null) $RES_UNIT_USR=$(systemctl --user is-active $RES_UNIT_USR 2>/dev/null)"
        exit 0 ;;
    idle)
        residente_em_uso && exit 1 || exit 0
        ;;
    takeover)
        takeover; rc=$?; espera_vram 1200 || rc=1; exit $rc ;;
    release)
        release; exit 0 ;;
    ""|-h|--help)
        echo "uso: llm-swap.sh <bonsai|mtp|takeover|release|status|idle>"; exit 2 ;;
esac

if [ ! -f "$MODEL" ]; then
    echo "  ERRO: modelo ausente: $MODEL" >&2
    exit 1
fi

takeover
espera_vram "$NEED" || exit 1

# sobe o servidor (com 1 retry se o load estourar VRAM na corrida)
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
            echo "  $1 pronto na porta $PORT (${i}x3s) — VRAM: $(vram_used) MiB"
            exit 0
        fi
        kill -0 "$NEW_PID" 2>/dev/null || break
    done

    echo "  $1 nao respondeu; ultimas linhas do log:"
    tail -3 "/home/nixos/logs/llm-$1.log" 2>/dev/null | cut -c1-140 | sed 's/^/    /'
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
