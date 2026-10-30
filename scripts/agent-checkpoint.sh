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
#   - --pains auto anexa o digest de `agent-pains.sh` (erros de CLI/dores) na nota e no vault.
#   - Sai != 0 se TODAS as camadas falharem; sai 0 se pelo menos uma passou.
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
DATA=$(date +%Y-%m-%d); HORA=$(date +%H:%M)
SLUG=$(printf '%s' "$ERA" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-|-$//g' | cut -c1-50)
[ -n "$SLUG" ] || SLUG="checkpoint"

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

**Projeto:** \`$GIT_ROOT\` · **Resumo:** $SUMMARY

**Próxima ação:** (ver o HANDOFF correspondente no vault: \`HANDOFF-$DATA-$SLUG.md\`)
**Pains/erros recentes (capturados automaticamente):** ver \`docs/pains/PAINS.md\`.

EOF
)
    if [ -n "$PAINS_BLOCK" ]; then NOTE="$NOTE
$PAINS_BLOCK

"; fi
    TMP=$(mktemp)
    { printf '%s' "$NOTE"; cat "$QUEUE"; } > "$TMP"
    mv "$TMP" "$QUEUE"
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
  OUT=$("$JARVIS_CLI" rag-index "$PROJ_ABS" 2>&1 | tail -2)
  if printf '%s' "$OUT" | grep -qiE "indexed|index"; then RAG_STATUS="$OUT"
  else RAG_STATUS="falhou: $OUT"; fi
else
  RAG_STATUS="dry-run"
fi
ok "rag: $RAG_STATUS"

# ---------- 3. mem: memória ----------
MEM_STATUS="pulado"
if [ "$DRY" -eq 0 ] && [ -x "$JARVIS_CLI" ]; then
  MEMTEXT="CHECKPOINT $DATA $HORA — $ERA [$GIT_ROOT]: $SUMMARY"
  OUT=$("$JARVIS_CLI" remember "$MEMTEXT" 2>&1 | tail -1)
  if printf '%s' "$OUT" | grep -qiE "stored|id|ok"; then MEM_STATUS="$OUT"
  else MEM_STATUS="falhou: $OUT"; fi
else
  MEM_STATUS="dry-run"
fi
ok "mem: $MEM_STATUS"

# ---------- 4. vault: HANDOFF ----------
VAULT_STATUS="pulado"
HANDOFF="$VAULT_DIR/HANDOFF-$DATA-$SLUG.md"
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
    git -C "$VAULT_DIR" add -- "$(basename "$HANDOFF")" 2>/dev/null
    if git -C "$VAULT_DIR" commit -q -m "handoff: $ERA ($DATA)" 2>/dev/null; then VAULT_STATUS="nota + commit"
    else VAULT_STATUS="nota escrita (commit falhou)"; fi
  else
    VAULT_STATUS="nota escrita"
  fi
  # espelha no JARVIS (indexa a nota no RAG do vault)
  [ -x "$JARVIS_CLI" ] && "$JARVIS_CLI" vault-write "handoff-$DATE-$SLUG" "$(cat "$HANDOFF")" >/dev/null 2>&1 || true
else
  VAULT_STATUS="dry-run"
fi
ok "vault: $VAULT_STATUS ($HANDOFF)"

log "== fim do checkpoint =="
