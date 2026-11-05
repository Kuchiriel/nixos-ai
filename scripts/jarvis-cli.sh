#!/usr/bin/env bash
# jarvis-cli.sh — CLI wrapper for all JARVIS MCP tools
#
# Usage:
#   jarvis-cli.sh <tool> [args...]
#
# Tools:
#   read <file> [offset] [limit]     — Read file with optional line range
#   write <file> <content>           — Write content to file
#   replace <file> <old> <new>       — Surgical string replacement
#   shell <command>                  — Execute shell command (read-only safe)
#   screen                           — Capture screenshot
#   observe                          — Screenshot + vision AI analysis
#   nix-eval <expr>                  — Evaluate Nix expression
#   nix-check                        — Run nix flake check
#   nix-search <query>               — Search NixOS packages
#   chatgpt <url>                    — Read shared ChatGPT conversation
#   remember <fact>                  — Store episodic memory
#   recall <query>                   — Recall memories
#   lessons <query>                  — Recall lessons from past errors
#   vault-list                       — List vault notes
#   vault-write <title> <content>    — Write to vault
#   rag-search <query>               — Semantic code search
#   rag-index <dir>                  — Index directory for RAG
#   hackmd-list                      — List HackMD notes
#   hackmd-read <id>                 — Read HackMD note
#   hackmd-write <title> <content>   — Write HackMD note
#   tools                            — List every MCP tool + CLI coverage gap
#   tool <name> <json>               — Call any MCP tool by name (JSON args)
#   bench-stt <wav> [wav...]         — ASR_BENCH: measure STT (VAD on/off, RTF)
#   status                           — Show JARVIS status
#   help                             — Show this help

set -euo pipefail

# Env COMPARTILHADO com o MCP (mesmo PYTHONPATH + keys): sem isso a CLI
# perdia `requests`, o provider de LLM abria o breaker e rag-index pendurava.
# shellcheck source=/dev/null
. /home/nixos/projects/nixos-ai/modules/ai/jarvis/jarvis-env.sh
PY="$JARVIS_PY"

usage() {
    head -30 "$0" | grep "^#" | sed 's/^# *//'
    exit 0
}

case "${1:-help}" in
    read)
        FILE="${2:?Usage: jarvis-cli.sh read <file> [offset] [limit]}"
        OFFSET="${3:-0}"
        LIMIT="${4:-2000}"
        "$PY" -c "
from jarvis.core.devtools import handle_dev_tool
import json
result = handle_dev_tool('read_file', {'path': '$FILE', 'offset': $OFFSET, 'limit': $LIMIT})
print(json.dumps(json.loads(result) if isinstance(result, str) else result, indent=2, ensure_ascii=False))
"
        ;;
    write)
        FILE="${2:?Usage: jarvis-cli.sh write <file> <content>}"
        CONTENT="${3:?Usage: jarvis-cli.sh write <file> <content>}"
        "$PY" -c "
from jarvis.core.devtools import handle_dev_tool
import json
result = handle_dev_tool('write_file', {'path': '$FILE', 'content': '''$CONTENT'''})
print(json.dumps(json.loads(result) if isinstance(result, str) else result, indent=2, ensure_ascii=False))
"
        ;;
    replace)
        FILE="${2:?Usage: jarvis-cli.sh replace <file> <old> <new>}"
        OLD="${3:?Usage: jarvis-cli.sh replace <file> <old> <new>}"
        NEW="${4:?Usage: jarvis-cli.sh replace <file> <old> <new>}"
        "$PY" -c "
from jarvis.core.devtools import handle_dev_tool
import json
result = handle_dev_tool('str_replace', {'path': '$FILE', 'old': '''$OLD''', 'new': '''$NEW'''})
print(json.dumps(json.loads(result) if isinstance(result, str) else result, indent=2, ensure_ascii=False))
"
        ;;
    shell)
        CMD="${2:?Usage: jarvis-cli.sh shell <command>}"
        "$PY" -c "
from jarvis.core.devtools import handle_dev_tool
import json
result = handle_dev_tool('execute_shell', {'cmd': '''$CMD'''})
print(json.dumps(json.loads(result) if isinstance(result, str) else result, indent=2, ensure_ascii=False))
"
        ;;
    screen)
        "$PY" -c "
from jarvis.mcp_server import call_tool
result = call_tool('jarvis_capture_screen', {})
print(result)
"
        ;;
    observe)
        "$PY" -c "
from jarvis.mcp_server import call_tool
result = call_tool('jarvis_observe_screen', {})
print(result)
"
        ;;
    nix-eval)
        EXPR="${2:?Usage: jarvis-cli.sh nix-eval <expression>}"
        "$PY" -c "
from jarvis.mcp_server import _handle_nix_eval
import json
result = _handle_nix_eval({'expression': '''$EXPR'''})
print(result)
"
        ;;
    nix-check)
        "$PY" -c "
from jarvis.mcp_server import _handle_nix_check
result = _handle_nix_check({})
print(result)
"
        ;;
    nix-search)
        QUERY="${2:?Usage: jarvis-cli.sh nix-search <query>}"
        "$PY" -c "
from jarvis.mcp_server import _handle_nix_search
result = _handle_nix_search({'query': '''$QUERY'''})
print(result)
"
        ;;
    chatgpt)
        URL="${2:?Usage: jarvis-cli.sh chatgpt <url>}"
        "$PY" -c "
from jarvis.mcp_server import call_tool
import json
result = call_tool('jarvis_read_chatgpt', {'url': '''$URL'''})
print(result)
"
        ;;
    remember)
        FACT="${2:?Usage: jarvis-cli.sh remember <fact>}"
        "$PY" -c "
from jarvis.mcp_server import _handle_remember
result = _handle_remember({'text': '''$FACT'''})
print(result)
"
        ;;
    recall)
        QUERY="${2:?Usage: jarvis-cli.sh recall <query>}"
        "$PY" -c "
from jarvis.mcp_server import _handle_recall
result = _handle_recall({'query': '''$QUERY'''})
print(result)
"
        ;;
    lessons)
        QUERY="${2:?Usage: jarvis-cli.sh lessons <query>}"
        "$PY" -c "
from jarvis.mcp_server import _handle_lessons
result = _handle_lessons({'query': '''$QUERY'''})
print(result)
"
        ;;
    state)
        "$PY" -c "
from jarvis.mcp_server import _rehydrate_state
print(_rehydrate_state())
"
        ;;
    vault-list)
        "$PY" -c "
from jarvis.mcp_server import _handle_vault_list
result = _handle_vault_list({})
print(result)
"
        ;;
    vault-write)
        TITLE="${2:?Usage: jarvis-cli.sh vault-write <title> <content>}"
        CONTENT="${3:?Usage: jarvis-cli.sh vault-write <title> <content>}"
        "$PY" -c "
from jarvis.mcp_server import _handle_vault_write
result = _handle_vault_write({'name': '''$TITLE''', 'content': '''$CONTENT'''})
print(result)
"
        ;;
    rag-search)
        QUERY="${2:?Usage: jarvis-cli.sh rag-search <query> [collection] [limit]}"
        COLL="${3:-code}"
        LIMIT="${4:-5}"
        "$PY" -c "
from jarvis.mcp_server import _handle_rag_search
result = _handle_rag_search({'query': '''$QUERY''', 'collection': '''$COLL''', 'limit': int('$LIMIT')})
print(result)
"
        ;;
    rag-index)
        DIR="${2:?Usage: jarvis-cli.sh rag-index <directory>}"
        "$PY" -c "
from jarvis.mcp_server import _handle_rag_index
result = _handle_rag_index({'path': '''$DIR'''})
print(result)
"
        ;;
    hackmd-list)
        "$PY" -c "
from jarvis.mcp_server import call_tool
result = call_tool('jarvis_hackmd_list', {})
print(result)
"
        ;;
    hackmd-read)
        ID="${2:?Usage: jarvis-cli.sh hackmd-read <note_id>}"
        "$PY" -c "
from jarvis.mcp_server import call_tool
result = call_tool('jarvis_hackmd_read', {'note_id': '''$ID'''})
print(result)
"
        ;;
    hackmd-write)
        TITLE="${2:?Usage: jarvis-cli.sh hackmd-write <title> <content>}"
        CONTENT="${3:?Usage: jarvis-cli.sh hackmd-write <title> <content>}"
        "$PY" -c "
from jarvis.mcp_server import call_tool
result = call_tool('jarvis_hackmd_write', {'title': '''$TITLE''', 'content': '''$CONTENT'''})
print(result)
"
        ;;
    hackmd-sync)
        FILE="${2:?Usage: jarvis-cli.sh hackmd-sync <file> [title]}"
        TITLE="${3:-$(basename "$FILE" .md)}"
        CONTENT=$(cat "$FILE")
        "$PY" -c "
from jarvis.mcp_server import call_tool
result = call_tool('jarvis_hackmd_write', {'title': '''$TITLE''', 'content': '''$CONTENT'''})
print(result)
"
        ;;
    status)
        echo "=== JARVIS Status ==="
        # (03/11) Portas lidas do REGISTRY (fonte única: models.nix) — não
        # literais: o default (4B-MTP+LoRA) e o router (bonsai) são
        # grupos diferentes, mostrados separados para não mentir.
        . "$(dirname "$0")/jarvis-registry.sh"
        _reg_default_model="$(reg_default 2>/dev/null || echo jarvis-mtp-lora)"
        _reg_default_port="$(reg_port "$_reg_default_model" 2>/dev/null || echo 8092)"
        _reg_router_port="$(reg_port bonsai 2>/dev/null || echo 8080)"
        _reg_embed_port="$(reg_service_port embeddings 2>/dev/null || echo 8081)"
        _reg_rerank_port="$(reg_service_port rerank 2>/dev/null || echo 8082)"
        echo "LLM (default :$_reg_default_port): $(curl -sf http://127.0.0.1:$_reg_default_port/health 2>/dev/null || echo 'offline')"
        echo "Router (:$_reg_router_port, on-demand): $(curl -sf http://127.0.0.1:$_reg_router_port/health 2>/dev/null || echo 'offline')"
        echo "Embeddings: $(curl -sf http://127.0.0.1:$_reg_embed_port/health 2>/dev/null || echo 'offline')"
        echo "Rerank: $(curl -sf http://127.0.0.1:$_reg_rerank_port/health 2>/dev/null || echo 'offline')"
        echo "Qdrant: $(curl -sf http://127.0.0.1:6333/healthz 2>/dev/null || echo 'offline')"
        echo "Wakeword: $(systemctl --user is-active jarvis-wakeword 2>/dev/null || echo 'inactive')"
        echo "Waybar: $(pgrep -c waybar 2>/dev/null || echo '0') processes"
        echo "Status: $(cat /tmp/jarvis-status.json 2>/dev/null || echo '{}')"
        ;;
    health|diagnose)
        "$PY" -c "
from jarvis.core.watchdog import watchdog_cycle
result = watchdog_cycle()
import json
print(json.dumps(result, indent=2))
"
        ;;
    system-health)
        "$PY" -c "
from jarvis.core.watchdog import watchdog_cycle
import json
print(json.dumps(watchdog_cycle(), indent=2))
"
        ;;
    classify)
        PATH_ARG="${2:.}"
        "$PY" -c "
from jarvis.core.classify import get_security_summary, format_security_summary
summary = get_security_summary('$PATH_ARG')
print(format_security_summary(summary))
"
        ;;
    classify-file)
        FILE_ARG="${2:?Usage: jarvis-cli.sh classify-file <file>}"
        "$PY" -c "
from jarvis.core.classify import classify_file
import json
result = classify_file('$FILE_ARG')
print(json.dumps(result.to_dict(), indent=2))
"
        ;;
    watchdog)
        "$PY" -c "
from jarvis.core.watchdog import watchdog_cycle
import json
result = watchdog_cycle()
print(json.dumps(result, indent=2))
"
        ;;
    watchdog-loop)
        "$PY" -c "
from jarvis.core.watchdog import run_watchdog_loop
interval = int('${2:-60}')
run_watchdog_loop(interval=interval)
"
        ;;
    vault-status)
        "$PY" -c "
from jarvis.mcp_server import _vault_status
import json
result = _vault_status()
print(json.dumps(result, indent=2))
"
        ;;
    vault-sync-obsidian)
        "$PY" -c "
from jarvis.mcp_server import _vault_sync_to_obsidian
import json
result = _vault_sync_to_obsidian()
print(json.dumps({'synced': len(result), 'files': result}, indent=2))
"
        ;;
    vault-sync-hackmd)
        "$PY" -c "
from jarvis.mcp_server import _vault_sync_to_hackmd
import json
result = _vault_sync_to_hackmd()
print(json.dumps({'synced': len(result), 'results': result}, indent=2))
"
        ;;
    vault-search-obsidian)
        QUERY="${2:?Usage: jarvis-cli.sh vault-search-obsidian <query>}"
        "$PY" -c "
from jarvis.mcp_server import _vault_read_from_obsidian
import json
result = _vault_read_from_obsidian('''$QUERY''')
print(json.dumps(result, indent=2))
"
        ;;
    workspace)
        shift
        "$PY" -c "
import sys; sys.argv = ['jarvis', 'workspace'] + sys.argv[1:]
from jarvis.cli.main import main; main()
" "$@"
        ;;
    persona)
        shift
        "$PY" -c "
import sys; sys.argv = ['jarvis', 'persona'] + sys.argv[1:]
from jarvis.cli.main import main; main()
" "$@"
        ;;
    workitem)
        shift
        "$PY" -c "
import sys; sys.argv = ['jarvis', 'workitem'] + sys.argv[1:]
from jarvis.cli.main import main; main()
" "$@"
        ;;
    orchestrate)
        shift
        "$PY" -c "
import sys; sys.argv = ['jarvis', 'orchestrate'] + sys.argv[1:]
from jarvis.cli.main import main; main()
" "$@"
        ;;
    stats)
        shift
        "$PY" -c "
import sys; sys.argv = ['jarvis', 'stats'] + sys.argv[1:]
from jarvis.cli.main import main; main()
" "$@"
        ;;
    evidence)
        shift
        "$PY" -c "
import sys; sys.argv = ['jarvis', 'evidence'] + sys.argv[1:]
from jarvis.cli.main import main; main()
" "$@"
        ;;
    tools)
        # 03/11: cobertura CLI x MCP. O MCP expoe ~37 tools; a CLI so tinha
        # ~20 atalhos. Esta lista mostra o que falta ("tool" cobre tudo).
        "$PY" -c "
import re
from jarvis.mcp_server import JARVIS_TOOLS
native = set()
for line in open('$0'):
    m = re.match(r'^    ([a-z0-9][a-z0-9-]*)\)$', line)
    if m:
        native.add(m.group(1))
aliases = {
    'read_file': 'read', 'write_file': 'write', 'str_replace': 'replace',
    'execute': 'shell', 'nix_eval': 'nix-eval', 'nix_check': 'nix-check',
    'nix_search': 'nix-search', 'read_chatgpt': 'chatgpt',
    'read_ai_conversation': 'chatgpt', 'rag_search': 'rag-search',
    'rag_index': 'rag-index', 'vault_list': 'vault-list',
    'vault_write': 'vault-write', 'vault_search_obsidian': 'vault-search',
    'hackmd_list': 'hackmd-list', 'hackmd_read': 'hackmd-read',
    'hackmd_write': 'hackmd-write', 'observe_screen': 'observe',
    'capture_screen': 'screen', 'make_scenarios': 'make-scenarios',
    'web_search': 'web-search',
}
covered, missing = [], []
for t in JARVIS_TOOLS:
    n = t['name']
    cli = aliases.get(n, n)
    (covered if cli in native else missing).append(n)
print('MCP tools: %d | CLI native: %d | so via tool: %d' % (len(JARVIS_TOOLS), len(covered), len(missing)))
print('--- CLI native ---')
print(' '.join(sorted(covered)))
print('--- only via tool ---')
print(' '.join(sorted(missing)))
"
        ;;
    rehydrate)
        # 03/11: o rehydrate era o tool mais usado do MCP (68 chamadas/7d) e
        # nao tinha atalho na CLI. Mapeia 1:1 na tool do MCP.
        ARGS="${2:-}"
        "$PY" -c "
import json, sys
from jarvis.mcp_server import call_tool
raw = sys.argv[1].strip() if len(sys.argv) > 1 else ''
args = json.loads(raw) if raw else {}
print(call_tool('rehydrate', args))
" "$ARGS"
        ;;
    web-search)
        QUERY="${2:?Usage: jarvis-cli.sh web-search <query> [limit]}"
        LIMIT="${3:-5}"
        "$PY" -c "
import json, sys
from jarvis.mcp_server import call_tool
print(call_tool('web_search', {'query': sys.argv[1], 'limit': int(sys.argv[2])}))
" "$QUERY" "$LIMIT"
        ;;
    tool)
        NAME="${2:?Usage: jarvis-cli.sh tool <name> <json-args>}"
        ARGS="${3:-}"
        "$PY" -c "
import json, sys
from jarvis.mcp_server import call_tool
raw = sys.argv[1].strip() if len(sys.argv) > 1 else ''
args = json.loads(raw) if raw else {}
print(call_tool(sys.argv[2], args))
" "$ARGS" "$NAME"
        ;;
    bench-stt)
        shift
        "$PY" -m jarvis.core.asr_bench "$@"
        ;;
    help|*)
        usage
        ;;
esac
