#!/bin/sh
# duplex-restart.sh — reinicia o cliente de voz duplex.
#
# (19/11/2026, auditoria-runtime) O DONO DO PROCESSO PASSA A SER O SYSTEMD.
# O script antigo matava os clientes por PATTERN (pgrep -f duplex-voice.py) e
# relançava um cliente ÓRFÃO (setsid nohup). Medido hoje: o unit
# duplex-voice.service started 07:57:12 e, 15 s depois, o proprio systemd
# registrou "Stopping ... duplex-voice.service" — quem matou o cliente foi
# este script (ele matava o processo que a unit supervisionava). Resultado
# medido: `systemctl status duplex-voice` = inactive (dead) e a voz fora,
# enquanto o cliente relançado ficava sem dono, sem restart e sem log no
# journal.
#
# AGORA:
#   - porta/gate PADRÃO (:8092, gate intent) -> `systemctl --user restart
#     duplex-voice.service`: o systemd e' o dono unico (restart, log no
#     journal, estado no `systemctl status`).
#   - porta/gate CUSTOM -> transient unit supervisionada (`systemd-run
#     --user --collect`), nunca um processo órfão.
#   - o guard anti-zumbi (backend :PORT morto) continua: nao se relança
#     cliente apontando para servidor morto (incidente 24/10 04:03).
#
# USO: duplex-restart.sh [--port N] [--gate intent|jarvis|on|off] [--force]
#   --port   porta do llama-server da voz (default 8092 = llama-uncensored-4b)
#   --gate   gate do turno (mesmos valores do duplex-voice.py):
#            intent = endereço OU intenção QUESTION/COMMAND (default 03/11;
#            recall 92,3% no bench) · jarvis/on = só a palavra "Jarvis"
#            (estrito, anti-TV) · off = responde TODO segmento (testes/AFK)
#   --force  relança mesmo com backend morto (estado zumbi — evitado por padrão)
#
# EXEMPLOS:
#   duplex-restart.sh                     # default: :8092, gate intent
#   duplex-restart.sh --gate jarvis       # modo-TV (estrito)
#   duplex-restart.sh --gate off          # testes/AFK
#
# CONTRATO: recusa relançar com o backend LLM morto (zumbi: cliente vivo
# apontando pra :8092 morto, incidente 24/10 04:03) a menos que --force;
# sugere o systemctl start quando o backend está caído.
set -u
PORT=8092
GATE=intent
FORCE=0
UNIT=duplex-voice.service
HERE="$(dirname "$0")"
while [ $# -gt 0 ]; do
    case "$1" in
        --port) PORT="$2"; shift 2 ;;
        --gate) GATE="$2"; shift 2 ;;
        --force) FORCE=1; shift ;;
        *) shift ;;
    esac
done

# (24/10) GUARD: cliente vivo com backend morto = zumbi mudo.
if [ "$FORCE" -eq 0 ] && \
   ! curl -s --max-time 3 "http://127.0.0.1:$PORT/v1/models" | grep -q model; then
    echo "duplex-restart: backend :$PORT MORTO — relançar criaria cliente zumbi." >&2
    echo "  Suba primeiro: sudo systemctl start llama-uncensored-4b.service" >&2
    echo "  (ou use --force se souber o que faz)" >&2
    exit 1
fi

# (19/11) ORFAO LEGADO: o script antigo relançava o cliente com setsid nohup.
# Se sobrou algum desses (sem unit, sem dono), ele precisa sair antes: dois
# clientes = duas respostas e dois falantes no mesmo FIFO. Mata por PID
# exato (nunca pkill -f com o proprio padrao na linha do comando).
for p in $(pgrep -f "scripts/duplex-voice.py" 2>/dev/null); do
    [ "$p" = "$$" ] && continue
    kill "$p" 2>/dev/null
done
sleep 2

if [ "$PORT" = "8092" ] && [ "$GATE" = "intent" ]; then
    # CAMINHO CANONICO: o systemd e' o dono. A unit roda o mesmo
    # duplex-voice-run.sh e o mesmo duplex-voice.py com os defaults.
    if ! systemctl --user restart "$UNIT" 2>&1; then
        echo "duplex-restart: falha no restart de $UNIT" >&2
        exit 1
    fi
    ok=0
    i=0
    while [ "$i" -lt 60 ]; do
        if journalctl --user -u "$UNIT" -n 80 --no-pager 2>/dev/null \
             | grep -q "MODO DUPLEX"; then
            ok=1
            break
        fi
        sleep 1
        i=$((i + 1))
    done
    echo "unit $UNIT: $(systemctl --user is-active "$UNIT" 2>/dev/null)"
    echo "clientes vivos: $(pgrep -f 'scripts/duplex-voice.py' 2>/dev/null | wc -l)"
    if [ "$ok" -eq 1 ]; then
        echo "voz no ar (MODO DUPLEX confirmado no journal de $UNIT)"
    else
        echo "AVISO: MODO DUPLEX não apareceu em 60s — journalctl --user -u $UNIT -n 40" >&2
        exit 1
    fi
    exit 0
fi

# PARAMETROS CUSTOM: transient unit supervisionada (systemd-run --collect).
# Nada de setsid nohup: processo órfão não tem restart, não tem log no
# journal e não aparece no status.
TRANSIENT="duplex-voice-custom-$(date +%H%M%S)"
if systemd-run --user --unit="$TRANSIENT" --collect \
     --property=WorkingDirectory="$HOME/projects/nixos-ai" \
     "$HERE/duplex-voice-run.sh" --port "$PORT" --gate "$GATE" >/dev/null 2>&1; then
    echo "duplex-restart: transient unit $TRANSIENT criada (:$PORT, gate=$GATE)"
    echo "  para derrubar: systemctl --user stop $TRANSIENT"
else
    echo "duplex-restart: falha ao criar a transient unit $TRANSIENT" >&2
    exit 1
fi
sleep 20
echo "clientes vivos: $(pgrep -f 'scripts/duplex-voice.py' 2>/dev/null | wc -l)"
