#!/bin/bash
# ab_loop.sh — Loop de teste A/B continuo entre modelos do dungeon
#
# Roda o harness nightwatch (que gera o patch), aplica o patch na lane e
# mede com o checker real (pytest + pygame, dentro do nix develop do repo).
# Como a VRAM da casa e de 6 GB, so cabe UM modelo por vez: o loop faz
# hot-swap (llm-swap.sh) entre os dois antes de cada corrida.
set -uo pipefail

LOG_DIR="/home/nixos/logs/ab_loop"
LANE_BASE="/home/nixos/projects"
DUNGEON_SRC="/home/nixos/projects/jarvis-dungeon"
BASELINE_COMMIT="343256793dc06a1a011adf360b611b1e652d7f79"
TEST_COMMIT="e47e976"
REPO="/home/nixos/projects/nixos-ai"
SWAP="/home/nixos/projects/nixos-ai/scripts/llm-swap.sh"
MODELS="${AB_MODELS:-bonsai mtp}"
SLEEP_ENTRE="${AB_SLEEP:-45}"

mkdir -p "$LOG_DIR"
log() { echo "[$(date '+%H:%M:%S')] $*" | tee -a "$LOG_DIR/ab_loop.log"; }

# (16/11) CANAL DE CONTROLE — o painel (hub) manda pausar/retomar/rodar
# agora/rodar so um modelo por um arquivo. Nao é matar processo: o loop
# continua vivo e o dono ve o estado.
CTL="/home/nixos/.local/state/jarvis/nightwatch/ab_loop.control"
controle() {
    [ -f "$CTL" ] && cat "$CTL" 2>/dev/null || echo "run"
}
# Consome uma acao "pontual" (now / run:modelo) e limpa o arquivo.
consome_acao() {
    local c m
    c=$(controle)
    case "$c" in
        now) printf 'run' > "$CTL"; echo "now" ;;
        run:*) m="${c#run:}"; printf 'run' > "$CTL"; echo "$m" ;;
        *) echo "" ;;
    esac
}

# GUARD: uma instancia por vez. Duas instancias escreviam no mesmo log e
# davam leitura intercalada sem sentido (medido 16/11).
PIDFILE="/home/nixos/.local/state/jarvis/nightwatch/ab_loop.pid"
if [ -f "$PIDFILE" ]; then
    OLD=$(cat "$PIDFILE" 2>/dev/null)
    if [ -n "$OLD" ] && kill -0 "$OLD" 2>/dev/null; then
        echo "AB_LOOP: ja existe uma instancia viva (PID $OLD) — saindo" >&2
        exit 1
    fi
fi
echo $$ > "$PIDFILE"
echo "AB_LOOP: PID $$ em $(date '+%H:%M:%S')"

LOCK="/home/nixos/.local/state/jarvis/nightwatch/RUNNING.lock"

# Quem tem o RUNNING.lock aberto (= segura o flock). O lock e flock de
# verdade: some quando o processo morre. Se alguem segura durante a
# corrida, a corrida sai com "Outro loop em execucao" e nao mede nada.
lock_holders() {
    local out=""
    local inode
    inode=$(stat -c %i "$LOCK" 2>/dev/null)
    [ -z "$inode" ] && { echo "sem lock"; return; }
    for P in /proc/[0-9]*; do
        local pid=${P#/proc/}
        local cmd
        cmd=$(tr '\0' ' ' < "$P/cmdline" 2>/dev/null)
        case "$cmd" in
            *nightwatch*|*nixos-ai*)
                for FD in "$P"/fd/*; do
                    local t
                    t=$(readlink "$FD" 2>/dev/null)
                    case "$t" in
                        *RUNNING.lock*) out="$out $pid:${cmd:0:90}" ;;
                    esac
                done 2>/dev/null
                ;;
        esac
    done
    [ -z "$out" ] && out="(ninguem)" || out="${out# }"
    echo "$out"
}

# Se o loop for morto no meio, o FILHO (nightwatch.dungeon run) continua
# vivo e segura o RUNNING.lock -> a proxima corrida sai em 3s com
# "Outro loop em execucao" e nao mede nada (medido 16/11).
limpa_execucao_anterior() {
    local PIDS
    PIDS=$(ps -eo pid,args 2>/dev/null | grep "nightwatch[.]dungeon" | grep -v grep | awk '{print $1}')
    for PID in $PIDS; do
        kill -9 "$PID" 2>/dev/null
    done
    # espera o flock realmente soltar
    local i
    for i in $(seq 1 15); do
        PIDS=$(ps -eo pid,args 2>/dev/null | grep "nightwatch[.]dungeon" | grep -v grep | awk '{print $1}')
        [ -z "$PIDS" ] && break
        sleep 1
    done
    for PID in $PIDS; do
        kill -9 "$PID" 2>/dev/null
    done
    rm -f "$LOCK"
}

cleanup() {
    local PIDS
    PIDS=$(ps -eo pid,args 2>/dev/null | grep "nightwatch[.]dungeon" | grep -v grep | awk '{print $1}')
    for PID in $PIDS; do
        kill -9 "$PID" 2>/dev/null
    done
    rm -f "$LOCK"
    if [ "$(cat "$PIDFILE" 2>/dev/null)" = "$$" ]; then
        rm -f "$PIDFILE"
    fi
}
# TRAP que SAI: sem o exit, o SIGTERM do pkill era interceptado, o handler
# rodava e o loop CONTINUAVA VIVO — dois loops escreviam no mesmo log e o
# resultado era lixo intercalado (medido 16/11).
trap 'cleanup; exit 0' TERM INT
trap cleanup EXIT

run_ab() {
    local modelo="$1"
    local lane="$LANE_BASE/dungeon-$modelo"

    log "=== A/B para $modelo ==="

    # Sem execucao anterior pendurada (lock + processo orfao)
    limpa_execucao_anterior
    log "  lock holders no inicio: $(lock_holders)"

    # Lane = copia do baseline, do zero, a cada ciclo
    rm -rf "$lane"; mkdir -p "$lane"
    cd "$DUNGEON_SRC" || { log "  ERRO: sem $DUNGEON_SRC"; return 1; }
    for f in $(git ls-tree -r --name-only "$BASELINE_COMMIT" | grep -v __pycache__); do
        mkdir -p "$lane/$(dirname "$f")"
        git show "$BASELINE_COMMIT:$f" > "$lane/$f"
    done

    # Test do commit que tem o A*. O arquivo tem sys.path HARDCODED para o
    # repo original — sem reescrever, o pytest testa o repo original e o
    # checker da FALSO POSITIVO ("4 passed" sem o agente ter feito nada).
    git -C "$DUNGEON_SRC" show "$TEST_COMMIT:test_astar.py" \
        | sed "s|/home/nixos/projects/jarvis-dungeon/src|$lane/src|" \
        > "$lane/test_astar.py"
    chmod 444 "$lane/test_astar.py"
    cat > "$lane/conftest.py" << 'CONF'
import os, sys
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "src"))
CONF
    # nao commitar __pycache__ (o harness commita junto e polui o diff)
    printf '__pycache__/\n*.pyc\n' > "$lane/.gitignore"

    # Commit TUDO antes de rodar: o harness recusa criar branch em arvore
    # suja ("[safety] dirty tree -> Branch isolation failed").
    cd "$lane" || return 1
    git init -q && git add -A && \
        git -c user.email=lab@local -c user.name=lab commit -q -m "baseline"

    # Hot-swap: sobe o modelo deste braço na porta que o nightwatch espera
    if [ -x "$SWAP" ]; then
        bash "$SWAP" "$modelo" || { log "  ERRO: swap para $modelo falhou"; return 1; }
    fi

    # Fila limpa
    local QF="/home/nixos/.local/state/jarvis/nightwatch/task_queue-dungeon-$modelo.json"
    echo "[]" > "$QF"

    # Enqueue + run no ambiente nix (o repo tem o flake)
    cd "$REPO" || return 1
    export PYTHONPATH="$REPO/modules/ai/jarvis/src"
    # Timeout do LLM: default 120s (config.py: _env_int("JARVIS_LLM_TIMEOUT", 120)).
    # O patcher pede 4096 tokens de JSON patch — o bonsai gera a ~16 tok/s,
    # ou seja ~256s: com 120s ele SEMPRE estoura o timeout e nunca chega a
    # aplicar o patch (medido 16/11). Com 600s o patch volta.
    export JARVIS_LLM_TIMEOUT="${JARVIS_LLM_TIMEOUT:-600}"
    timeout 300 nix develop -c python3 -m nightwatch.dungeon enqueue --model "$modelo" 2>&1 | tail -1 | cut -c1-100

    local start=$(date +%s)
    # --kill-after: garante que o wrapper nix develop morra se travar
    timeout --kill-after=60 1800 nix develop -c python3 -m nightwatch.dungeon run --model "$modelo" \
        > "$LOG_DIR/run-$modelo.log" 2>&1
    local rc=$?
    local end=$(date +%s)
    local dur=$((end - start))
    log "  lock holders apos a corrida: $(lock_holders)"

    # Checker real: precisa do python do nix develop (pygame esta la).
    # Caminho do flake EXPLICITO para poder cd em outro diretorio.
    local checker_result
    checker_result=$(timeout 180 nix develop "$REPO" -c bash -c \
        "cd /tmp && python3 -m pytest -q '$lane/test_astar.py'" 2>&1 | grep -E "passed|failed|error" | tail -1)
    [ -z "$checker_result" ] && checker_result="sem resultado do checker"

    local diff_stat
    diff_stat=$(git -C "$lane" diff --stat 2>/dev/null | tail -1)
    [ -z "$diff_stat" ] && diff_stat="(sem diff)"

    # Guarda o patch produzido: sem isso nao da pra comparar O QUE cada
    # modelo escreveu, so que ele falhou. Compara contra o commit RAIZ
    # (o baseline) — diff vs HEAD sozinho pegaria o baseline inteiro.
    local stamp
    stamp=$(date +%H%M%S)
    local base_sha
    base_sha=$(git -C "$lane" rev-list --max-parents=0 HEAD 2>/dev/null | head -1)
    if [ -n "$base_sha" ]; then
        git -C "$lane" diff "$base_sha" HEAD -- "*.py" 2>/dev/null | head -250 \
            > "$LOG_DIR/patch-$modelo-$stamp.diff"
    else
        : > "$LOG_DIR/patch-$modelo-$stamp.diff"
    fi
    git -C "$lane" log --oneline -3 > "$LOG_DIR/commits-$modelo-$stamp.txt" 2>/dev/null

    log "Resultado $modelo: rc=$rc, dur=${dur}s"
    log "  Checker: $checker_result"
    log "  Diff: $diff_stat"

    printf '{"modelo":"%s","rc":%s,"dur":%s,"checker":"%s","patch_bytes":%s,"ck":"v2","ts":%s}\n' \
        "$modelo" "$rc" "$dur" "$(echo "$checker_result" | tr -d '"' | cut -c1-120)" \
        "$(wc -c < "$LOG_DIR/patch-$modelo-$stamp.diff" 2>/dev/null || echo 0)" "$(date +%s)" \
        >> "$LOG_DIR/results.jsonl"
}

CICLO=0
while true; do
    # (16/11) PAUSA: o painel manda, o loop espera sem morrer.
    while [ "$(controle)" = "pause" ]; do
        [ $((CICLO % 10)) -eq 0 ] && log "pausado pelo painel (aguardando)"
        sleep 10
    done
    # Acao pontual do painel: "now" (roda agora) ou "run:modelo".
    ACAO=$(consome_acao)
    CICLOS_MODELO="$MODELS"
    if [ -n "$ACAO" ]; then
        if [ "$ACAO" = "now" ]; then
            log "painel mandou: rodar agora"
        else
            log "painel mandou: rodar so $ACAO"
            CICLOS_MODELO="$ACAO"
        fi
    fi

    CICLO=$((CICLO + 1))
    log "========== CICLO $CICLO =========="
    for modelo in $CICLOS_MODELO; do
        run_ab "$modelo"
    done
    log "========== Ciclo $CICLO concluído =========="
    sleep "$SLEEP_ENTRE"
done
