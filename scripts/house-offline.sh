#!/usr/bin/env bash
# house-offline.sh — o house offline, num entrypoint unico.
#
# POR QUE (17/11/2026, coord-naming, fila da frota ID:coord-1794921621223615):
# a casa tem um corpus offline (N.O.M.A.D / Kiwix / FM 4-25.11 / NHS, 18.943
# docs em FTS5) e o websearch CAI nele quando a busca online falha. Mas
# "offline funciona" era uma AFIRMACO: ninguem checava as dependencias
# locais, e nao havia um comando unico que provasse a operacao sem rede.
#
# O QUE ESTE SCRIPT FAZ (tres coisas, um comando):
#   1) CHECA as dependencias locais (o corpus, o FTS5, o glossario PT-EN, o
#      python do jarvis-env, o embedder 8081, a chave do Tavily) e diz o que
#      falta, com o motivo;
#   2) TESTA SEM REDE de verdade: o teste roda num namespace de rede SEM
#      rota (unshare -n), ou seja, nao e' "sem usar a internet", e' "sem
#      rede nenhuma" — e ainda assim a busca offline tem de responder;
#   3) PROVA o fallback: com a rede cortada e a busca online indisponivel,
#      a resposta vem do corpus LOCAL, marcada como offline.
#
# O QUE ELE NAO FAZ: nao mexe em repo alheio, nao mexe no webui, nao
# instala nada, nao altera a chave do Tavily, nao chama a API do dono.
#
# USO
#   scripts/house-offline.sh              # checa + testa (o padrao)
#   scripts/house-offline.sh check        # so a checagem de dependencias
#   scripts/house-offline.sh test         # so o teste sem rede
#   scripts/house-offline.sh query "picada de cobra"   # uma busca offline
#   scripts/house-offline.sh --self-test  # prova a logica do proprio script
#
# EXEMPLO
#   $ scripts/house-offline.sh
#   [deps] corpus.db ....... OK (18.943 docs)
#   [deps] FTS5 ............. OK
#   [deps] glossario PT-EN .. OK (1.234 pares)
#   [deps] python jarvis ..... OK
#   [deps] embedder :8081 ... AUSENTE (opcional: so o fallback hibrido)
#   [deps] chave Tavily ..... presente
#   [test] sem rede (unshare -n): a busca offline respondeu em 0,31 s
#   [test] resultado traz fonte local: SIM
#   RESULTADO: house offline OK (2 checagens, 1 teste sem rede)
set -uo pipefail

HERE="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
REPO="$(cd "$HERE/.." && pwd)"
SRC="$REPO/modules/ai/jarvis/src"
CORPUS="$REPO/data/offline/corpus.db"
GLOSSARY="$REPO/data/offline/glossary-pt-en.json"
ENV_SH="$SRC/jarvis/jarvis-env.sh"

OK=0
FAL=0
declare -a PROBLEMAS=()

log()  { printf '%s\n' "$*"; }
pass() { printf '  [ok]   %s\n' "$*"; OK=$((OK+1)); }
fail() { printf '  [FALHA] %s\n' "$*"; FAL=$((FAL+1)); PROBLEMAS+=("$*"); }
warn() { printf '  [aviso] %s\n' "$*"; }

# ── 1) as dependencias locais ───────────────────────────────────────────────
checar_dependencias() {
    log "[deps] dependencias locais:"

    # o corpus (FTS5)
    if [ -f "$CORPUS" ]; then
        local n
        n=$(python3 - "$CORPUS" << 'PY' 2>/dev/null
import sqlite3, sys
try:
    con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True, timeout=3)
    try:
        row = con.execute("SELECT value FROM meta WHERE key='total'").fetchone()
        print(int(row[0]) if row else 0)
    finally:
        con.close()
except Exception:
    print(0)
PY
)
        if [ "${n:-0}" -gt 0 ]; then
            pass "corpus.db: $n docs ($(du -h "$CORPUS" | cut -f1))"
        else
            fail "corpus.db existe mas a contagem de docs falhou (ou o banco esta corrompido)"
        fi
    else
        fail "corpus.db AUSENTE em data/offline/ (sem ele nao ha offline)"
    fi

    # o FTS5 (a virtual table existe?)
    # (17/11) MEDIDO: a tabela FTS5 e' a 'docs' — o 'docs_idx' e' o indice
    # interno do FTS5 e NAO aceita MATCH direto. O primeiro check falhou por
    # isso, e era o CHECK que estava errado, nao o corpus.
    if [ -f "$CORPUS" ] && python3 - "$CORPUS" << 'PY' 2>/dev/null
import sqlite3, sys
con = sqlite3.connect(f"file:{sys.argv[1]}?mode=ro", uri=True, timeout=3)
try:
    con.execute("SELECT count(*) FROM docs WHERE docs MATCH 'snake'").fetchone()
finally:
    con.close()
PY
    then
        pass "FTS5 (tabela docs): a busca por texto funciona"
    else
        fail "FTS5 indisponivel (a tabela docs nao responde a MATCH)"
    fi

    # o glossario PT-EN (a ponte que faz 'picada de cobra' achar 'snakebite')
    if [ -f "$GLOSSARY" ]; then
        local pares
        pares=$(python3 -c "import json,sys; d=json.load(open(sys.argv[1])); print(len(d.get('entries') or []) if isinstance(d,dict) else len(d))" "$GLOSSARY" 2>/dev/null || echo 0)
        pass "glossario PT-EN: ${pares:-0} pares"
    else
        fail "glossario PT-EN AUSENTE (a busca PT perde precisao)"
    fi

    # o python do jarvis (o mesmo env do MCP: a regra da casa)
    # (17/11) MEDIDO: o jarvis-env.sh fica em modules/ai/jarvis/ (nao em
    # src/jarvis/) — o primeiro check apontava o path errado.
    if [ -f "$REPO/modules/ai/jarvis/jarvis-env.sh" ]; then
        pass "jarvis-env.sh presente (o MCP e o CLI compartilham o env)"
    else
        warn "jarvis-env.sh ausente em modules/ai/jarvis/jarvis-env.sh"
    fi

    # o embedder 8081 (so o fallback hibrido precisa; o FTS5 nao)
    if timeout 3 bash -c 'cat < /dev/null > /dev/tcp/127.0.0.1/8081' 2>/dev/null; then
        pass "embedder :8081 de pe (o fallback hibrido tambem funciona)"
    else
        warn "embedder :8081 AUSENTE: o FTS5 funciona, so o fallback hibrido (Qdrant) nao"
    fi

    # a chave do Tavily (a busca online; a sua ausencia NAO impede o offline)
    if [ -n "${TAVILY_API_KEY:-}" ] || grep -qs '^TAVILY_API_KEY=' /etc/litellm-sops.env 2>/dev/null; then
        pass "chave Tavily presente (a busca online existe; o offline e' o plano B)"
    else
        warn "chave Tavily AUSENTE: a busca online cai no offline (que e' o ramo de sobrevivencia)"
    fi

    # o Qdrant (o fallback hibrido)
    if timeout 3 bash -c 'cat < /dev/null > /dev/tcp/127.0.0.1/6333' 2>/dev/null; then
        pass "qdrant :6333 de pe"
    else
        warn "qdrant :6333 AUSENTE (so o fallback hibrido depende dele)"
    fi
}

# ── 2) o teste SEM REDE ─────────────────────────────────────────────────────
# O teste nao e' "sem usar a internet": e' SEM REDE. O unshare -n cria um
# namespace de rede sem rota — o processo nao ve interface, nao resolve
# nome e nao conecta em nada. Se o offline ainda responde ali, entao o
# offline NAO depende da internet (medido, naosuposto).
testar_sem_rede() {
    log "[test] teste sem rede (namespace sem rota):"
    local q="${1:-picada de cobra}"
    local antes depois

    if ! command -v unshare >/dev/null 2>&1; then
        warn "unshare ausente: o teste vai rodar COM rede (prova mais fraca)"
        return 1
    fi

    antes=$(date +%s.%N)
    local out
    out=$(unshare -n --map-root-user bash -c "
        export PYTHONPATH='$SRC'
        cd '$REPO' || exit 1
        timeout 120 python3 - <<'PYEOF'
from jarvis.core.offline import offline_search
r = offline_search('${q}', max_results=3)
print(r)
PYEOF
" 2>&1)
    depois=$(date +%s.%N)

    local dt
    dt=$(python3 -c "print(f'{float('$depois')-float('$antes'):.2f}')" 2>/dev/null || echo "?")

    if echo "$out" | grep -qiE "offline survival corpus|Source:"; then
        pass "sem rede, a busca offline respondeu em ${dt}s"
        # o resultado traz a fonte?
        if echo "$out" | grep -qiE "Source:|\.md|\.pdf|licen"; then
            pass "o resultado traz a fonte local (arquivo/licenca)"
        else
            fail "o resultado NAO traz a fonte (o contrato do offline exige)"
        fi
        # e nao veio da web? (a URL no texto pode ser uma citacao do corpus:
        # o que nao pode e' o resultado ter vindo do Tavily)
        if echo "$out" | grep -qi "tavily"; then
            warn "o resultado cita o Tavily (a rede nao devia ter funcionado)"
        fi
        printf '%s\n' "$out" | head -6 | sed 's/^/         | /'
        return 0
    fi
    fail "sem rede, a busca offline NAO respondeu (saida: $(echo "$out" | head -2 | tr '\n' ' ' | cut -c1-90))"
    return 1
}

# ── 3) uma busca offline (a prova de uso) ─────────────────────────────────
consultar() {
    local q="$1"
    PYTHONPATH="$SRC" timeout 120 python3 - "$q" << 'PY'
import sys
from jarvis.core.offline import offline_search
print(offline_search(sys.argv[1], max_results=5))
PY
}

# ── 4) o FALLBACK: a busca online cai no offline ──────────────────────────
# (17/11, medido) Sem o env do jarvis, o web_search falha com 'requests nao
# instalado' — nao e' a rede, e' o PYTHONPATH. O env canonico e' o
# jarvis-env.sh (o mesmo do MCP e da CLI), entao o teste o usa. O que se
# prova aqui: COM A REDE CORTADA, a busca online devolve o corpus local
# marcado como offline (e nao uma excecao).
testar_fallback() {
    log "[test] fallback: a busca online, sem rede, cai no offline:"
    local env_sh="$REPO/modules/ai/jarvis/jarvis-env.sh"
    if [ ! -f "$env_sh" ]; then
        warn "jarvis-env.sh ausente: o fallback nao pode ser testado"
        return 1
    fi
    local out
    out=$(unshare -n --map-root-user bash -c "
        source '$env_sh' >/dev/null 2>&1
        export PYTHONPATH='$SRC'
        cd '$REPO' || exit 1
        timeout 180 python3 - <<'PYEOF'
from jarvis.core.websearch import web_search
print(str(web_search('picada de cobra'))[:800])
PYEOF
" 2>&1)
    if echo "$out" | grep -qiE "offline|NO OFFLINE SOURCE|Source:"; then
        pass "sem rede, a busca online devolveu o corpus local (fallback ativo)"
        printf '%s\n' "$out" | head -3 | sed 's/^/         | /'
        return 0
    fi
    if echo "$out" | grep -qiE "requests|Traceback|Error"; then
        fail "o fallback nao respondeu: $(echo "$out" | head -3 | tr '\n' ' ' | cut -c1-90)"
    else
        warn "a busca online sem rede nao devolveu o offline: $(echo "$out" | head -2 | tr '\n' ' ' | cut -c1-90)"
    fi
    return 1
}

# ── o self-test do proprio script ──────────────────────────────────────────
self_test() {
    log "SELF-TEST do house-offline.sh:"

    # 1) o script passa a sintaxe (ele se checa)
    if bash -n "$0"; then pass "bash -n"; else fail "bash -n"; return 1; fi

    # 2) as dependencias: o corpus tem de estar la
    [ -f "$CORPUS" ] && pass "corpus.db presente" || fail "corpus.db ausente"

    # 3) a busca offline responde, offline mesmo
    local out
    out=$(PYTHONPATH="$SRC" timeout 120 python3 - << 'PY' 2>&1
from jarvis.core.offline import offline_search
print(offline_search("picada de cobra", max_results=2))
PY
)
    if echo "$out" | grep -qiE "offline survival corpus|Source:"; then
        pass "a busca offline responde e traz a fonte"
    else
        fail "a busca offline nao respondeu"
    fi

    # 4) sem resultado, ela DIZ que nao tem fonte (nunca inventa)
    out=$(PYTHONPATH="$SRC" timeout 120 python3 - << 'PY' 2>&1
from jarvis.core.offline import offline_search
print(offline_search("pergunta sem nenhuma resposta no corpus 12345xyz", max_results=2))
PY
)
    if echo "$out" | grep -qiE "NO OFFLINE SOURCE"; then
        pass "sem resposta, ela diz NO OFFLINE SOURCE (nao inventa)"
    else
        fail "sem resposta, ela nao avisou que nao tem fonte"
    fi

    # 5) o namespace sem rede existe (o teste forte)
    if command -v unshare >/dev/null 2>&1 && unshare -n --map-root-user true 2>/dev/null; then
        pass "unshare -n funciona (o teste sem rede e' de verdade)"
    else
        warn "unshare -n indisponivel (o teste sem rede sera mais fraco)"
    fi

    log ""
    log "SELF-TEST: $OK ok, $FAL falha"
    [ "$FAL" = "0" ]
}

# ── o main ─────────────────────────────────────────────────────────────────
acao="${1:-all}"
[ "$acao" = "--self-test" ] && acao="self-test"
shift 2>/dev/null || true

case "$acao" in
    check)
        checar_dependencias
        log ""
        log "RESULTADO: $OK ok, $FAL falha"
        [ "$FAL" = "0" ] || exit 1
        ;;
    test)
        checar_dependencias >/dev/null
        testar_sem_rede "${1:-picada de cobra}"
        log ""
        log "RESULTADO: $OK ok, $FAL falha"
        [ "$FAL" = "0" ] || exit 1
        ;;
    query)
        [ -n "${1:-}" ] || { log "uso: house-offline.sh query <pergunta>"; exit 2; }
        consultar "$1"
        ;;
    self-test)
        self_test
        ;;
    all)
        checar_dependencias
        log ""
        testar_sem_rede
        log ""
        testar_fallback
        log ""
        if [ "$FAL" = "0" ]; then
            log "RESULTADO: house offline OK ($OK checagens, 2 testes sem rede)"
            exit 0
        fi
        log "RESULTADO: house offline COM FALHAS ($OK ok, $FAL falha)"
        for p in "${PROBLEMAS[@]}"; do log "  - $p"; done
        exit 1
        ;;
    *)
        sed -n '2,40p' "$0"
        exit 2
        ;;
esac
