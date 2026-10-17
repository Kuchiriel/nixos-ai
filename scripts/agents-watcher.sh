#!/usr/bin/env bash
# agents-watcher.sh — O WATCHER ÚNICO dos agentes (17/10, dono: "consolide
# tudo em um script e um serviço só... precisa ser agnóstico de projeto,
# funcionar em qualquer um"). Substitui 4 peças: tools/agents-watcher.sh
# (v2, CPU-delta working/idle), tools/tem-novo.sh (detector de eventos),
# nixos-ai/scripts/agent-heartbeat.sh (progress-heartbeat) e o
# agent-keepawake (hypridle.nix). O systemd (Restart=always) É o watchdog
# — os timers de reanimação morreram com a consolidação.
#
# AGNÓSTICO: zero repos/canais/projetos hardcodados no núcleo. A raiz
# observada é uma config; o específico do projeto entra por ARQUIVOS
# OPCIONAIS (crie os mesmos nomes em qualquer raiz e funciona):
#
#   $ROOT/AGENTS-QUEUE.md                     blackboard (evento na mudança)
#   $ROOT/tools/agents-watcher-hooks.sh       eventos do projeto (contrato
#                                            abaixo; ex.: docker, bridges)
#   $ROOT/tools/agents-watcher-prospects.txt  alvos de prospecção, 1/linha
#
# ENV (todos opcionais):
#   AGENTS_ROOT       raiz observada             (default ~/projects)
#   AGENTS_QUEUE      caminho do blackboard      (default $ROOT/AGENTS-QUEUE.md)
#   AGENTS_HOOKS      hooks do projeto           (default $ROOT/tools/agents-watcher-hooks.sh)
#   AGENTS_PROSPECTS  prospecções                (default $ROOT/tools/agents-watcher-prospects.txt)
#   AGENTS_NOTIFY     cmd de notificação         (default $ROOT/team/tg.sh post; vazio = cala)
#   AGENTS_INTERVAL   seg/ciclo                  (default 150; argv[1] ganha)
#   AGENTS_GIT_DEPTH  profundidade do find .git  (default 2)
#   AGENTS_CPU_LIMIT  ticks/ciclo = working      (default 2500 — calibrado
#                                              13/10: idle c/ ruído ~1541/5min,
#                                              trabalho real 3604-12800;
#                                              bug v1: 2 = todos 'working')
#   AGENTS_RATE_MIN   seg mínimos entre wakes do mesmo agente (default 180)
#   AGENTS_FALLBACK   seg de idle → prospecção   (default 900)
#   AGENTS_PROSPECT_COOLDOWN  cooldown por alvo de prospecção (default 14400)
#   AGENTS_QUIET      horas caladas "DE ATE"     (default "1 7"; "0 0" = 24h)
#
# CONTRATO DOS HOOKS (executado 1x/ciclo, stderr ignorado, deve ser +x):
#   linha "chave valor..."  → evento quando o VALOR mudar vs ciclo anterior
#   linha "!chave valor..." → evento ENQUANTO existir (alarme persistente:
#                             dispara todo ciclo até sumir)
#   primeira execução = BASELINE (silêncio absoluto, registra o estado)
#
# SEMÂNTICA (provada na v2, preservada):
#   WORKING (CPU alta) NUNCA é interrompido; IDLE só acorda com evento
#   novo, prospecção rotativa (fallback) ou deadlock-check; eventos são
#   consume-uma-vez por CICLO (todos os idle do ciclo veem, o próximo
#   não); rate-limit por agente; horas quietas = sem wakes (o keepawake
#   segue 24h — agentes vivos = máquina não suspende).
#
# USO:
#   agents-watcher.sh [intervalo]   loop infinito (o systemd roda isto)
#   agents-watcher.sh --once        um ciclo e sai (teste manual)
#   agents-watcher.sh --check       relatório dry-run SEM acordar ninguém
#                                   (não consome estado, não escreve nada)
set -u
PATH="$HOME/.nix-profile/bin:/run/current-system/sw/bin:$PATH"

RAIZ="${AGENTS_ROOT:-$HOME/projects}"
QUEUE="${AGENTS_QUEUE:-$RAIZ/AGENTS-QUEUE.md}"
HOOKS="${AGENTS_HOOKS:-$RAIZ/tools/agents-watcher-hooks.sh}"
PROSPECTS="${AGENTS_PROSPECTS:-$RAIZ/tools/agents-watcher-prospects.txt}"
NOTIFY="${AGENTS_NOTIFY:-}"
[ -z "$NOTIFY" ] && [ -x "$RAIZ/team/tg.sh" ] && NOTIFY="$RAIZ/team/tg.sh post"
DEPTH="${AGENTS_GIT_DEPTH:-2}"
LIMITE_CPU="${AGENTS_CPU_LIMIT:-2500}"
RATE_MIN="${AGENTS_RATE_MIN:-180}"
FALLBACK="${AGENTS_FALLBACK:-900}"
COOLDOWN="${AGENTS_PROSPECT_COOLDOWN:-14400}"
read -r QUIET_DE QUIET_ATE <<< "${AGENTS_QUIET:-1 7}"

INTERVALO="${AGENTS_INTERVAL:-150}"
ONCE=0; CHECK=0
for a in "$@"; do
    case "$a" in
        --once)  ONCE=1 ;;
        --check) CHECK=1 ;;
        *[!0-9]*|'') ;;
        *) INTERVALO="$a" ;;
    esac
done

DIR_ST="${TMPDIR:-/tmp}/opencode/agents-watcher"; mkdir -p "$DIR_ST"
# estado por raiz observada: trocar AGENTS_ROOT NÃO dispara falsos "novo:"
STATE="$DIR_ST/snapshot.$(printf '%s' "$RAIZ" | md5sum | cut -c1-8).state"
INHIBIT_PID=""

notifica() { [ -n "$NOTIFY" ] && "$NOTIFY" "$1" >/dev/null 2>&1 || true; }
log()      { echo "$(date '+%H:%M:%S') $*"; [ "$CHECK" -eq 1 ] || echo "$(date '+%H:%M:%S') $*" >> "$DIR_ST/states"; }

# descobre os terminais OC + pids dos processos opencode de cada um
# (descendentes via /proc — pstree NÃO EXISTE no NixOS; walk ppid)
mapa_agentes() {
    python3 2>/dev/null <<'PYEOF'
import json, os, subprocess
def descendentes(root):
    pids, frontier = [root], [root]
    while frontier:
        nxt = []
        for d in os.scandir('/proc'):
            if not d.name.isdigit():
                continue
            try:
                stat = open(f'/proc/{d.name}/stat').read().rsplit(')', 1)[1].split()
                if int(stat[1]) in frontier:  # ppid
                    nxt.append(int(d.name))
            except Exception:
                pass
        pids += nxt
        frontier = nxt
    return pids
for c in json.loads(subprocess.run(['hyprctl','clients','-j'],
        capture_output=True, text=True).stdout):
    if c.get('class') != 'foot' or not (c.get('title') or '').startswith('OC |'):
        continue
    cpu = 0
    for pid in descendentes(c.get('pid', 0)):
        try:
            parts = open(f'/proc/{pid}/stat').read().rsplit(')', 1)[1].split()
            cpu += int(parts[11]) + int(parts[12])
        except Exception:
            pass
    print(f"{c['address']} {c['pid']} {cpu}")
PYEOF
}

# O SNAPSHOT (o antigo tem-novo.sh, genérico): commits de TODOS os repos
# git sob a raiz + queue + hooks do projeto. Silêncio = estado igual.
snapshot_atual() {
    find "$RAIZ" -maxdepth "$DEPTH" -name .git 2>/dev/null | sort | while read -r g; do
        r=$(dirname "$g")
        printf 'commit:%s %s\n' "${r##*/}" "$(git -C "$r" log -1 --format=%h 2>/dev/null)"
    done
    [ -f "$QUEUE" ] && printf 'queue %s\n' "$(md5sum "$QUEUE" 2>/dev/null | cut -d' ' -f1)"
    [ -x "$HOOKS" ] && "$HOOKS" 2>/dev/null
    true
}

# diff dos snapshots: "!chave" dispara enquanto existir; "chave" só na
# mudança/primeira aparição pós-baseline.
diff_eventos() {
    awk '
        NR==FNR { velho[$1] = $0; next }
        /^!/    { sub(/^!/, "ALERTA "); print; next }
        $1 == "" { next }
        !($1 in velho) { print "novo: "  $0; next }
        velho[$1] != $0 { print "mudou: " $0 }
    ' "$1" "$2"
}

hora_quieta() {
    [ "$QUIET_DE" -eq "$QUIET_ATE" ] && return 1
    local h; h=$(date +%H)
    if [ "$QUIET_DE" -lt "$QUIET_ATE" ]; then
        [ "$h" -ge "$QUIET_DE" ] && [ "$h" -lt "$QUIET_ATE" ]
    else
        { [ "$h" -ge "$QUIET_DE" ] || [ "$h" -lt "$QUIET_ATE" ]; }
    fi
}

# KEEPAWAKE (o antigo agent-keepawake, mesclado): lock sleep:idle enquanto
# houver agente vivo; um lock por vez (expira sozinho ≤4min após o último).
keepawake() {
    pgrep -u "$USER" -f '[o]pencode|[f]reebuff|[b]uffy' >/dev/null 2>&1 || return 0
    if [ -n "$INHIBIT_PID" ] && kill -0 "$INHIBIT_PID" 2>/dev/null; then
        return 0
    fi
    systemd-inhibit --what=sleep:idle --who=agents --mode=block \
        --why="agentes de IA ativos" sleep 240 >/dev/null 2>&1 &
    INHIBIT_PID=$!
}

# um ciclo do watcher
ciclo() {
    local AGORA AGORA_E ACHADO_CICLO ANTES
    AGORA=$(date +%H:%M); AGORA_E=$(date +%s)
    [ "$CHECK" -eq 1 ] || keepawake

    snapshot_atual > "$DIR_ST/snapshot.agora"
    # raiz sem repos/queue/hooks: sentinela estável (nunca vira evento,
    # só impede re-baseline infinito)
    [ -s "$DIR_ST/snapshot.agora" ] || echo "raiz-sem-sinais" > "$DIR_ST/snapshot.agora"
    ANTES=$(cat "$STATE" 2>/dev/null || true)
    if [ -z "$ANTES" ]; then
        [ "$CHECK" -eq 1 ] || cp "$DIR_ST/snapshot.agora" "$STATE"
        ACHADO_CICLO=""
        log "BASELINE registrado (o próximo ciclo compara)"
    else
        ACHADO_CICLO=$(diff_eventos "$STATE" "$DIR_ST/snapshot.agora")
        [ "$CHECK" -eq 1 ] || cp "$DIR_ST/snapshot.agora" "$STATE"
    fi

    mapa_agentes > "$DIR_ST/mapa.agora"
    if [ ! -s "$DIR_ST/mapa.agora" ]; then
        log "sem janelas OC | — ciclo silencioso"
    fi
    while read -r END FOOTPID CPU; do
        [ -z "${END:-}" ] && continue
        CHAVE="$FOOTPID"
        ANTIGO=$(cat "$DIR_ST/cpu.$CHAVE" 2>/dev/null || echo "$CPU")
        DELTA=$(( CPU - ANTIGO ))
        [ "$CHECK" -eq 1 ] || echo "$CPU" > "$DIR_ST/cpu.$CHAVE"
        if [ "$DELTA" -ge "$LIMITE_CPU" ]; then
            log "working delta=$DELTA end=$END"
            continue   # WORKING: NUNCA interromper
        fi
        # IDLE — decide se acorda
        if [ ! -f "$DIR_ST/wake.$CHAVE" ]; then
            # primeira vista deste agente: considera "agora acordado" —
            # não dispara fallback de idle imediato (evita IDLE=epoch)
            ULT_WAKE="$AGORA_E"
            [ "$CHECK" -eq 1 ] || date +%s > "$DIR_ST/wake.$CHAVE"
        else
            ULT_WAKE=$(cat "$DIR_ST/wake.$CHAVE")
        fi
        IDLE_SEGS=$(( AGORA_E - ULT_WAKE ))
        MOTIVO=""
        [ -n "$ACHADO_CICLO" ] && [ "$IDLE_SEGS" -ge "$RATE_MIN" ] && MOTIVO="$ACHADO_CICLO"
        # IDLE-PROSPECÇÃO: sem acontecimento, agente parado = desperdiçado.
        # Rotação com cooldown por alvo (anti-mirror-loop); todos frios =
        # DEADLOCK-CHECK. Sem arquivo de prospecção = deadlock-check direto.
        if [ -z "$MOTIVO" ] && [ "$IDLE_SEGS" -ge "$FALLBACK" ]; then
            ESCOLHIDO=""
            if [ -s "$PROSPECTS" ]; then
                mapfile -t PROS < "$PROSPECTS"
                if [ "${#PROS[@]}" -gt 0 ]; then
                    IDX=$(cat "$DIR_ST/prospect.idx" 2>/dev/null || echo 0)
                    for _try in "${!PROS[@]}"; do
                        _i=$(( (IDX + _try) % ${#PROS[@]} ))
                        _last=$(cat "$DIR_ST/prospect.$_i.last" 2>/dev/null || echo 0)
                        if [ $(( AGORA_E - _last )) -ge "$COOLDOWN" ]; then
                            ESCOLHIDO="$_i"; break
                        fi
                    done
                    if [ -n "$ESCOLHIDO" ]; then
                        [ "$CHECK" -eq 1 ] || { echo "$ESCOLHIDO" > "$DIR_ST/prospect.idx"; date +%s > "$DIR_ST/prospect.$ESCOLHIDO.last"; }
                        MOTIVO="${PROS[$ESCOLHIDO]}"
                    fi
                fi
            fi
            [ -z "$MOTIVO" ] && MOTIVO="DEADLOCK-CHECK: declare em 1 linha ESTADO (working X | ready Y | waiting-on Z). Waiting-on colega >10min = tome a iniciativa (turn-taking): proponha divisão concreta e COMECE sua parte AGORA; sem material próprio = PESQUISA na internet E LEIA os fontes do projeto — ache o próximo sistema a trabalhar e COMEÇE. Nunca espere calado."
        fi
        if [ "$CHECK" -eq 1 ]; then
            echo "CHECK: end=$END idle=${IDLE_SEGS}s delta=$DELTA motivo='${MOTIVO:-(nenhum)}'"
            continue
        fi
        [ -z "$MOTIVO" ] && { log "idle-quiet delta=$DELTA end=$END"; continue; }
        if hora_quieta; then
            log "quiet ${QUIET_DE}h-${QUIET_ATE}h (wake suprimido) end=$END"
            continue
        fi
        hyprctl dispatch focuswindow "address:$END" >/dev/null 2>&1
        wtype "[WATCHER $AGORA] $MOTIVO. Conf. mutuas AUTORIZADAS. 1 linha de acao."
        wtype -k Return
        date +%s > "$DIR_ST/wake.$CHAVE"
        log "WAKE end=$END motivo=$MOTIVO"
    done < "$DIR_ST/mapa.agora"

    # digest: notifica SÓ os commits que mudaram neste ciclo (sinal, não ruído)
    if [ -n "$ACHADO_CICLO" ]; then
        COMMITS=$(echo "$ACHADO_CICLO" | grep '^mudou: commit:' | sed 's/^mudou: commit://' | tr '\n' '; ')
        [ -n "$COMMITS" ] && notifica "WATCHER $AGORA: commits $COMMITS"
    fi
}

if [ "$CHECK" -eq 1 ]; then
    echo "== agents-watcher CHECK (dry-run: nada é escrito, ninguém acorda) =="
    echo "root=$RAIZ queue=$QUEUE hooks=$HOOKS prospects=$PROSPECTS"
    [ -x "$HOOKS" ] || echo "(sem hooks — só commits+queue)"
    ciclo
    exit 0
fi
log "watcher iniciado (root=$RAIZ intervalo=${INTERVALO}s quiet=${QUIET_DE}h-${QUIET_ATE}h)"
if [ "$ONCE" -eq 1 ]; then
    ciclo
    log "ciclo único completo (--once)"
    exit 0
fi
while true; do
    ciclo
    sleep "$INTERVALO"
done
