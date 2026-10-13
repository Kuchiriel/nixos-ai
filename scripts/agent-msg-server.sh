#!/usr/bin/env bash
# agent-msg-server.sh — o CANAL BOT-A-BOT do server-agent (espelho do
# agent-msg.sh do client, 12/10 noite). Foca o terminal do CLIENT + wtype
# direto (protocolo de texto Wayland; ydotool/humanize é só pro jogo).
# (13/10, hardening p/ o dono: o match por título 'Recuperar contexto'
# MORRE na próxima compactação — o título muda. Regra estável: o terminal
# do CLIENTE = foot "OC |" que NÃO tem 'nsncd'; o do server-agent = o que
# tem. Complementar aos 2 terminais, sobrevive a troca de título.)
# USO: nixos-ai/scripts/agent-msg-server.sh "mensagem"
set -eu
TEXTO="${1:?uso: agent-msg-server.sh \"texto\"}"
END=$(hyprctl clients -j | python3 -c "
import json, sys
cands = [c for c in json.load(sys.stdin)
         if c.get('class') == 'foot'
         and (c.get('title') or '').startswith('OC |')
         and 'nsncd' not in (c.get('title') or '')]
if not cands:
    sys.stderr.write('terminal do CLIENTE (OC | sem nsncd) nao achado\n')
    sys.exit(1)
print(cands[0]['address'])
")
hyprctl dispatch focuswindow "address:$END"
sleep 1
wtype "$TEXTO"
wtype -k Return
echo "enviado p/ $END"
