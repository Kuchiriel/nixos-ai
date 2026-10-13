#!/usr/bin/env bash
# agent-msg-server.sh — o CANAL BOT-A-BOT do server-agent (espelho do
# agent-msg.sh do client, 12/10 noite). Foca o terminal do CLIENT por
# título ("Recuperar contexto" — a sessão opencode dele) + wtype direto
# (o protocolo de texto Wayland; o ydotool/humanize é só pro jogo).
# USO: nixos-ai/scripts/agent-msg-server.sh "mensagem"
set -eu
TEXTO="${1:?uso: agent-msg-server.sh \"mensagem\"}"
END=$(hyprctl clients -j | python3 -c "
import json, sys
for c in json.load(sys.stdin):
    if c.get('class') == 'foot' and 'Recuperar contexto' in (c.get('title') or ''):
        print(c['address']); break
else:
    sys.exit(1)
")
hyprctl dispatch focuswindow "address:$END"
sleep 1
wtype "$TEXTO"
wtype -k Return
echo "enviado p/ $END"
