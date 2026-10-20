#!/usr/bin/env bash
# agent-msg.sh — O CANAL BOT-A-BOT via desktop (consolidado 17/10, dono:
# "o script de comunicação entre IAs deve fazer parte do sistema": os
# espelhos otclient/tools/agent-msg.sh + agent-msg-server.sh viram ESTE
# script único; canônico no sistema do watcher, nixos-ai/scripts).
#
# COMO: hyprctl focusa o terminal do alvo → wtype (protocolo de texto
# Wayland, instantâneo, zero keycodes — humanize/ydotool NÃO: o per-char
# é lento ~60s/msg e o ydotool já corrompeu teclas com '--delay 12') →
# Return. VERIFICA o foco antes de digitar (16/10, dono: "mandou pra vc
# mesmo" — sem o check o wtype cai na janela antiga). No fim REFOCA a
# minha janela (cortesia + anti-confusão do dono).
#
# ALVOS (agnóstico — funciona pra N agentes, sem convenção de título):
#   --to other  (default) TODAS as janelas "OC |" EXCETO a minha própria
#                (a minha = walk ppid até o pid do meu foot; se o chamador
#                não vive num foot OC |, use --to explícito)
#   --to all    todas as janelas "OC |"
#   --to nsncd  legado: janela "OC |" COM 'nsncd' no título (server-agent)
#   --to plain  legado: janela "OC |" SEM 'nsncd' (client-agent)
#   --list      só lista os alvos (dry-run, NÃO digita nada)
#
# USO:   agent-msg.sh [--to other|all|nsncd|plain] [--list] "texto"
# PROVA: 12/10 ping/confirmations client↔server; 17/10 unificação.
set -eu
PATH="$HOME/.nix-profile/bin:/run/current-system/sw/bin:$PATH"

MODO="other"; LISTAR=0; TEXTO=""
while [ $# -gt 0 ]; do
    case "$1" in
        --to)   MODO="${2:?--to precisa de other|all|nsncd|plain}"; shift 2 ;;
        --to=*) MODO="${1#--to=}"; shift ;;
        --list) LISTAR=1; shift ;;
        -h|--help) sed -n '2,22p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) TEXTO="$1"; shift ;;
    esac
done

# resolve os alvos: JANELA-AGENTE = foot com um opencode TUI vivo como
# descendente (17/10: título era frágil — sessão morta mantém título,
# viva sem título fica invisível; process-tree = agnóstico de verdade)
mapfile -t ALVOS < <(python3 - "$MODO" <<'PYEOF'
import json, os, subprocess, sys
modo = sys.argv[1]
ppid_de, agente = {}, {}
for d in os.scandir('/proc'):
    if not d.name.isdigit():
        continue
    pid = int(d.name)
    try:
        stat = open(f'/proc/{pid}/stat').read().rsplit(')', 1)[1].split()
        ppid_de[pid] = int(stat[1])
        if b'opencode' in open(f'/proc/{pid}/cmdline','rb').read():
            agente[pid] = True
    except Exception:
        pass
def descendentes(root):
    pids, frontier = [root], [root]
    while frontier:
        nxt = [p for p in ppid_de
               if ppid_de[p] in frontier and p not in pids]
        pids += nxt
        frontier = nxt
    return pids
try:
    foots = json.loads(subprocess.run(['hyprctl','clients','-j'],
            capture_output=True, text=True).stdout)
except Exception:
    sys.exit(1)
cands = [c for c in foots
         if c.get('class') == 'foot'
         and any(agente.get(p) for p in descendentes(c.get('pid', 0)))]

meu_pid = None
if modo in ('other', 'all'):
    p = os.getppid()
    pids = {c['pid'] for c in cands}
    while p > 1:
        if p in pids:
            meu_pid = p
            break
        p = ppid_de.get(p, 0)

if modo == 'other':
    if meu_pid is None:
        sys.stderr.write("agent-msg: chamador não vive numa janela-agente (foot com opencode) — use --to all|nsncd|plain\n")
        sys.exit(2)
    alvos = [c['address'] for c in cands if c['pid'] != meu_pid]
elif modo == 'all':
    alvos = [c['address'] for c in cands]
elif modo == 'nsncd':
    alvos = [c['address'] for c in cands if 'nsncd' in (c.get('title') or '')][:1]
elif modo == 'plain':
    alvos = [c['address'] for c in cands if 'nsncd' not in (c.get('title') or '')][:1]
else:
    sys.stderr.write(f"agent-msg: modo inválido '{modo}'\n")
    sys.exit(2)
print('\n'.join(alvos))
PYEOF
) || { echo "agent-msg: nenhum alvo (modo=$MODO)" >&2; exit 3; }
[ "${#ALVOS[@]}" -gt 0 ] || { echo "agent-msg: nenhum alvo (modo=$MODO)" >&2; exit 3; }
[ -n "${ALVOS[0]}" ] || { echo "agent-msg: nenhum alvo (modo=$MODO)" >&2; exit 3; }

if [ "$LISTAR" -eq 1 ]; then
    printf 'alvos (%s):\n' "$MODO"
    printf '  %s\n' "${ALVOS[@]}"
    exit 0
fi
[ -n "$TEXTO" ] || { echo 'uso: agent-msg.sh [--to other|all|nsncd|plain] [--list] "texto"' >&2; exit 1; }

# o endereço da MINHA janela (p/ refocar no fim)
MINHA=$(hyprctl activewindow -j 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('address',''))" 2>/dev/null || true)

# LOG (20/10, aval mútuo HB+OC — melhoria #2): auditoria pós-compact —
# correlaciona com as notas da fila; $JARVIS_AGENT_NAME identifica o remetente.
for END in "${ALVOS[@]}"; do
    hyprctl dispatch focuswindow "address:$END"
    sleep 1
    ATUAL=$(hyprctl activewindow -j 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('address',''))" 2>/dev/null || true)
    if [ "$ATUAL" != "$END" ]; then
        echo "agent-msg: FOCO NAO PEGOU (alvo=$END atual=$ATUAL) — nada digitado" >&2
        continue
    fi
    wtype "$TEXTO"
    wtype -k Return
    echo "enviado p/ $END"
    printf '%s %s->%s: %s\n' "$(date '+%d/%m %H:%M')" \
        "${JARVIS_AGENT_NAME:-?}" "${END:-?}" "${TEXTO:0:100}" \
        >> "$HOME/projects/AGENTS-MSG.log"
done

[ -n "$MINHA" ] && hyprctl dispatch focuswindow "address:$MINHA" >/dev/null 2>&1 || true
