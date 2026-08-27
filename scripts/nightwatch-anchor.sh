#!/usr/bin/env bash
# ══════════════════════════════════════════════════════════════
# Nightwatch Anchor Script — Ancoragem pra loop autônomo
# ══════════════════════════════════════════════════════════════
#
# Este script fornece contexto resumido pra uma sessão de IA
# que precisa retomar um loop de melhoria contínua.
#
# Uso:
#   cat scripts/nightwatch-anchor.sh | head -100  # contexto rápido
#   ./scripts/nightwatch-anchor.sh status         # estado atual
#   ./scripts/nightwatch-anchor.sh cycle           # executar 1 ciclo
#
# ══════════════════════════════════════════════════════════════

set -euo pipefail
cd "$(dirname "$0")/.."

# ── Cores ──
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
CYAN='\033[0;36m'
NC='\033[0m'

# ═══ CONTEXTO RÁPIDO ═══
print_context() {
    echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
    echo -e "${CYAN} NIGHTWATCH ANCHOR — Contexto do Projeto${NC}"
    echo -e "${CYAN}═══════════════════════════════════════════════════${NC}"
    echo ""
    echo "Projeto: nixos-ai (JARVIS on NixOS)"
    echo "Stack: NixOS, Python, llama.cpp, Qwen3.6-35B-A3B"
    echo "Hardware: RTX 4050 6GB, i7-13620H, 32GB RAM"
    echo ""
    echo "Servidores (NÃO reiniciar):"
    echo "  - llama-cpp-server (port 8080) — LLM backend"
    echo "  - qdrant (port 6333) — Vector DB"
    echo ""
    echo "Regras:"
    echo "  1. NÃO mate o llama-server"
    echo "  2. Commits pequenos e atômicos"
    echo "  3. TESTE antes de commitar"
    echo "  4. Registre em NIGHTLOG.md"
    echo "  5. Use nix develop (NÃO nix-shell)"
    echo ""
}

# ═══ STATUS ═══
print_status() {
    echo -e "${YELLOW}═══ STATUS ═══${NC}"
    echo ""
    echo "Git:"
    git log --oneline -5
    echo ""
    echo "Uncommitted:"
    git status --short
    echo ""
    echo "Testes:"
    nix develop --command python3 -m pytest modules/ai/jarvis/tests/test_agent.py modules/ai/jarvis/tests/test_loop_detector.py -q --tb=line 2>/dev/null | tail -3
    echo ""
    echo "Serviços:"
    curl -sf http://127.0.0.1:8080/health >/dev/null 2>&1 && echo "  llama-cpp: UP" || echo "  llama-cpp: DOWN"
    curl -sf http://127.0.0.1:6333/healthz >/dev/null 2>&1 && echo "  qdrant: UP" || echo "  qdrant: DOWN"
    echo ""
    echo "NIGHTLOG:"
    tail -5 NIGHTLOG.md 2>/dev/null || echo "  (not found)"
    echo ""
}

# ═══ SCAN ═══
scan_project() {
    echo -e "${CYAN}═══ SCAN ═══${NC}"
    echo ""

    # 1. Python syntax (via nix develop)
    echo "1. Python syntax check..."
    nix develop --command python3 -c "
import py_compile, os
errors = []
for root, dirs, files in os.walk('modules/ai/jarvis/src/jarvis'):
    for f in files:
        if f.endswith('.py'):
            path = os.path.join(root, f)
            try:
                py_compile.compile(path, doraise=True)
            except py_compile.PyCompileError as e:
                errors.append(str(e))
if errors:
    for e in errors[:5]: print(f'  {e}')
else:
    print('  All files OK')
" 2>/dev/null

    # 2. Import check
    echo "2. Import check..."
    nix develop --command python3 -c "
from jarvis.core.loop_detector import LoopDetector
from jarvis.core.context_budget import ContextBudget
from jarvis.core.agent import Agent
from jarvis.core.devtools import handle_dev_tool
from jarvis.core.vision import handle_capture
print('  All imports OK')
" 2>/dev/null

    # 3. Test check
    echo "3. Tests..."
    nix develop --command python3 -m pytest modules/ai/jarvis/tests/test_agent.py modules/ai/jarvis/tests/test_loop_detector.py -q --tb=line 2>/dev/null | tail -2

    # 4. Nix check
    echo "4. Nix flake check..."
    nix flake check 2>/dev/null | tail -1

    # 5. Dead code
    echo "5. Dead code scan..."
    grep -rn "TODO\|FIXME\|HACK\|XXX" modules/ai/jarvis/src/ --include="*.py" 2>/dev/null | head -5 || echo "  (none found)"

    # 6. Docstrings
    echo "6. Missing docstrings..."
    nix develop --command python3 -c "
import ast, os
missing = []
for root, dirs, files in os.walk('modules/ai/jarvis/src/jarvis'):
    for f in files:
        if f.endswith('.py') and not f.startswith('_'):
            path = os.path.join(root, f)
            try:
                tree = ast.parse(open(path).read())
                for node in ast.walk(tree):
                    if isinstance(node, (ast.FunctionDef, ast.ClassDef)):
                        if not ast.get_docstring(node) and not node.name.startswith('_'):
                            missing.append(f'{path}:{node.lineno} {node.name}')
            except: pass
for m in missing[:5]:
    print(f'  {m}')
if len(missing) > 5:
    print(f'  ... and {len(missing)-5} more')
" 2>/dev/null

    echo ""
}

# ═══ MAIN ═══
case "${1:-context}" in
    context) print_context ;;
    status) print_status ;;
    scan) scan_project ;;
    all)
        print_context
        print_status
        scan_project
        ;;
    *)
        echo "Usage: $0 {context|status|scan|all}"
        exit 1
        ;;
esac
