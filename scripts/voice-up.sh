#!/bin/sh
# voice-up.sh — ERGUE A LANE DE VOZ em 1 comando (sequência sancionada
# 24/10: router OFF → 4B :8092 UP → duplex client). O caminho antigo
# ("hey jarvis acordar") morreu com o wakeword aposentado (21/10) —
# pós-reboot a voz precisava de 3 comandos manuais que ninguém decora.
#
# USO: voice-up.sh [--router-off]
#   --router-off  para ANTES o llama-cpp-server (bonsai 4.3GB) — os dois
#                 NÃO cabem no GPU 6GB; o stop é DECISÃO do dono (default:
#                 NÃO para, só avisa se faltar VRAM).
#
# CONTRATO: idempotente (4B já vivo = só relança o cliente); o
# duplex-restart.sh embutido tem guard anti-zumbi (recusa cliente com
# backend morto); VRAM insuficiente = mensagem clara, não cryptico.
# ⚠️ RISCO CONHECIDO: o proxy :8080 (llama-cpp-server) pode ser reerguido
# por qualquer `systemctl start jarvis.target` (comandos jarvis CLI o
# fazem). Proxy leve = inofensivo; MAS um request chat bonsai spawn
# 4.3GB SOBRE o 4B da voz → OOM do request. Regra da era da voz: nada de
# jarvis chat/:8080 sem coordenar (v. queue 24/10 13:58).
set -u
ROUTER_OFF=0
[ "${1:-}" = "--router-off" ] && ROUTER_OFF=1

# (idempotência REAL: 4B vivo → VRAM irrelevante, direto ao cliente)
ALREADY_UP=0
curl -s --max-time 3 http://127.0.0.1:8092/v1/models | grep -q model && ALREADY_UP=1

SMI=/run/current-system/sw/bin/nvidia-smi
FREE=$("$SMI" --query-gpu=memory.free --format=csv,noheader,nounits 2>/dev/null | head -1)
FREE=${FREE:-0}

if [ "$ALREADY_UP" -eq 0 ] && [ "$FREE" -lt 4000 ]; then
    if [ "$ROUTER_OFF" -eq 1 ]; then
        echo "voice-up: VRAM livre ${FREE}MiB < 4000 — parando o router (decisão --router-off)..."
        sudo -n systemctl stop llama-cpp-server.service || {
            echo "voice-up: falhou o stop do router (sudo). Pare manualmente e rerode." >&2
            exit 1; }
        sleep 5
    else
        echo "voice-up: VRAM livre ${FREE}MiB < 4000 (4B precisa ~4000)." >&2
        echo "  Router bonsai segurando a GPU? Decisão do dono:" >&2
        echo "  voice-up.sh --router-off   (para o router e sobe a voz)" >&2
        echo "  (jarvis chat CLI fica sem bonsai até trocar de volta)" >&2
        exit 1
    fi
fi

if ! curl -s --max-time 3 http://127.0.0.1:8092/v1/models | grep -q model; then
    echo "voice-up: subindo llama-uncensored-4b (:8092)..."
    sudo -n systemctl start llama-uncensored-4b.service || {
        echo "voice-up: falhou o start (sudo?). Manual: sudo systemctl start llama-uncensored-4b" >&2
        exit 1; }
    for i in $(seq 1 20); do
        curl -s --max-time 2 http://127.0.0.1:8092/v1/models | grep -q model && break
        sleep 2
    done
    curl -s --max-time 3 http://127.0.0.1:8092/v1/models | grep -q model || {
        echo "voice-up: 4B não respondeu em 40s — journalctl -u llama-uncensored-4b" >&2
        exit 1; }
else
    echo "voice-up: 4B já vivo (:8092)."
fi

exec "$(dirname "$0")/duplex-restart.sh" "$@"
