#!/usr/bin/env bash
# agent-heartbeat.sh — watchdog DE PROGRESSO do client-agent (16/10, dono:
# "se ngm te provocar vc fica parada"). Liveness (processo vivo) não é
# progresso (trabalho feito): este script mede PROGRESSO (commits nos
# repos da lane + queue + capturas PNG) e, se parado há >20min em horário
# ativo, injeta WAKEUP na minha janela (canal bot-a-bot p/ mim mesmo).
# Regras anti-spam (best practice): quiet 01-07h; sem WAKEUP se houve
# progresso; WAKEUP carrega ESTADO (não é "acorda", é "declare e aja").
# USO: systemd user timer a cada 10min (home.nix). Teste seco:
#   scripts/agent-heartbeat.sh --check
set -euo pipefail
IDLE_MIN="${IDLE_MIN:-20}"
HORA=$(date +%H)

# quiet hours: 01-07 (dono dorme; progresso noturno aparece nogit log)
FORCE=0; case " $* " in *" --force "*) FORCE=1;; esac
if [ "$HORA" -ge 1 ] && [ "$HORA" -lt 7 ] && [ "$FORCE" != 1 ]; then
    exit 0
fi

agora=$(date +%s)
mais_recente=0
nota=""

# 1. commits nos repos das lanes (client + server + root + nixos-ai).
#    (16/10, colega: faltava canary-official — commits server não
#    contavam como progresso.)
for repo in /home/nixos/projects/otclient /home/nixos/projects/canary-official /home/nixos/projects /home/nixos/projects/nixos-ai; do
    if [ -d "$repo/.git" ]; then
        t=$(git -C "$repo" log -1 --format=%ct 2>/dev/null || echo 0)
        if [ "$t" -gt "$mais_recente" ]; then
            mais_recente=$t
            nota="commit em $repo"
        fi
    fi
done
# 2. fila (heartbeat do turno) + capturas PNG (trabalho visual)
for f in /home/nixos/projects/AGENTS-QUEUE.md; do
    [ -f "$f" ] || continue
    t=$(stat -c %Y "$f" 2>/dev/null || echo 0)
    if [ "$t" -gt "$mais_recente" ]; then
        mais_recente=$t
        nota="queue atualizada"
    fi
done
png_novo=$(find /tmp/opencode -maxdepth 1 -name "*.png" -mmin -20 2>/dev/null | head -1 || true)
if [ -n "$png_novo" ]; then
    mais_recente=$agora
    nota="captura $png_novo"
fi

if [ "$mais_recente" -eq 0 ]; then
    echo "HEARTBEAT: sem sinal (repos?/queue?/png?) — nada a medir" >&2
    exit 0
fi

idle_min=$(( (agora - mais_recente) / 60 ))
if [ "$idle_min" -lt "$IDLE_MIN" ] && [ "$FORCE" != 1 ]; then
    case " $* " in *" --check "*) echo "HEARTBEAT: ativo há ${idle_min}min ($nota) — quieto";; esac
    exit 0
fi

case " $* " in *" --check "*) if [ "$idle_min" -ge "$IDLE_MIN" ]; then echo "HEARTBEAT: PARADO há ${idle_min}min (último: $nota) — WAKEUP iria agora"; else echo "HEARTBEAT: ativo há ${idle_min}min ($nota) — quieto"; fi;; esac
[ -n "$(echo " $* " | grep -- --check)" ] && exit 0

# 3. WAKEUP na MINHA janela (foot "OC |" SEM nsncd — regra estável 13/10;
#    com nsncd = colega; Freebuff = dono — nunca tocar).
END=$(hyprctl clients -j | python3 -c "
import json, sys
cands = [c for c in json.load(sys.stdin)
         if c.get('class') == 'foot'
         and (c.get('title') or '').startswith('OC |')
         and 'nsncd' not in (c.get('title') or '')]
if not cands:
    sys.exit(1)
print(cands[0]['address'])
") || { echo "HEARTBEAT: minha janela nao achada — sem WAKEUP" >&2; exit 0; }
hyprctl dispatch focuswindow "address:$END" >/dev/null 2>&1
sleep 1
ATUAL=$(hyprctl activewindow -j 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('address',''))" 2>/dev/null || true)
[ "$ATUAL" = "$END" ] || { echo "HEARTBEAT: foco nao pegou — sem WAKEUP" >&2; exit 0; }
wtype "[WAKEUP $(date +%H:%M)] sem progresso há ${idle_min}min (último: $nota). Declare ESTADO (working|ready|waiting-on) e tome a iniciativa (turn-taking) ou escale ao dono." || true
wtype -k Return || true
echo "HEARTBEAT: WAKEUP enviado (idle ${idle_min}min)"
