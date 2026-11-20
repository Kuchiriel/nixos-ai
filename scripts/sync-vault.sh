#!/bin/bash
# Sync important docs to Obsidian vault (not everything)
# Run: ./scripts/sync-vault.sh
#
# (20/11) AGENTS.md e CONTRATO OPERACIONAL: copiar o arquivo inteiro criou
# 100 copias estaleiros no vault. A copia do nixos-ai (12/11) ainda mandava
# consultar a tabela `part` (congelada) — ler isso ja fez o `prune` apagar
# 4 agentes VIVOS. Agora o vault recebe um PONTEIRO com sha256 do canonico.
set -uo pipefail

VAULT=~/vaults/projects
SRC=~/projects/nixos-ai

write_agents_pointer() {
    local src="$1" dst="$2"
    [ -f "$src" ] || return 0
    mkdir -p "$(dirname "$dst")"
    local sum
    sum=$(sha256sum "$src" | cut -d' ' -f1)
    cat > "$dst" <<EOF
# AGENTS.md — ponteiro gerado por scripts/sync-vault.sh

> **NAO editar esta copia.** Contrato canonico: \`$src\`
> sha256: \`$sum\`
> Atualizado: $(date -u +%Y-%m-%dT%H:%M:%SZ)

Abra o arquivo canonico acima antes de agir. Copias estaleiras de AGENTS.md
ja causaram decisoes erradas (liveness pela tabela part).
EOF
}

# Only sync curated docs, not raw code
echo "Syncing curated docs to vault..."

# Architecture (Mermaid diagrams render here)
mkdir -p $VAULT/nixos-ai/architecture
for f in $SRC/docs/ARCHITECTURE.mmd $SRC/docs/JARVIS-COMPARISON.mmd $SRC/docs/SELF-IMPROVEMENT-LOOP.mmd; do
    if [ -f "$f" ]; then
        name=$(basename "$f" .mmd)
        echo "# $name" > $VAULT/nixos-ai/architecture/${name}.md
        echo "" >> $VAULT/nixos-ai/architecture/${name}.md
        echo '```mermaid' >> $VAULT/nixos-ai/architecture/${name}.md
        cat "$f" >> $VAULT/nixos-ai/architecture/${name}.md
        echo '```' >> $VAULT/nixos-ai/architecture/${name}.md
    fi
done

# Key docs only
for doc in README.md HANDOFF.md NIGHTLOG.md; do
    [ -f "$SRC/$doc" ] && cp "$SRC/$doc" "$VAULT/nixos-ai/"
done
write_agents_pointer "$SRC/AGENTS.md" "$VAULT/nixos-ai/AGENTS.md"

# Audit reports
mkdir -p $VAULT/nixos-ai/audits
cp $SRC/docs/PLATFORM-AUDIT-2026-08-30.md $VAULT/nixos-ai/audits/ 2>/dev/null
cp $SRC/docs/JARVIS-MCU-PARITY.md $VAULT/nixos-ai/audits/ 2>/dev/null
cp $SRC/docs/MONOREPO-SCHEMA-2026.md $VAULT/nixos-ai/guides/ 2>/dev/null

# AGENTS.md from all projects
for dir in ~/projects/*/; do
    name=$(basename "$dir")
    src="${dir%/}/AGENTS.md"
    [ -f "$src" ] && write_agents_pointer "$src" "$VAULT/$name/AGENTS.md"
done

echo "Done. Vault files:"
find $VAULT -name "*.md" -type f | wc -l
