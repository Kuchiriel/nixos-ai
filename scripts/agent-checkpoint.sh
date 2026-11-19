#!/usr/bin/env bash
# agent-checkpoint.sh — checkpoint de 4 camadas em 1 comando (genérico do monorepo).
#
# USO:
#   ./agent-checkpoint.sh --project <path> --era "<título da era>" \
#                         --summary "<resumo do estado>" [--queue <arquivo>] \
#                         [--pains auto|<arquivo>] [--no-commit] [--dry-run]
#
# O QUE FAZ (as 4 camadas do protocolo de rehydration, em ordem):
#   1. md    → nota de topo no AGENTS-QUEUE.md + commit (o commit da fila acorda o colega)
#   2. rag   → re-index da árvore do projeto
#   3. mem   → 1 evento de memória com o resumo da era
#   4. vault → nota HANDOFF-<data>-<slug> no vault + commit do repo do vault
#
# CONTRATO:
#   - Genérico: funciona em qualquer repo do monorepo (detecta a raiz git, a fila e o vault).
#   - Cada camada é independente: a falha de uma não aborta as outras (o relatório mostra o status).
#   - Idempotente por data+era: rodar 2x no mesmo dia não duplica a nota (ele reescreve a seção).
#   - --pains auto anexa o digest de `agent-pains.sh` (erros de CLI/dores) no vault.
#   - Sai != 0 se TODAS as camadas falharem; sai 0 se pelo menos uma passou.
#
# 1 FATO = 1 LUGAR (08/11, medido): antes o mesmo $SUMMARY ia inteiro na fila,
# na memória e no vault — o rehydrate recebia o mesmo texto 3x (o clip de 600
# chars por linha mascarava o custo, não a duplicação). Agora:
#   fila   = ESTADO da era (curto: 1 linha + ponteiro para o HANDOFF)
#   vault  = DETALHE completo (texto integral; é o original a ler)
#   memória= 1 evento atômico (curto + ponteiro para o HANDOFF)
#   pains  = digest só no vault; a fila aponta para docs/pains/PAINS.md
# Quem lê: `jarvis_rehydrate` (fila top + HANDOFF + memórias) e o `coord`
# (bus GitHub + roster) — nenhum precisa do texto completo nos três lugares.
set -uo pipefail

PROJECTS_ROOT="${PROJECTS_ROOT:-$HOME/projects}"
JARVIS_CLI="${JARVIS_CLI:-$(dirname "$(realpath "$0")")/jarvis-cli.sh}"
PAINS_SH="${PAINS_SH:-$(dirname "$(realpath "$0")")/agent-pains.sh}"
VAULT_DIR="${VAULT_DIR:-$HOME/.local/state/jarvis/vault}"

PROJ=""; ERA=""; SUMMARY=""; QUEUE=""; PAINS="auto"; COMMIT=1; DRY=0
while [ $# -gt 0 ]; do
  case "$1" in
    --project) PROJ="$2"; shift 2;;
    --era) ERA="$2"; shift 2;;
    --summary) SUMMARY="$2"; shift 2;;
    --queue) QUEUE="$2"; shift 2;;
    --pains) PAINS="$2"; shift 2;;
    --no-commit) COMMIT=0; shift;;
    --dry-run) DRY=1; shift;;
    *) echo "flag desconhecida: $1" >&2; exit 2;;
  esac
done
[ -n "$PROJ" ] && [ -n "$ERA" ] && [ -n "$SUMMARY" ] || {
  echo "uso: agent-checkpoint.sh --project P --era T --summary S [--queue F] [--pains auto|F] [--no-commit] [--dry-run]" >&2
  exit 2
}

log() { printf '%s\n' "$*"; }
ok()  { log "  [ok]   $*"; }
fail(){ log "  [FALHA] $*"; }

PROJ_ABS=$(cd "$PROJ" 2>/dev/null && pwd) || { echo "projeto inexistente: $PROJ" >&2; exit 2; }
GIT_ROOT=$(git -C "$PROJ_ABS" rev-parse --show-toplevel 2>/dev/null || echo "$PROJ_ABS")
DATA=$(date +%Y-%m-%d); HORA=$(date +%H:%M); DATE="$DATA"
NIXOS_DIR="$(dirname "$(dirname "$(realpath "$0")")")"

# roda a CLI do JARVIS: tenta o python do sistema; se faltar dependencia,
# refaz dentro do nix develop (onde o jarvis e as deps vivem)
#
# JARVIS_RUN_TIMEOUT (default 1800s): teto de relogio por chamada. Medido
# 08/11: um `rag-index` ficou 13h em `poll` num socket do :8081 (servidor
# saudavel, rchar congelado) — sem teto, o checkpoint inteiro pendura e o
# agente nunca termina. Index morto no meio e seguro: upsert no Qdrant e
# idempotente por id, rodar de novo completa.
jarvis_run() {
  local out tmo="${JARVIS_RUN_TIMEOUT:-1800}"
  out=$(timeout "$tmo" "$JARVIS_CLI" "$@" 2>&1 | tail -3)
  if printf '%s' "$out" | grep -qiE "ModuleNotFoundError|ModuleNotFound|No module named"; then
    out=$(cd "$NIXOS_DIR" && timeout "$tmo" nix develop --command "$JARVIS_CLI" "$@" 2>&1 | tail -3)
  fi
  printf '%s' "$out"
}
SLUG=$(printf '%s' "$ERA" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-|-$//g' | cut -c1-50)
[ -n "$SLUG" ] || SLUG="checkpoint"
HANDOFF_REL="HANDOFF-$DATA-$SLUG.md"

# resumo CURTO para a fila e a memória (1 fato = 1 lugar): 1 linha, <=280 chars.
# O texto integral fica só no vault (HANDOFF-<data>-<slug>.md).
SUMMARY_SHORT=$(printf '%s' "$SUMMARY" | tr '\n\t' '  ' | sed -E 's/[[:space:]]+/ /g; s/^ //; s/ $//')
if [ "${#SUMMARY_SHORT}" -gt 280 ]; then
  # (10/11) corta em LIMITE DE FRASE, não no meio da palavra: medido, o topo
  # da fila terminava em "Resultado: NENHU..." e a conclusao da era ficava
  # ilegivel justamente no artefato que todo mundo le primeiro. Se nao ha
  # ponto/ponto e virgula no corte, cai na ultima palavra.
  SUMMARY_SHORT=$(printf '%s' "$SUMMARY_SHORT" | awk '{
    s = substr($0, 1, 280); cut = 0;
    for (i = length(s); i > 0; i--) {
      c = substr(s, i, 1);
      if (c == "." || c == ";") { cut = i; break }
    }
    if (cut < 120) {
      cut = 0;
      for (i = length(s); i > 0; i--) {
        if (substr(s, i, 1) == " ") { cut = i; break }
      }
    }
    if (cut > 0) s = substr(s, 1, cut);
    sub(/[.;]$/, "", s);
    print s "...";
  }')
fi

# fila: a do projeto se existir, senão a do monorepo
if [ -z "$QUEUE" ]; then
  if [ -f "$GIT_ROOT/AGENTS-QUEUE.md" ]; then QUEUE="$GIT_ROOT/AGENTS-QUEUE.md"
  elif [ -f "$PROJECTS_ROOT/AGENTS-QUEUE.md" ]; then QUEUE="$PROJECTS_ROOT/AGENTS-QUEUE.md"
  else QUEUE=""; fi
fi

# digest de pains (erros de CLI / dores) para anexar
PAINS_BLOCK=""
if [ "$PAINS" = "auto" ]; then
  PAINS_BLOCK=$("$PAINS_SH" digest --days 3 --limit 10 2>/dev/null || true)
elif [ -n "$PAINS" ] && [ -f "$PAINS" ]; then
  PAINS_BLOCK=$(cat "$PAINS")
fi

log "== CHECKPOINT $DATA $HORA =="
log "projeto: $PROJ_ABS (git: $GIT_ROOT)"
log "era:     $ERA"

# ---------- 1. md: nota de topo na fila + commit ----------
MD_STATUS="pulado"
if [ -n "$QUEUE" ] && [ -f "$QUEUE" ]; then
  if [ "$DRY" -eq 1 ]; then
    MD_STATUS="dry-run: seria $QUEUE"
  else
    NOTE=$(cat <<EOF
## ⭐ CHECKPOINT $DATA $HORA — $ERA

**Projeto:** \`$GIT_ROOT\` · **Resumo:** $SUMMARY_SHORT

**Detalhe completo:** vault \`$HANDOFF_REL\` (este é o original; a fila não o copia).
**Pains/erros recentes (capturados automaticamente):** ver \`docs/pains/PAINS.md\`.

EOF
)
    TMP=$(mktemp)
    # `$(...)` remove os newlines finais -> sem o \n\n a nota nova gruda na
    # anterior e o heading "## ⭐" da fila antiga vira texto de parágrafo
    # (o _rehydrate_queue então não acha o corte e serve 2 checkpoints).
    #
    # (10/11) ESCRITA SEGURA da fila compartilhada: o read-modify-write
    # (cat -> mv) não é atômico, e entre os dois a nota de outra lane
    # sumia. Medido 10/11: o watcher viu o topo da fila trocar de era no
    # meio de outra escrita (a peer e eu gravando ao mesmo tempo). Agora:
    # flock serializa os checkpoint entre lanes e, com verificação de hash,
    # a leitura é refeita se o arquivo mudou entre ler e gravar (quando a
    # outra lane escreveu à mão, sem lock).
    _mode=$(stat -c '%a' "$QUEUE" 2>/dev/null || echo 644)
    _qfd=""
    exec {_qfd}>"${QUEUE}.lock" 2>/dev/null || _qfd=""
    [ -n "$_qfd" ] && flock -w 30 "$_qfd" 2>/dev/null || true
    _try=0
    _written=0
    while [ "$_try" -lt 3 ]; do
      _try=$((_try + 1))
      _before=$(cksum < "$QUEUE" 2>/dev/null | awk '{print $1"-"$2}')
      { printf '%s\n\n' "$NOTE"; cat "$QUEUE"; } > "$TMP"
      _after=$(cksum < "$QUEUE" 2>/dev/null | awk '{print $1"-"$2}')
      if [ "$_before" = "$_after" ]; then
        chmod "$_mode" "$TMP" 2>/dev/null || true
        mv "$TMP" "$QUEUE"
        _written=1
        break
      fi
      log "  fila mudou enquanto eu lia: refazendo (tentativa $((_try + 1)))"
    done
    [ "$_written" = "1" ] || { MD_STATUS="FALHOU: a fila mudou 3x durante a escrita"; POINTER_BROKEN=1; }
    [ -n "$_qfd" ] && exec {_qfd}>&- 2>/dev/null || true
    if [ "$COMMIT" -eq 1 ]; then
      QROOT=$(git -C "$(dirname "$QUEUE")" rev-parse --show-toplevel 2>/dev/null || dirname "$QUEUE")
      if git -C "$QROOT" add -- "$QUEUE" 2>/dev/null && git -C "$QROOT" commit -q -m "docs(queue): checkpoint $DATA — $ERA" 2>/dev/null; then
        MD_STATUS="nota de topo + commit em $(basename "$QROOT")"
      else
        MD_STATUS="nota de topo escrita (commit falhou/não aplicável)"
      fi
    else
      MD_STATUS="nota de topo escrita (sem commit)"
    fi
  fi
  ok "md: $MD_STATUS ($QUEUE)"
else
  fail "md: nenhuma AGENTS-QUEUE.md encontrada (use --queue)"
fi

# ---------- 2. rag: re-index ----------
RAG_STATUS="pulado"
if [ "$DRY" -eq 0 ] && [ -x "$JARVIS_CLI" ]; then
  OUT=$(jarvis_run rag-index "$PROJ_ABS")
  if printf '%s' "$OUT" | grep -qiE "indexed|index"; then RAG_STATUS="$OUT"
  else RAG_STATUS="falhou: $OUT"; fi
else
  RAG_STATUS="dry-run"
fi
ok "rag: $RAG_STATUS"

# ---------- 3. mem: memória ----------
MEM_STATUS="pulado"
if [ "$DRY" -eq 0 ] && [ -x "$JARVIS_CLI" ]; then
  MEMTEXT="CHECKPOINT $DATA $HORA — $ERA [$GIT_ROOT]: $SUMMARY_SHORT (detalhe: $HANDOFF_REL)"
  OUT=$(jarvis_run remember "$MEMTEXT")
  if printf '%s' "$OUT" | grep -qiE "stored|id|ok"; then MEM_STATUS="$OUT"
  else MEM_STATUS="falhou: $OUT"; fi
else
  MEM_STATUS="dry-run"
fi
ok "mem: $MEM_STATUS"

# ---------- 4. vault: HANDOFF ----------
VAULT_STATUS="pulado"
HANDOFF="$VAULT_DIR/$HANDOFF_REL"
if [ "$DRY" -eq 0 ]; then
  mkdir -p "$VAULT_DIR"
  {
    printf '# HANDOFF %s %s — %s\n\n' "$DATA" "$HORA" "$ERA"
    printf -- '- **Projeto:** `%s`\n' "$GIT_ROOT"
    printf -- '- **Data:** %s %s\n\n' "$DATA" "$HORA"
    printf '## Estado\n\n%s\n\n' "$SUMMARY"
    if [ -n "$PAINS_BLOCK" ]; then printf '## Pains / erros de CLI (auto)\n\n%s\n\n' "$PAINS_BLOCK"; fi
    printf '## Fila\n\n`%s` (nota de topo: %s)\n\n' "${QUEUE:-sem fila}" "$ERA"
    printf '## Rehydration\n\n1. este HANDOFF · 2. topo da fila · 3. memórias · 4. RAG\n'
  } > "$HANDOFF"
  if [ "$COMMIT" -eq 1 ] && git -C "$VAULT_DIR" rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    # (19/11) `add -A` DENTRO do repo do vault, nao no monorepo: o commit
    # anterior so pegava a nota deste handoff e 276 notas de outras vias
    # (vault_write sem commit, corpora, HANDOFFs manuais) ficaram untracked
    # por um mes num vault sem remote. O vault e um repo de um proposito so.
    git -C "$VAULT_DIR" add -A 2>/dev/null
    if git -C "$VAULT_DIR" commit -q -m "handoff: $ERA ($DATA)" 2>/dev/null; then VAULT_STATUS="nota + commit"
    else VAULT_STATUS="nota escrita (commit falhou)"; fi
  else
    VAULT_STATUS="nota escrita"
  fi
  # (10/11) READ BACK: a fila (passo 1) ja aponta para esta nota, entao uma
  # escrita que nao persistiu deixa um ponteiro quebrado. Medido 10/11: o
  # topo da fila apontava para HANDOFF-2026-11-10-prova-do-wakeword.md e o
  # arquivo nao existia em lugar nenhum. Regra da casa: write -> read back ->
  # so depois "ok" (o Qdrant ja aceitou um write com HTTP 200 e nao
  # persistiu, e quem confiou no status perdeu 6 pontos).
  if [ -s "$HANDOFF" ] && grep -qF "$ERA" "$HANDOFF" 2>/dev/null; then
    VAULT_STATUS="$VAULT_STATUS (lida de volta)"
  else
    VAULT_STATUS="FALHOU: a nota nao persistiu (a fila aponta para ela)"
    POINTER_BROKEN=1
  fi
  # espelha no JARVIS (indexa a nota no RAG do vault)
  [ -x "$JARVIS_CLI" ] && jarvis_run vault-write "handoff-$DATE-$SLUG" "$(cat "$HANDOFF")" >/dev/null 2>&1 || true
else
  VAULT_STATUS="dry-run"
fi
if [ "${POINTER_BROKEN:-0}" = "1" ]; then
  fail "vault: a nota do HANDOFF nao persistiu, e a fila ja aponta para ela"
else
  ok "vault: $VAULT_STATUS ($HANDOFF)"
fi

# ---------- 5. sessions: refresh opencode session summaries + consolidation (best-effort) ----------
SESS_STATUS="pulado"
SESS_IDX="$NIXOS_DIR/scripts/index_opencode_sessions.py"
SESS_CONS="$NIXOS_DIR/scripts/consolidate_sessions_memory.py"
if [ "$DRY" -eq 0 ] && [ -f "$SESS_IDX" ]; then
  SESS_TMO="${SESSIONS_INDEX_TIMEOUT:-600}"
  OUT=$(timeout "$SESS_TMO" python3 "$SESS_IDX" --incremental 2>&1 | tail -3)
  if printf '%s' "$OUT" | grep -qiE "ModuleNotFoundError|ModuleNotFound|No module named"; then
    OUT=$(cd "$NIXOS_DIR" && timeout "$SESS_TMO" nix develop -c python3 scripts/index_opencode_sessions.py --incremental 2>&1 | tail -3)
  fi
  SESS_STATUS="$OUT"
  if [ -f "$SESS_CONS" ]; then
    OUT2=$(timeout "$SESS_TMO" python3 "$SESS_CONS" --incremental 2>&1 | tail -2)
    if printf '%s' "$OUT2" | grep -qiE "ModuleNotFoundError|ModuleNotFound|No module named"; then
      OUT2=$(cd "$NIXOS_DIR" && timeout "$SESS_TMO" nix develop -c python3 scripts/consolidate_sessions_memory.py --incremental 2>&1 | tail -2)
    fi
    SESS_STATUS="$SESS_STATUS | $OUT2"
  fi
else
  SESS_STATUS="dry-run"
fi
ok "sessions: $SESS_STATUS"

log "== fim do checkpoint =="

# (10/11) exit != 0 quando a fila ficou com ponteiro quebrado: quem chama o
# checkpoint (o agente, o watcher) precisa ver a falha, nao um "ok" bonito.
if [ "${POINTER_BROKEN:-0}" = "1" ]; then
  exit 1
fi

# (01/11) avisa o agents-watcher que houve checkpoint AGORA (o watcher nao ve
# o que o agente roda fora dele): marcador global + snapshot para o dedupe.
_WDIR="/tmp/opencode/agents-watcher"
[ -d "$_WDIR" ] && date +%s > "$_WDIR/ultimo_checkpoint"
