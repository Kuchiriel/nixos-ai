#!/usr/bin/env bash
# agents-watcher.sh — O WATCHER ÚNICO dos agentes (17/10, dono: "consolide
# tudo em um script e um serviço só... precisa ser agnóstico de projeto,
# funcionar em qualquer um"). Substitui 4 peças: tools/agents-watcher.sh
# (v2, CPU-delta working/idle), tools/tem-novo.sh (detector de eventos),
# nixos-ai/scripts/agent-heartbeat.sh (progress-heartbeat) e o
# agent-keepawake (hypridle.nix — 02/11: saiu daqui p/ o serviço
# SEMPRE ligado agents-keepawake.service; o watcher é AFK-only).
# O systemd (Restart=always) É o watchdog
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
# (03/11) GUARDA DE PROVIDER: timeout de 5min/429/400 do LLM nao e erro de
# tool — o agent-pains nao ve e o dono descobria 15min depois. Le o log do
# opencode, deduplica e manda PING (notify-send) + nota p/ a peer.
GUARD_PY="${AGENTS_GUARD_PY:-$SCRIPT_DIR/agent-provider-guard.py}"
GUARD_SINCE="${AGENTS_GUARD_SINCE:-20}"
GUARD_EVERY="${AGENTS_GUARD_EVERY:-1}"
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
# (02/11) A GEOMETRIA DE JANELAS agora mora no agent-roster.py (fonte ÚNICA
# p/ watcher + agent-msg: uma só implementação do process-tree walk).
# CPU via /proc (utime+stime) — pstree NÃO EXISTE no NixOS; walk ppid.
ROSTER_PY="${AGENTS_ROSTER_PY:-$SCRIPT_DIR/agent-roster.py}"
# (02/11) API do opencode: o wake passa a ser entregue NA SESSÃO do agente
# (POST /session/:id/prompt_async) — sem roubar o foco e sem digitar na
# caixa de input do humano (o wtype antigo bloqueava o typing do dono).
OC_URL="${AGENTS_OC_URL:-http://100.121.100.103:4599}"
OC_ENVFILE="${AGENTS_OC_ENVFILE:-$HOME/.config/opencode/server.env}"
OC_USER="${OPENCODE_SERVER_USERNAME:-opencode}"
OC_PASS="${OPENCODE_SERVER_PASSWORD:-}"
if [ -z "$OC_PASS" ] && [ -r "$OC_ENVFILE" ]; then
    OC_PASS=$(sed -n 's/^OPENCODE_SERVER_PASSWORD=//p' "$OC_ENVFILE" | head -1)
    OC_PASS="${OC_PASS%\"}"; OC_PASS="${OC_PASS#\"}"
fi
mapa_agentes() {
    [ -x "$ROSTER_PY" ] || { echo "agent-roster.py ausente ($ROSTER_PY)" >&2; return 0; }
    "$ROSTER_PY" windows --json 2>/dev/null | python3 -c '
import json, sys
try:
    d = json.load(sys.stdin)
except Exception:
    sys.exit(0)
for w in d.get("all", []):
    print(w.get("address", ""), w.get("pid", 0), w.get("cpu", 0),
          w.get("session", "") or "-")
'
}

# wake via API: a mensagem entra na sessão do agente e ele roda. Sem foco,
# sem wtype, sem travar o humano na caixa de input.
wake_api() {
    local SESSAO="$1" TEXTO="$2"
    python3 - "$OC_URL" "$OC_USER" "$OC_PASS" "$SESSAO" "$TEXTO" <<'PYEOF'
import base64, json, sys, urllib.request
base, user, pw, sid, texto = sys.argv[1:6]
body = json.dumps({"parts": [{"type": "text", "text": texto}]})
req = urllib.request.Request(
    f"{base}/session/{sid}/prompt_async", data=body.encode(), method="POST",
    headers={"Content-Type": "application/json",
             "Authorization": "Basic " +
             base64.b64encode(f"{user}:{pw}".encode()).decode()})
try:
    with urllib.request.urlopen(req, timeout=25) as r:
        print(r.status)
except Exception as e:
    print(f"ERRO {e}")
        sys.exit(1)
PYEOF
}

# (02/11) SEMÂNTICA DE LANE: o evento de commit é do repo X → só acorda o
# agente DONO do repo X (repo vazio = generalista). Eventos globais
# (fila/hooks) acordam todos. Sem roster → comportamento legado (global).
# Pesquisa: CHI'26 (arXiv 2602.17864) — wake sem filtro QUEBRA o fluxo e
# aumenta a carga; Anthropic — fronteira explícita evita trabalho duplicado.
filtra_eventos() {
    local END="$1"
    [ -n "${ACHADO_CICLO:-}" ] || return 0
    [ -x "$ROSTER_PY" ] || { printf '%s\n' "$ACHADO_CICLO"; return 0; }
    printf '%s\n' "$ACHADO_CICLO" | "$ROSTER_PY" events --window "$END" 2>/dev/null
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

# KEEPAWAKE: saiu daqui (02/11) — virou serviço SEMPRE ligado
# (agents-keepawake.service → scripts/agents-keepawake.sh). O watcher é
# AFK-only (sem WantedBy, decisão do dono); o keepawake tem que estar de
# pé o tempo todo. Uma única implementação do lock (sem cópia).

# um ciclo do watcher
ciclo() {
    local AGORA AGORA_E ACHADO_CICLO ANTES
    AGORA=$(date +%H:%M); AGORA_E=$(date +%s)

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
    # (02/11) ROSTER do ciclo: quem existe e em que lane/repo. Vazio = modo
    # legado (wake global) — o aviso abaixo deixa isso explícito.
    if [ -x "$ROSTER_PY" ]; then
        "$ROSTER_PY" list --json > "$DIR_ST/roster.json" 2>/dev/null \
            || echo '{}' > "$DIR_ST/roster.json"
    else
        echo '{}' > "$DIR_ST/roster.json"
    fi
    # (05/11) BUS DE COORDENACAO: as pendencias (msg endereçada, claim
    # sobreposta) sao lidas pelo MCP LOCAL (coord_pending), que tem o cache
    # do GitHub dentro — polling direto do issue estoura o rate limit (60/h).
    # O wake por bus NAO depende de prompt do dono: se o bus tem algo para
    # o codinome deste agente, ele acorda (mesma politica de lane do resto).
    BUS_CMD="${AGENTS_BUS_CMD:-$SCRIPT_DIR/agent-bus-pending.py}"
    _claims_vivos=$(python3 -c '
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except Exception:
    d = {}
print(len([a for a in d.get("agents", []) if a.get("state") == "live"]))
' "$DIR_ST/roster.json" 2>/dev/null || echo 0)
    [ "$_claims_vivos" -gt 0 ] || log "roster vazio — wake por evento fica GLOBAL (legado); use agent-roster.py claim para ativar o filtro de lane"
    # (22/10) RESET do backoff: se houve EVENTO neste ciclo (commit/queue),
    # o agente tem trabalho novo → zera deadlock-consecutivos
    if [ -n "${ACHADO_CICLO:-}" ]; then
        for _f in "$DIR_ST"/dlc.*; do
            [ -f "$_f" ] && echo 0 > "$_f"
        done
    fi
    while read -r END FOOTPID CPU SESSAO; do
        [ -z "${END:-}" ] && continue
        SESSAO="${SESSAO:--}"
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
        # (02/11) SO com wake via wtype (fallback): com a API nao ha rascunho
        # pendente — apertar Return ali submeteria o que o HUMANO estivesse
        # digitando (o watcher nao pode submeter texto alheio).
        if [ "$DELTA" -lt "$LIMITE_CPU" ] \
           && [ -f "$DIR_ST/fallback.$CHAVE" ] \
           && [ "$IDLE_SEGS" -ge 3 ] && [ "$IDLE_SEGS" -le "$REENTER_MAX" ]; then
            hyprctl dispatch focuswindow "address:$END" >/dev/null 2>&1
            sleep 0.3
            wtype -k Return
            log "RE-ENTER end=$END (o wake anterior nao foi submetido: so o Return)"
            [ "$CHECK" -eq 1 ] || date +%s > "$DIR_ST/wake.$CHAVE"
            continue
        fi
        MOTIVO=""
        # (02/11) EVENTO FILTRADO POR LANE: commit do repo X só acorda o
        # agente dono do repo X (fila/hooks = global). Sem claim = legado.
        _evt=$(filtra_eventos "$END")
        if [ -n "$_evt" ]; then
            [ -n "$ACHADO_CICLO" ] && [ "$_evt" != "$ACHADO_CICLO" ] \
                && log "filtro de lane end=$END: evento nao pertence a esta lane"
            [ "$IDLE_SEGS" -ge "$RATE_MIN" ] && MOTIVO="$_evt"
        fi
        # (05/11) WAKE POR BUS: o que o bus global tem para ESTE agente
        # (mensagem endereçada ao codinome dele). Sem item novo = não acorda
        # (o hash evita repetir a mesma mensagem a cada ciclo).
        if [ -z "$MOTIVO" ] && [ "$IDLE_SEGS" -ge "$RATE_MIN" ] && [ -x "$BUS_CMD" ]; then
            # O coord_pending precisa do QUEM eu sou (codinome) e do MEU
            # escopo (globs) para devolver as msgs endereçadas E as claims
            # que se sobrepoem aos meus arquivos. O MCP tem cache do bus
            # (COORD_CACHE_TTL_S=60s): uma leitura por agente por ciclo
            # custa UMA consulta ao GitHub por minuto, nao uma por agente.
            _bus_who=$(python3 - "$DIR_ST/roster.json" "$SESSAO" <<'PYWHO'
import json, sys
roster_p, sess = sys.argv[1:3]
try:
    roster = json.load(open(roster_p))
except Exception:
    roster = {}
for a in roster.get("agents", []):
    if sess and a.get("session") == sess:
        print((a.get("codename") or "") + "\t" + ",".join(a.get("files") or []))
        break
PYWHO
)
            _bus_cod="${_bus_who%%	*}"
            _bus_files="${_bus_who#*	}"
            if [ -n "$_bus_cod" ]; then
                _bus_json=$("$BUS_CMD" --codename "$_bus_cod" --files "$_bus_files" 2>/dev/null || echo '[]')
                _bus_hash=$(printf '%s' "$_bus_json" | python3 -c '
import hashlib, json, sys
try:
    items = json.load(sys.stdin)
except Exception:
    items = []
if not isinstance(items, list):
    items = []
texts = sorted(str(i.get("text") or "") for i in items if isinstance(i, dict))
print(hashlib.sha1("\n".join(texts).encode()).hexdigest())
' 2>/dev/null || echo "")
                _bus_seen=$(cat "$DIR_ST/bus.seen.$_bus_cod" 2>/dev/null || echo "")
                if [ -n "$_bus_hash" ] && [ "$_bus_hash" != "$_bus_seen" ]; then
                    _bus_msg=$(printf '%s' "$_bus_json" | python3 -c '
import json, sys
try:
    items = json.load(sys.stdin)
except Exception:
    items = []
if not isinstance(items, list):
    items = []
msgs = [str(i.get("text") or "").strip() for i in items if isinstance(i, dict)]
print(" | ".join(m for m in msgs if m)[:600])
' 2>/dev/null || echo "")
                    if [ -n "$_bus_msg" ]; then
                        MOTIVO="bus: $_bus_msg"
                        [ "$CHECK" -eq 1 ] || echo "$_bus_hash" > "$DIR_ST/bus.seen.$_bus_cod"
                    fi
                fi
            fi
        fi
        # (30/10) SUGESTAO DE CHECKPOINT: stretch longo de trabalho + agente
        # idle -> e a hora de gravar fila/rag/memoria/vault. O texto ja vem com
        # o comando pronto (o agente nao precisa pensar no protocolo).
        if [ -z "$MOTIVO" ]; then
            _w=$(cat "$DIR_ST/work.$CHAVE" 2>/dev/null || echo 0)
            _cp=$(cat "$DIR_ST/checkpoint.$CHAVE" 2>/dev/null || echo 0)
            _cp_gl=$(cat "$CP_MARCADOR" 2>/dev/null || echo 0)
            [ "$_cp_gl" -gt "$_cp" ] 2>/dev/null && _cp="$_cp_gl"
            if [ "$_w" -ge "$CP_TRABALHO" ] && [ $(( AGORA_E - _cp )) -ge "$CP_COOLDOWN" ]; then
                # (01/11, fix 02:5x) so sugerir se houve trabalho NOVO desde o
                # ultimo checkpoint: algum .git/HEAD da raiz (ou a fila) mais
                # NOVO que o marcador global. Imune a corrida do snapshot
                # (a fila commita no meio do checkpoint e o snapshot.agora
                # recalcula a cada ciclo - a comparacao de snapshots dava
                # falso "trabalho novo").
                _trab_novo=0
                for _g in $(find "$RAIZ" -maxdepth "$DEPTH" -name HEAD -path "*/.git/*" 2>/dev/null) "$QUEUE"; do
                    [ -e "$_g" ] && [ "$_g" -nt "$CP_MARCADOR" ] && { _trab_novo=1; break; }
                done
                if [ "$_trab_novo" -eq 0 ]; then
                    log "checkpoint ja selado (nenhum commit novo desde o marcador) end=$END - sem sugestao"
                    continue
                fi
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
        # (02/11) WAKE VIA API: a mensagem entra NA SESSÃO do agente e ele
        # roda — sem roubar o foco e sem digitar na caixa do humano.
        _MSG="[WATCHER $AGORA] $MOTIVO. Conf. mutuas AUTORIZADAS. 1 linha de acao."
        _OK=0
        if [ "$SESSAO" != "-" ] && [ -n "$SESSAO" ]; then
            _R=$(wake_api "$SESSAO" "$_MSG" || true)
            case "$_R" in
                2*|HTTP*) _OK=1 ;;
                *) log "wake API falhou end=$END sessao=$SESSAO: $_R" ;;
            esac
        fi
        if [ "$_OK" -eq 0 ]; then
            # fallback antigo (focus + wtype + Return): só quando não há API
            hyprctl dispatch focuswindow "address:$END" >/dev/null 2>&1
            wtype "$_MSG"
            sleep 1.2
            wtype -k Return
            [ "$CHECK" -eq 1 ] || touch "$DIR_ST/fallback.$CHAVE"
            log "WAKE (fallback focus+wtype) end=$END motivo=$MOTIVO"
        else
            [ "$CHECK" -eq 1 ] || rm -f "$DIR_ST/fallback.$CHAVE"
            log "WAKE (API) end=$END sessao=$SESSAO motivo=$MOTIVO"
        fi
        date +%s > "$DIR_ST/wake.$CHAVE"
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

    # (03/11) GUARDA DE PROVIDER (timeout 5min / 429 / 400 do LLM): cada
    # ciclo, janela de GUARD_SINCE min. Dedup interno: so evento NOVO pinga.
    # CHECK (dry-run) nao notifica.
    _cgn=$(cat "$DIR_ST/ciclo.guard" 2>/dev/null || echo 0)
    _cgn=$(( _cgn + 1 ))
    [ "$CHECK" -eq 1 ] || echo "$_cgn" > "$DIR_ST/ciclo.guard"
    if [ "$_cgn" -ge "$GUARD_EVERY" ] && [ -f "$GUARD_PY" ]; then
        [ "$CHECK" -eq 1 ] || echo 0 > "$DIR_ST/ciclo.guard"
        if [ "$CHECK" -eq 1 ]; then
            _gr=$(python3 "$GUARD_PY" scan --since-min "$GUARD_SINCE" --dry-run 2>&1 | tail -2 | tr '\n' '; ')
        else
            _gr=$(python3 "$GUARD_PY" scan --since-min "$GUARD_SINCE" 2>&1 | tail -2 | tr '\n' '; ')
        fi
        case "$_gr" in
            *"sem evento novo"*) ;;
            *) log "provider-guard: $_gr" ;;
        esac
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
