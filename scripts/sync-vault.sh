#!/bin/bash
# Sync important docs to Obsidian vault (not everything)
# Run: ./scripts/sync-vault.sh

VAULT=~/vaults/projects
SRC=~/projects/nixos-ai

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
for doc in AGENTS.md README.md HANDOFF.md NIGHTLOG.md; do
    [ -f "$SRC/$doc" ] && cp "$SRC/$doc" "$VAULT/nixos-ai/"
done

# Audit reports
mkdir -p $VAULT/nixos-ai/audits
cp $SRC/docs/PLATFORM-AUDIT-2026-08-30.md $VAULT/nixos-ai/audits/ 2>/dev/null
cp $SRC/docs/JARVIS-MCU-PARITY.md $VAULT/nixos-ai/audits/ 2>/dev/null
cp $SRC/docs/MONOREPO-SCHEMA-2026.md $VAULT/nixos-ai/guides/ 2>/dev/null

# AGENTS.md from all projects
for dir in ~/projects/*/; do
    name=$(basename "$dir")
    [ -f "$dir/AGENTS.md" ] && mkdir -p "$VAULT/$name" && cp "$dir/AGENTS.md" "$VAULT/$name/"
done

echo "Done. Vault files:"
find $VAULT -name "*.md" -type f | wc -l
