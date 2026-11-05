#!/bin/sh
# duplex-restart.sh — reinicia o cliente de voz duplex (mata TODOS os
# clientes e relança UM). Promovido do volátil /tmp/opencode/clean-restart.sh
# (24/10, lição do reboot: /tmp morre e ninguém sabia reiniciar a voz).
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

for p in $(pgrep -f "duplex-voice.py"); do kill "$p" 2>/dev/null; done
sleep 3
for p in $(pgrep -f "duplex-voice.py"); do kill -9 "$p" 2>/dev/null; done
sleep 1
setsid nohup "$(dirname "$0")/duplex-voice-run.sh" \
  --port "$PORT" --gate "$GATE" > /tmp/opencode/duplex-voice.log 2>&1 < /dev/null &
sleep 50
echo "clientes vivos: $(pgrep -f 'duplex-voice.py' | wc -l)"
grep -m1 "MODO DUPLEX" /tmp/opencode/duplex-voice.log || echo "AVISO: MODO DUPLEX não apareceu no log"
