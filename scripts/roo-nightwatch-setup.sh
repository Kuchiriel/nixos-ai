#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════
# Roo Code Nightwatch Setup Helper
# Verifica se auto-approve está configurado para modo autônomo.
# ══════════════════════════════════════════════════════════════
set -euo pipefail

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

ROO_GLOBAL="$HOME/.config/VSCodium/User/globalStorage/rooveterinaryinc.roo-cline"
MCP_SETTINGS="$ROO_GLOBAL/settings/mcp_settings.json"

echo -e "${CYAN}═══ Roo Code Nightwatch Setup ═══${NC}"
echo ""

# ── 1. Verificar MCP alwaysAllow ──
echo -e "${YELLOW}[1/4] Verificando MCP alwaysAllow...${NC}"
if [ -f "$MCP_SETTINGS" ]; then
    for server in tavily-search jarvis nixos-mcp context7; do
        has=$(grep -o "\"$server\"" "$MCP_SETTINGS" >/dev/null 2>&1 && \
              python3 -c "
import json, sys
with open('$MCP_SETTINGS') as f:
    d = json.load(f)
s = d.get('mcpServers', {}).get('$server', {})
a = s.get('alwaysAllow', [])
print('yes' if a else 'no')
" 2>/dev/null || echo "skip")
        if [ "$has" = "yes" ]; then
            echo -e "  ${GREEN}✓${NC} $server"
        elif [ "$has" = "no" ]; then
            echo -e "  ${RED}✗${NC} $server — SEM alwaysAllow"
        else
            echo -e "  ${YELLOW}?${NC} $server — não verificável (rode dentro de nix develop)"
        fi
    done
else
    echo -e "  ${RED}✗${NC} mcp_settings.json não encontrado"
fi

# ── 2. Verificar .roomodes ──
echo ""
echo -e "${YELLOW}[2/4] Verificando custom modes...${NC}"
ROOMODES="${ROOMODES:-$HOME/projects/nixos-ai/.roomodes}"
if [ -f "$ROOMODES" ]; then
    for mode in nightwatch organizer code; do
        # Check if slug exists and has mcp in its groups section
        has_mcp=$(awk "/slug: $mode/{found=1} found && /groups:/{grp=1} grp && /- mcp/{print \"yes\"; exit} grp && /^  - slug:/{exit}" "$ROOMODES" 2>/dev/null || echo "no")
        if [ "$has_mcp" = "yes" ]; then
            echo -e "  ${GREEN}✓${NC} $mode — group mcp"
        else
            echo -e "  ${YELLOW}⚠${NC} $mode — sem group mcp"
        fi
    done
else
    echo -e "  ${RED}✗${NC} .roomodes não encontrado"
fi

# ── 3. Verificar serviços ──
echo ""
echo -e "${YELLOW}[3/4] Verificando serviços...${NC}"
for svc in "LLM:8080" "Embed:8081" "Rerank:8082" "Qdrant:6333"; do
    name="${svc%%:*}"
    port="${svc##*:}"
    if curl -sf "http://127.0.0.1:$port/health" >/dev/null 2>&1 || \
       curl -sf "http://127.0.0.1:$port/healthz" >/dev/null 2>&1; then
        echo -e "  ${GREEN}✓${NC} $name (porta $port)"
    else
        echo -e "  ${RED}✗${NC} $name (porta $port) — inativo"
    fi
done

# ── 4. Instruções ──
echo ""
echo -e "${CYAN}═══ Auto-Approve (não automatizável via Nix) ═══${NC}"
echo ""
echo "O auto-approve do Roo Code fica no globalState do VS Code."
echo "Não existe setting.json para configurar — só a UI."
echo ""
echo -e "  ${CYAN}1.${NC} Abra o VSCodium"
echo -e "  ${CYAN}2.${NC} Painel do Roo Code → dropdown ${YELLOW}Auto-Approve${NC}"
echo -e "  ${CYAN}3.${NC} Clique ${GREEN}Enabled${NC}"
echo -e "  ${CYAN}4.${NC} Ative:"
echo -e "      ${GREEN}✓${NC} Read files"
echo -e "      ${GREEN}✓${NC} Edit files"
echo -e "      ${GREEN}✓${NC} Execute commands"
echo -e "      ${GREEN}✓${NC} Use MCP servers"
echo -e "      ${GREEN}✓${NC} Switch modes"
echo -e "      ${GREEN}✓${NC} Create subtasks"
echo ""
echo "Ou atalho: ${YELLOW}Ctrl+Alt+A${NC}"
echo ""
echo -e "${CYAN}═══ Prompt para Nightwatch ═══${NC}"
echo ""
cat <<'PROMPT'
Modo: nightwatch

You are working autonomously on the nixos-ai repository.
NEVER stop. NEVER ask the user. NEVER say "done" or "complete".
After EVERY action, immediately take the next one.

If your context gets condensed:
1. Read NIGHTLOG.md to see what you did last
2. Read AGENTS.md for the rules
3. Continue from the last logged cycle

Cycle: scan → fix → test → commit → log → repeat forever.

Use MCP tools: tavily_search for research, jarvis_execute for shell,
nix for package queries.

Start now. First action: git log --oneline -5
PROMPT
