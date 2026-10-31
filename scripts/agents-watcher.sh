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
#   AGENTS_PAINS_EVERY  ciclos entre auto-captura de erros de CLI (default 10)
#   AGENTS_CHECKPOINT_WORK  seg de trabalho p/ sugerir checkpoint (default 2700)
#   AGENTS_CHECKPOINT_COOLDOWN  seg entre sugestoes (default 3600)
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
# (30/10) janela (s) para o re-Return: se o agente segue ocioso ate
# REENTER_MAX s depois de um wake, o Return anterior nao pegou.
REENTER_MAX="${AGENTS_REENTER_MAX:-200}"
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
# (30/10) STACK GENERALISTA: pains + checkpoint moram AO LADO do watcher
# (nada hardcoded de projeto). Env sobrescreve.
SCRIPT_DIR="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
PAINS_SH="${AGENTS_PAINS_SH:-$SCRIPT_DIR/agent-pains.sh}"
CHECKPOINT_SH="${AGENTS_CHECKPOINT_SH:-$SCRIPT_DIR/agent-checkpoint.sh}"
# auto-captura de erros de CLI a cada N ciclos (silencioso, nunca acorda ninguem)
PAINS_EVERY="${AGENTS_PAINS_EVERY:-10}"
PAINS_SINCE="${AGENTS_PAINS_SINCE:-90}"
# checkpoint sugerido depois de um stretch longo de trabalho (segundos de CPU)
CP_TRABALHO="${AGENTS_CHECKPOINT_WORK:-2700}"
CP_COOLDOWN="${AGENTS_CHECKPOINT_COOLDOWN:-3600}"
# (01/11) o watcher nao ve checkpoint feito PELO AGENTE (script fora dele):
# o agent-checkpoint.sh grava o marcador global abaixo; o cooldown usa o mais novo.
CP_MARCADOR="$DIR_ST/ultimo_checkpoint"
# (01/11, pedido do dono) SINAL DE VIDA REAL: o delta de CPU e falso-positivo
# quando o agente esta bloqueado num comando longo (backtest de 20min, copia de
# 3GB). O store do opencode (SQLite opencode.db, tabela part) e atualizado A
# CADA tool call -> se houve part nova nos ultimos AGENTS_DB_ALIVE segundos, o
# agente esta VIVO e o deadlock-check NAO dispara (e o backoff nao avanca).
DB_ALIVE="${AGENTS_DB_ALIVE:-600}"
DB_PATH="${AGENTS_DB_PATH:-$HOME/.local/share/opencode/opencode.db}"
# estado por raiz observada: trocar AGENTS_ROOT NÃO dispara falsos "novo:"
STATE="$DIR_ST/snapshot.$(printf '%s' "$RAIZ" | md5sum | cut -c1-8).state"
INHIBIT_PID=""
# (22/10, lição do agente-fraco) BACKOFF PROGRESSIVO p/ DEADLOCK-CHECK:
# agente idle que responde sempre igual = SPAM. Cada deadlock-check
# consecutivo DOBRA o intervalo até MAX_BACKOFF; qualquer commit ou
# evento novo no ciclo ZERA o contador (atividade = reset).
MAX_BACKOFF="${AGENTS_MAX_BACKOFF:-7200}"   # 2h cap
backoff_seg() { # $1=chave do agente → segundos de fallback efetivo
    local _n=$(cat "$DIR_ST/dlc.$1" 2>/dev/null || echo 0)
    local _fb=$FALLBACK
    for _ in $(seq 1 "$_n"); do
        _fb=$(( _fb * 2 ))
        [ "$_fb" -ge "$MAX_BACKOFF" ] && { _fb=$MAX_BACKOFF; break; }
    done
    echo "$_fb"
}

# (01/11) atividade REAL do agente no store do opencode (part = cada tool call
# e trecho de resposta). Somente leitura (mode=ro); falha aberta = sem sinal.
agente_vivo_db() {
    [ -f "$DB_PATH" ] || return 1
    python3 - "$DB_PATH" "$DB_ALIVE" <<'PYEOF' 2>/dev/null
import sqlite3, sys, time
db, janela = sys.argv[1], int(sys.argv[2])
try:
    c = sqlite3.connect(f'file:{db}?mode=ro', uri=True)
    r = c.execute("SELECT MAX(time_updated), MAX(time_created) FROM part").fetchone()
    if not r:
        sys.exit(1)
    now = int(time.time() * 1000)
    for t in r:
        if t and now - t <= janela * 1000:
            sys.exit(0)
    sys.exit(1)
except Exception:
    sys.exit(1)
PYEOF
}

notifica() { [ -n "$NOTIFY" ] && "$NOTIFY" "$1" >/dev/null 2>&1 || true; }
log()      { echo "$(date '+%H:%M:%S') $*"; [ "$CHECK" -eq 1 ] || echo "$(date '+%H:%M:%S') $*" >> "$DIR_ST/states"; }

# descobre as JANELAS-AGENTE: foot com um opencode TUI VIVO como descendente
# (17/10: título "OC |" provou ser frágil — sessões mortas mantêm título e
# o wake digitou em shell morto; sessão viva sem título ficava invisível.
# Process-tree = zero convenção de título, agnóstico de verdade.)
# CPU via /proc (utime+stime) — pstree NÃO EXISTE no NixOS; walk ppid.
mapa_agentes() {
    python3 2>/dev/null <<'PYEOF'
import json, os, subprocess
def proc_map():
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
    return ppid_de, agente
ppid_de, agente = proc_map()
def descendentes(root):
    pids, frontier = [root], [root]
    while frontier:
        nxt = [p for p in ppid_de
               if ppid_de[p] in frontier and p not in pids]
        pids += nxt
        frontier = nxt
    return pids
for c in json.loads(subprocess.run(['hyprctl','clients','-j'],
        capture_output=True, text=True).stdout):
    if c.get('class') != 'foot':
        continue
    desc = descendentes(c.get('pid', 0))
    if not any(agente.get(p) for p in desc):
        continue   # foot sem opencode vivo = janela comum/shell morto
    cpu = 0
    for pid in desc:
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
        log "sem janelas-agente (foot com opencode vivo) — ciclo silencioso"
    fi
    # (22/10) RESET do backoff: se houve EVENTO neste ciclo (commit/queue),
    # o agente tem trabalho novo → zera deadlock-consecutivos
    if [ -n "${ACHADO_CICLO:-}" ]; then
        for _f in "$DIR_ST"/dlc.*; do
            [ -f "$_f" ] && echo 0 > "$_f"
        done
    fi
    while read -r END FOOTPID CPU; do
        [ -z "${END:-}" ] && continue
        CHAVE="$FOOTPID"
        ANTIGO=$(cat "$DIR_ST/cpu.$CHAVE" 2>/dev/null || echo "$CPU")
        DELTA=$(( CPU - ANTIGO ))
        [ "$CHECK" -eq 1 ] || echo "$CPU" > "$DIR_ST/cpu.$CHAVE"
        if [ "$DELTA" -ge "$LIMITE_CPU" ]; then
            # (30/10) acumula o tempo de trabalho: depois de um stretch longo,
            # o agente idle e o momento certo p/ sugerir o checkpoint de 4 camadas.
            _w=$(cat "$DIR_ST/work.$CHAVE" 2>/dev/null || echo 0)
            _w=$(( _w + INTERVALO ))
            [ "$CHECK" -eq 1 ] || echo "$_w" > "$DIR_ST/work.$CHAVE"
            log "working delta=$DELTA end=$END (trabalho acumulado=${_w}s)"
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
        # (01/11) agente VIVO por atividade real (store do opencode)? O idle de
        # CPU so indica que nao ha PROCESSO consumindo CPU - nao que o agente
        # esteja parado (comando longo bloqueia o TUI sem CPU). Vivo = nao acorda.
        if agente_vivo_db; then
            _w=$(cat "$DIR_ST/work.$CHAVE" 2>/dev/null || echo 0)
            _w=$(( _w + INTERVALO ))
            [ "$CHECK" -eq 1 ] || { echo "$_w" > "$DIR_ST/work.$CHAVE"; }
            log "vivo (part nova <=${DB_ALIVE}s no opencode.db) end=$END (trabalho acumulado=${_w}s) - sem wake"
            continue
        fi
        # (30/10) FIX ENTER: o TUI do opencode as vezes ignora o Return colado
        # com o texto (o input ainda esta processando) -> o dono precisa apertar
        # enter na mao. Aqui: se o agente continua OCIOSO logo apos um wake,
        # o texto segue na caixa de input -> reenvia SO o Return (nao digita
        # outra mensagem, que se misturaria com a anterior).
        if [ "$DELTA" -lt "$LIMITE_CPU" ] \
           && [ "$IDLE_SEGS" -ge 3 ] && [ "$IDLE_SEGS" -le "$REENTER_MAX" ]; then
            hyprctl dispatch focuswindow "address:$END" >/dev/null 2>&1
            sleep 0.3
            wtype -k Return
            log "RE-ENTER end=$END (o wake anterior nao foi submetido: so o Return)"
            [ "$CHECK" -eq 1 ] || date +%s > "$DIR_ST/wake.$CHAVE"
            continue
        fi
        MOTIVO=""
        [ -n "$ACHADO_CICLO" ] && [ "$IDLE_SEGS" -ge "$RATE_MIN" ] && MOTIVO="$ACHADO_CICLO"
        # (30/10) SUGESTAO DE CHECKPOINT: stretch longo de trabalho + agente
        # idle -> e a hora de gravar fila/rag/memoria/vault. O texto ja vem com
        # o comando pronto (o agente nao precisa pensar no protocolo).
        if [ -z "$MOTIVO" ]; then
            _w=$(cat "$DIR_ST/work.$CHAVE" 2>/dev/null || echo 0)
            _cp=$(cat "$DIR_ST/checkpoint.$CHAVE" 2>/dev/null || echo 0)
            _cp_gl=$(cat "$CP_MARCADOR" 2>/dev/null || echo 0)
            [ "$_cp_gl" -gt "$_cp" ] 2>/dev/null && _cp="$_cp_gl"
            if [ "$_w" -ge "$CP_TRABALHO" ] && [ $(( AGORA_E - _cp )) -ge "$CP_COOLDOWN" ]; then
                # (01/11) so sugerir se houve trabalho NOVO desde o ultimo
                # checkpoint: guarda o snapshot no momento da sugestao e compara.
                # Sem commit novo = a era ja foi selada -> nao repete a sugerencia.
                _cp_snap="$DIR_ST/checkpoint.$CHAVE.snap"
                if [ -f "$_cp_snap" ] && diff -q "$_cp_snap" "$DIR_ST/snapshot.agora" >/dev/null 2>&1; then
                    log "checkpoint ja selado (sem commit novo desde o ultimo) end=$END - sem sugestao"
                    continue
                fi
                cp "$DIR_ST/snapshot.agora" "$_cp_snap" 2>/dev/null || true
                MOTIVO="CHECKPOINT-SUGERIDO: voce acumula ${_w}s de trabalho nesta sessao. Grave as 4 camadas AGORA (fila+commit, rag, memoria, vault): ${CHECKPOINT_SH} --project <projeto> --era '<tema>' --summary '<estado>'. Nao precisa digitar as dores: o agent-pains.sh ja capturou os erros de CLI sozinho."
                [ "$CHECK" -eq 1 ] || { date +%s > "$DIR_ST/checkpoint.$CHAVE"; echo 0 > "$DIR_ST/work.$CHAVE"; }
            fi
        fi
        # IDLE-PROSPECÇÃO: sem acontecimento, agente parado = desperdiçado.
        # (22/10, lição do agente-fraco) BACKOFF PROGRESSIVO: cada
        # deadlock-check consecutivo dobra o intervalo; evento = reset.
        _EFFECTIVE_FALLBACK=$(backoff_seg "$CHAVE")
        if [ -z "$MOTIVO" ] && [ "$IDLE_SEGS" -ge "$_EFFECTIVE_FALLBACK" ]; then
            # (22/10) SESSÃO COMPLETA: se a fila tem SELO/★/ARCHIVED no
            # topo recente, deadlock-check vira LEMBRETE leve (não força)
            _SELADO=0
            if [ -f "$QUEUE" ]; then
                head -20 "$QUEUE" 2>/dev/null | grep -qiE "SELO DE FIM|SESSION.*COMPLETE|ARCHIVED|sessão encerrada" && _SELADO=1
            fi
            if [ "$_SELADO" -eq 1 ]; then
                # sessão selada = apenas prospecção, NUNCA deadlock-check
                if [ -s "$PROSPECTS" ]; then
                    mapfile -t PROS < "$PROSPECTS"
                    ESCOLHIDO=""
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
                [ -z "$MOTIVO" ] && MOTIVO=""  # selado e sem prospect = CALADO
            else
                # sessão ativa = comportamento normal (prospecção → deadlock)
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
                if [ -z "$MOTIVO" ]; then
                    # incrementa deadlock-consecutivos (para o backoff)
                    _n=$(cat "$DIR_ST/dlc.$CHAVE" 2>/dev/null || echo 0)
                    _n=$(( _n + 1 ))
                    [ "$CHECK" -eq 1 ] || echo "$_n" > "$DIR_ST/dlc.$CHAVE"
                    MOTIVO="DEADLOCK-CHECK: declare em 1 linha ESTADO (working X | ready Y | waiting-on Z). Waiting-on colega >10min = tome a iniciativa (turn-taking): proponha divisão concreta e COMECE sua parte AGORA; sem material próprio = PESQUISE OS ÚLTIMOS PAPERS do assunto/dificuldade (arXiv, ~/Books/papers, RAG books — diretiva 20/10) E LEIA os fontes do projeto — ache o próximo sistema a trabalhar e COMEÇE. Nunca espere calado."
                fi
            fi
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
        sleep 1.2   # (30/10) o TUI precisa terminar de processar o texto antes do Return
        wtype -k Return
        date +%s > "$DIR_ST/wake.$CHAVE"
        log "WAKE end=$END motivo=$MOTIVO"
    done < "$DIR_ST/mapa.agora"

    # (30/10) AUTO-PAINS: captura sozinho os erros de tool dos agentes (a CLI
    # le o store VIVO do opencode). Silencioso: so loga, nunca acorda ninguem.
    _cpn=$(cat "$DIR_ST/ciclo.pains" 2>/dev/null || echo 0)
    _cpn=$(( _cpn + 1 ))
    [ "$CHECK" -eq 1 ] || echo "$_cpn" > "$DIR_ST/ciclo.pains"
    if [ "$_cpn" -ge "$PAINS_EVERY" ]; then
        [ "$CHECK" -eq 1 ] || echo 0 > "$DIR_ST/ciclo.pains"
        if [ -x "$PAINS_SH" ]; then
            _pr=$("$PAINS_SH" scan-apply --since-min "$PAINS_SINCE" --max 40 2>&1 | tail -1)
            log "auto-pains: $_pr"
        fi
    fi

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
