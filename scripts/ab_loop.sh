#!/bin/bash
# ab_loop.sh — Loop A/B continuo do dungeon: escada L1/L2/L3 x modelos locais.
#
# ── O QUE MUDOU (17/11, medido) ───────────────────────────────────────────
# 1. GPU TOMADA E DEVOLVIDA POR CICLO (`llm-swap.sh takeover|release`). Antes
#    o residente da casa (duplex-voice :8092, 3.886 MiB) ficava no ar e o
#    bonsai nao cabia: 62 ciclos morreram em "swap falhou" e viravam buraco
#    no results.jsonl. Se alguem estiver usando a voz agora, o ciclo e ADIADO.
# 2. ESCADA: cada ciclo roda um degrau (L1 metodo puro -> L2 desvio local ->
#    L3 pathfinding). Falhar no L3 nao distingue 8B de 4B; a curva distingue.
# 3. FALHA E DADO: swap/checker/timeout agora gravam linha com "erro" em vez
#    de sumir. O painel mostra vermelho, nao ausencia.
# 4. `nivel` em toda linha do results.jsonl.
set -uo pipefail

LOG_DIR="/home/nixos/logs/ab_loop"
LANE_BASE="/home/nixos/projects"
DUNGEON_SRC="/home/nixos/projects/jarvis-dungeon"
BASELINE_COMMIT="343256793dc06a1a011adf360b611b1e652d7f79"
TEST_COMMIT="e47e976"
REPO="/home/nixos/projects/nixos-ai"
SWAP="/home/nixos/projects/nixos-ai/scripts/llm-swap.sh"
MOTIVO_LIB="$REPO/scripts/ab_loop_motivo.sh"
MODELS="${AB_MODELS:-bonsai mtp api api-moe}"
NIVEIS="${AB_LEVELS:-L1 L2 L3}"
SLEEP_ENTRE="${AB_SLEEP:-45}"
RES="$LOG_DIR/results.jsonl"

mkdir -p "$LOG_DIR"
log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_DIR/ab_loop.log"; }

if [ ! -r "$MOTIVO_LIB" ]; then
    echo "AB_LOOP: classificador ausente: $MOTIVO_LIB" >&2
    exit 1
fi
# shellcheck source=scripts/ab_loop_motivo.sh
. "$MOTIVO_LIB"

CTL="/home/nixos/.local/state/jarvis/nightwatch/ab_loop.control"
controle() { [ -f "$CTL" ] && cat "$CTL" 2>/dev/null || echo "run"; }

# Acao pontual: now | run:modelo | level:L2 | one (um ciclo e volta a run)
ACAO=""
consome_acao() {
    local c
    c=$(controle)
    case "$c" in
        now|one) printf 'run' > "$CTL"; echo "$c" ;;
        run:*|level:*) printf 'run' > "$CTL"; echo "$c" ;;
        *) echo "" ;;
    esac
}

PIDFILE="/home/nixos/.local/state/jarvis/nightwatch/ab_loop.pid"
if [ -f "$PIDFILE" ]; then
    OLD=$(cat "$PIDFILE" 2>/dev/null)
    if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then
        echo "AB_LOOP: ja existe uma instancia viva (PID $OLD) — saindo" >&2
        exit 1
    fi
fi
echo $$ > "$PIDFILE"
echo "AB_LOOP: PID $$ em $(date '+%H:%M:%S') modelo=$MODELS niveis=$NIVEIS"

LOCK="/home/nixos/.local/state/jarvis/nightwatch/RUNNING.lock"

lock_holders() {
    local out="" inode
    inode=$(stat -c %i "$LOCK" 2>/dev/null)
    [ -z "$inode" ] && { echo "sem lock"; return; }
    for P in /proc/[0-9]*; do
        local pid=${P#/proc/} cmd
        cmd=$(tr '\0' ' ' < "$P/cmdline" 2>/dev/null)
        case "$cmd" in
            *nightwatch*|*nixos-ai*)
                for FD in "$P"/fd/*; do
                    local t
                    t=$(readlink "$FD" 2>/dev/null)
                    case "$t" in *RUNNING.lock*) out="$out $pid:${cmd:0:90}" ;; esac
                done 2>/dev/null ;;
        esac
    done
    [ -z "$out" ] && out="(ninguem)" || out="${out# }"
    echo "$out"
}

limpa_execucao_anterior() {
    local PIDS PID i
    PIDS=$(ps -eo pid,args 2>/dev/null | grep "nightwatch[.]dungeon" | grep -v grep | awk '{print $1}')
    for PID in $PIDS; do kill -9 "$PID" 2>/dev/null; done
    for i in $(seq 1 15); do
        PIDS=$(ps -eo pid,args 2>/dev/null | grep "nightwatch[.]dungeon" | grep -v grep | awk '{print $1}')
        [ -z "$PIDS" ] && break
        sleep 1
    done
    for PID in $PIDS; do kill -9 "$PID" 2>/dev/null; done
    rm -f "$LOCK"
}

cleanup() {
    local PIDS
    PIDS=$(ps -eo pid,args 2>/dev/null | grep "nightwatch[.]dungeon" | grep -v grep | awk '{print $1}')
    for PID in $PIDS; do kill -9 "$PID" 2>/dev/null; done
    rm -f "$LOCK"
    # nunca deixar a casa sem a voz por causa do laboratorio
    [ -x "$SWAP" ] && bash "$SWAP" release >/dev/null 2>&1
    if [ "$(cat "$PIDFILE" 2>/dev/null)" = "$$" ]; then rm -f "$PIDFILE"; fi
}
trap 'cleanup; exit 0' TERM INT
trap cleanup EXIT

checker_do_nivel() {
    case "$1" in
        L1) echo "dungeon-checker-l1.py" ;;
        L2) echo "dungeon-checker-l2.py" ;;
        *)  echo "dungeon-checker.py" ;;
    esac
}

# review_wrong: o patch rejeitado esta no git stash da lane? Entao, num
# COPIA em /tmp, o checker fixo APROVA esse patch? Se sim, o review reprovou
# um patch BOM e o motivo e' review_wrong. A lane original nunca e' tocada.

# (19/11) persona da ultima execucao da lane (log de observabilidade do harness)
persona_da_lane() {  # lane texto_da_task -> "id|in_prompt"
  local lane="$1" tasktxt="$2" logf
  for logf in "$HOME/.local/state/jarvis/orchestrator/task-execution.jsonl"; do
    [ -f "$logf" ] || continue
    python3 - "$logf" "$lane" <<'PYEOF' 2>/dev/null && return 0
import json,sys
logf,lane=sys.argv[1],sys.argv[2]
last=None
try:
    for line in open(logf,encoding="utf-8"):
        try: d=json.loads(line)
        except Exception: continue
        # casa pela lane: o task_id traz o nome da lane (dungeon-ab-bonsai-L1-...)
        tid = str(d.get("task_id",""))
        proj = str(d.get("project",""))
        # casa por: lane no task_id, OU o texto da task no project da entrada
        if (lane in tid) or (lane in str(d.get("lane",""))) \
           or (tasktxt and tasktxt[:40] and tasktxt[:40] in proj):
            last=d
except Exception: pass
if last:
    p=last.get("persona") or ""
    print(f"{p}|{1 if last.get('persona_in_prompt') else 0}")
PYEOF
  done
  echo "|0"
}

registra_erro() {  # modelo nivel erro
    printf '{"modelo":"%s","nivel":"%s","erro":"%s","ck":"v3","motivo":"infra","ts":%s}\n' \
        "$1" "$2" "$3" "$(date +%s)" >> "$RES"
    log "  ERRO registrado: $1/$2 -> $3"
}

run_ab() {
    local modelo="$1" nivel="$2"
    local lane="$LANE_BASE/dungeon-$modelo"

    log "=== A/B $modelo @ $nivel ==="

    limpa_execucao_anterior
    log "  lock holders no inicio: $(lock_holders)"

    rm -rf "$lane"; mkdir -p "$lane"
    cd "$DUNGEON_SRC" || { log "  ERRO: sem $DUNGEON_SRC"; registra_erro "$modelo" "$nivel" "sem-repo"; return 1; }
    local f
    for f in $(git ls-tree -r --name-only "$BASELINE_COMMIT" | grep -v __pycache__); do
        mkdir -p "$lane/$(dirname "$f")"
        git show "$BASELINE_COMMIT:$f" > "$lane/$f"
    done

    # sinal extra (NAO e o veredito)
    git -C "$DUNGEON_SRC" show "$TEST_COMMIT:test_astar.py" \
        | sed "s|/home/nixos/projects/jarvis-dungeon/src|$lane/src|" \
        > "$lane/test_astar.py"
    chmod 444 "$lane/test_astar.py"

    # O VEREDITO: checker do nivel, escrito antes e trancado
    local ck
    ck=$(checker_do_nivel "$nivel")
    if [ -f "$REPO/scripts/$ck" ]; then
        cp "$REPO/scripts/$ck" "$lane/checker.py"
        chmod 444 "$lane/checker.py"
    else
        log "  ERRO: checker ausente: $ck"
        registra_erro "$modelo" "$nivel" "sem-checker"
        return 1
    fi

    cat > "$lane/conftest.py" << 'CONF'
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
CONF
    printf '__pycache__/\n*.pyc\n' > "$lane/.gitignore"

    cd "$lane" || return 1
    git init -q && git add -A && \
        git -c user.email=lab@local -c user.name=lab commit -q -m "baseline+checker"

    # os bracos "api" e "api-moe" nao usam GPU: nao ha swap nem VRAM a disputar
    if [ "$modelo" != "api" ] && [ "$modelo" != "api-moe" ] && [ -x "$SWAP" ]; then
        bash "$SWAP" "$modelo" || { registra_erro "$modelo" "$nivel" "swap"; return 1; }
    fi

    # (17/11) ESTADO DO HARNESS ISOLADO POR BRACO. Limpar os arquivos por
    # projeto NAO bastava: checkpoint.py tem fallback LEGADO para o
    # checkpoint.json global e ressuscitava um "fail-test" de 04/set
    # (projeto test-repo) reescrito como dungeon-<braco> — o run comecava em
    # "Recovering: This will fail" antes de qualquer task do A/B, com o
    # checker novo. Com JARVIS_STATE_DIR proprio por braco nao existe arquivo
    # legado para herdar, e cada ciclo comeca em estado comprovadamente limpo.
    local ST="/home/nixos/.local/state/jarvis/nightwatch"
    export JARVIS_STATE_DIR="$ST/ab-$modelo"
    mkdir -p "$JARVIS_STATE_DIR"
    find "$JARVIS_STATE_DIR" -maxdepth 1 -type f -name '*.json' -delete
    log "  estado do harness: $JARVIS_STATE_DIR (limpo)"

    cd "$REPO" || return 1
    export PYTHONPATH="$REPO/modules/ai/jarvis/src"
    export JARVIS_LLM_TIMEOUT="${JARVIS_LLM_TIMEOUT:-600}"
    export AB_LEVEL="$nivel"
    timeout 300 nix develop -c python3 -m nightwatch.dungeon enqueue --model "$modelo" --level "$nivel" \
        2>&1 | tail -1 | cut -c1-100

    local start end dur rc
    start=$(date +%s)
    timeout --kill-after=60 1800 nix develop -c python3 -m nightwatch.dungeon run \
        --model "$modelo" --level "$nivel" > "$LOG_DIR/run-$modelo.log" 2>&1
    rc=$?
    end=$(date +%s); dur=$((end - start))
    # historico de execucao: sem isso, a falha detalhada de um ciclo era
    # apagada pelo ciclo seguinte (so sobrava o ultimo).
    cp -f "$LOG_DIR/run-$modelo.log" "$LOG_DIR/run-$modelo-$(date +%H%M%S).log" 2>/dev/null || true
    ls -t "$LOG_DIR"/run-"$modelo"-*.log 2>/dev/null | tail -n +21 | xargs -r rm -f
    log "  lock holders apos a corrida: $(lock_holders)"

    local checker_result
    checker_result=$(timeout 180 nix develop "$REPO" -c bash -c \
        "cd /tmp && python3 -m pytest -q '$lane/checker.py'" 2>&1 \
        | grep -E "passed|failed|error" | tail -1)
    [ -z "$checker_result" ] && checker_result="sem resultado do checker"

    local diff_stat
    diff_stat=$(git -C "$lane" diff --stat 2>/dev/null | tail -1)
    [ -z "$diff_stat" ] && diff_stat="(sem diff)"

    local stamp base_sha pbytes
    stamp=$(date +%H%M%S)
    base_sha=$(git -C "$lane" rev-list --max-parents=0 HEAD 2>/dev/null | head -1)
    if [ -n "$base_sha" ]; then
        git -C "$lane" diff "$base_sha" HEAD -- "*.py" 2>/dev/null | head -250 \
            > "$LOG_DIR/patch-$modelo-$stamp.diff"
    else
        : > "$LOG_DIR/patch-$modelo-$stamp.diff"
    fi
    git -C "$lane" log --oneline -3 > "$LOG_DIR/commits-$modelo-$stamp.txt" 2>/dev/null
    pbytes=$(wc -c < "$LOG_DIR/patch-$modelo-$stamp.diff" 2>/dev/null || echo 0)

    log "Resultado $modelo @ $nivel: rc=$rc, dur=${dur}s, patch=${pbytes}B"
    log "  Checker: $checker_result"

    # rc do run: 124 = timeout do nosso wrapper (nao e veredito do modelo)
    if [ "$rc" = "124" ]; then
        printf '{"modelo":"%s","nivel":"%s","rc":124,"dur":%s,"erro":"timeout","patch_bytes":%s,"ck":"v3","motivo":"infra","ts":%s}\n' \
            "$modelo" "$nivel" "$dur" "$pbytes" "$(date +%s)" >> "$RES"
        return 1
    fi

    # (17/11) MOTIVO: separa "o modelo errou" de "o revisor abortou" e de
    # "infra falhou". Sem isto, um patch rejeitado pelo revisor aparecia como
    # reprovacao no checker e o A/B media o baseline, nao o modelo.
    local motivo runlog="$LOG_DIR/run-$modelo.log" review_meta review_sha review_checker
    review_meta="$(ab_review_meta_path "$LOG_DIR" "$modelo-$nivel-$stamp")"
    review_sha=""; review_checker=""
    # G1: se o revisor abortou com patch vazio, captura AGORA o diff
    # rejeitado e o veredito do checker numa copia. O stash vivo some no
    # proximo ciclo (a lane e recriada), e sem isto a atribuicao de culpa
    # fica no escuro.
    if [ "$pbytes" = "0" ] && ab_log_tem_review_failed "$runlog"; then
        if ab_captura_rejeicao "$lane" "$LOG_DIR" "$modelo-$nivel-$stamp"; then
            review_sha=$(grep -E '^diff_sha256=' "$review_meta" 2>/dev/null | head -1 | cut -d= -f2-)
            review_checker=$(grep -E '^checker=' "$review_meta" 2>/dev/null | head -1 | cut -d= -f2-)
            log "  Capturado patch rejeitado: sha=$review_sha checker=$review_checker"
        fi
    fi
    motivo=$(classifica_motivo "$rc" "$pbytes" "$runlog" "$lane" "$review_meta")
    log "  Motivo: $motivo"
    local persona_info persona_id persona_in_prompt
    local texto_task=""
    texto_task="$(python3 -c "
import json,os
p=os.path.expanduser('~/.local/state/jarvis/nightwatch/task_queue-dungeon-${modelo}-${nivel,,}.json')
try:
    d=json.load(open(p))
    for t in d:
        if t.get('status') in ('IN_PROGRESS','READY','DISCOVERED'):
            print(t.get('description','')); break
except Exception: pass
" 2>/dev/null)"
    persona_info="$(persona_da_lane "$lane" "$texto_task")"
    persona_id="${persona_info%%|*}"; persona_in_prompt="${persona_info##*|}"
    printf '{"modelo":"%s","nivel":"%s","rc":%s,"dur":%s,"checker":"%s","patch_bytes":%s,"ck":"v3","motivo":"%s","persona":"%s","persona_in_prompt":%s,"review_diff_sha256":"%s","review_checker":"%s","ts":%s}\n' \
        "$modelo" "$nivel" "$rc" "$dur" \
        "$(echo "$checker_result" | tr -d '"' | cut -c1-120)" "$pbytes" "$motivo" "$persona_id" \
        "${persona_in_prompt:-0}" "$review_sha" "$review_checker" "$(date +%s)" \
        >> "$RES"
}

# ── o laco ───────────────────────────────────────────────────────────────
read -r -a NIVEIS_ARR <<< "$NIVEIS"
[ ${#NIVEIS_ARR[@]} -eq 0 ] && NIVEIS_ARR=("L3")
CICLO=0
IDX=0
FORCA_NIVEL=""

while true; do
    while [ "$(controle)" = "pause" ]; do
        [ $((CICLO % 10)) -eq 0 ] && log "pausado pelo painel (aguardando)"
        sleep 10
    done

    ACAO=$(consome_acao)
    CICLOS_MODELO="$MODELS"
    UMA_VEZ=0
    case "$ACAO" in
        "") ;;
        now)  log "painel: rodar agora" ;;
        one)  log "painel: um ciclo so"; UMA_VEZ=1 ;;
        run:*) CICLOS_MODELO="${ACAO#run:}"; log "painel: rodar so $CICLOS_MODELO" ;;
        level:*) FORCA_NIVEL="${ACAO#level:}"; log "painel: nivel forcado $FORCA_NIVEL" ;;
    esac

    if [ -n "$FORCA_NIVEL" ]; then
        NIVEL="$FORCA_NIVEL"
        FORCA_NIVEL=""
    else
        NIVEL="${NIVEIS_ARR[$IDX]:-L3}"
        IDX=$(( (IDX + 1) % ${#NIVEIS_ARR[@]} ))
    fi

    # A voz do dono tem prioridade: se ha cliente conectado no residente,
    # nao toma a GPU (so adia o ciclo).
    if ! bash "$SWAP" idle 2>/dev/null; then
        log "residente em uso agora — ciclo adiado (a voz ganha do laboratorio)"
        sleep 60
        continue
    fi

    CICLO=$((CICLO + 1))
    log "========== CICLO $CICLO (nivel $NIVEL) =========="
    for modelo in $CICLOS_MODELO; do
        run_ab "$modelo" "$NIVEL"
    done
    bash "$SWAP" release >/dev/null 2>&1
    log "========== Ciclo $CICLO concluido; GPU devolvida =========="

    [ "$UMA_VEZ" = "1" ] && { log "painel: ciclo unico feito, mantendo em run"; }
    sleep "$SLEEP_ENTRE"
done
