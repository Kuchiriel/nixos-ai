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
#   status                           — Show JARVIS status
#   help                             — Show this help

set -euo pipefail

JARVIS_SRC="${JARVIS_SRC:-$(dirname "$(realpath "$0")")/../modules/ai/jarvis/src}"
export PYTHONPATH="$JARVIS_SRC:${PYTHONPATH:-}"

usage() {
    head -30 "$0" | grep "^#" | sed 's/^# *//'
    exit 0
}

case "${1:-help}" in
    read)
        FILE="${2:?Usage: jarvis-cli.sh read <file> [offset] [limit]}"
        OFFSET="${3:-0}"
        LIMIT="${4:-2000}"
        python3 -c "
from jarvis.core.devtools import handle_dev_tool
import json
result = handle_dev_tool('read_file', {'path': '$FILE', 'offset': $OFFSET, 'limit': $LIMIT})
print(json.dumps(json.loads(result) if isinstance(result, str) else result, indent=2, ensure_ascii=False))
"
        ;;
    write)
        FILE="${2:?Usage: jarvis-cli.sh write <file> <content>}"
        CONTENT="${3:?Usage: jarvis-cli.sh write <file> <content>}"
        python3 -c "
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
        python3 -c "
from jarvis.core.devtools import handle_dev_tool
import json
result = handle_dev_tool('str_replace', {'path': '$FILE', 'old': '''$OLD''', 'new': '''$NEW'''})
print(json.dumps(json.loads(result) if isinstance(result, str) else result, indent=2, ensure_ascii=False))
"
        ;;
    shell)
        CMD="${2:?Usage: jarvis-cli.sh shell <command>}"
        python3 -c "
from jarvis.core.devtools import handle_dev_tool
import json
result = handle_dev_tool('execute_shell', {'cmd': '''$CMD'''})
print(json.dumps(json.loads(result) if isinstance(result, str) else result, indent=2, ensure_ascii=False))
"
        ;;
    screen)
        python3 -c "
from jarvis.mcp_server import call_tool
result = call_tool('jarvis_capture_screen', {})
print(result)
"
        ;;
    observe)
        python3 -c "
from jarvis.mcp_server import call_tool
result = call_tool('jarvis_observe_screen', {})
print(result)
"
        ;;
    nix-eval)
        EXPR="${2:?Usage: jarvis-cli.sh nix-eval <expression>}"
        python3 -c "
from jarvis.mcp_server import _handle_nix_eval
import json
result = _handle_nix_eval({'expression': '''$EXPR'''})
print(result)
"
        ;;
    nix-check)
        python3 -c "
from jarvis.mcp_server import _handle_nix_check
result = _handle_nix_check({})
print(result)
"
        ;;
    nix-search)
        QUERY="${2:?Usage: jarvis-cli.sh nix-search <query>}"
        python3 -c "
from jarvis.mcp_server import _handle_nix_search
result = _handle_nix_search({'query': '''$QUERY'''})
print(result)
"
        ;;
    chatgpt)
        URL="${2:?Usage: jarvis-cli.sh chatgpt <url>}"
        python3 -c "
from jarvis.mcp_server import call_tool
import json
result = call_tool('jarvis_read_chatgpt', {'url': '''$URL'''})
print(result)
"
        ;;
    remember)
        FACT="${2:?Usage: jarvis-cli.sh remember <fact>}"
        python3 -c "
from jarvis.mcp_server import _handle_remember
result = _handle_remember({'text': '''$FACT'''})
print(result)
"
        ;;
    recall)
        QUERY="${2:?Usage: jarvis-cli.sh recall <query>}"
        python3 -c "
from jarvis.mcp_server import _handle_recall
result = _handle_recall({'query': '''$QUERY'''})
print(result)
"
        ;;
    lessons)
        QUERY="${2:?Usage: jarvis-cli.sh lessons <query>}"
        python3 -c "
from jarvis.mcp_server import _handle_lessons
result = _handle_lessons({'query': '''$QUERY'''})
print(result)
"
        ;;
    vault-list)
        python3 -c "
from jarvis.mcp_server import _handle_vault_list
result = _handle_vault_list({})
print(result)
"
        ;;
    vault-write)
        TITLE="${2:?Usage: jarvis-cli.sh vault-write <title> <content>}"
        CONTENT="${3:?Usage: jarvis-cli.sh vault-write <title> <content>}"
        python3 -c "
from jarvis.mcp_server import _handle_vault_write
result = _handle_vault_write({'title': '''$TITLE''', 'content': '''$CONTENT'''})
print(result)
"
        ;;
    rag-search)
        QUERY="${2:?Usage: jarvis-cli.sh rag-search <query>}"
        python3 -c "
from jarvis.mcp_server import _handle_rag_search
result = _handle_rag_search({'query': '''$QUERY'''})
print(result)
"
        ;;
    rag-index)
        DIR="${2:?Usage: jarvis-cli.sh rag-index <directory>}"
        python3 -c "
from jarvis.mcp_server import _handle_rag_index
result = _handle_rag_index({'directory': '''$DIR'''})
print(result)
"
        ;;
    hackmd-list)
        python3 -c "
from jarvis.mcp_server import call_tool
result = call_tool('jarvis_hackmd_list', {})
print(result)
"
        ;;
    hackmd-read)
        ID="${2:?Usage: jarvis-cli.sh hackmd-read <note_id>}"
        python3 -c "
from jarvis.mcp_server import call_tool
result = call_tool('jarvis_hackmd_read', {'note_id': '''$ID'''})
print(result)
"
        ;;
    hackmd-write)
        TITLE="${2:?Usage: jarvis-cli.sh hackmd-write <title> <content>}"
        CONTENT="${3:?Usage: jarvis-cli.sh hackmd-write <title> <content>}"
        python3 -c "
from jarvis.mcp_server import call_tool
result = call_tool('jarvis_hackmd_write', {'title': '''$TITLE''', 'content': '''$CONTENT'''})
print(result)
"
        ;;
    hackmd-sync)
        FILE="${2:?Usage: jarvis-cli.sh hackmd-sync <file> [title]}"
        TITLE="${3:-$(basename "$FILE" .md)}"
        CONTENT=$(cat "$FILE")
        python3 -c "
from jarvis.mcp_server import call_tool
result = call_tool('jarvis_hackmd_write', {'title': '''$TITLE''', 'content': '''$CONTENT'''})
print(result)
"
        ;;
    status)
        echo "=== JARVIS Status ==="
        echo "LLM: $(curl -sf http://127.0.0.1:8080/health 2>/dev/null || echo 'offline')"
        echo "Embeddings: $(curl -sf http://127.0.0.1:8081/health 2>/dev/null || echo 'offline')"
        echo "Rerank: $(curl -sf http://127.0.0.1:8082/health 2>/dev/null || echo 'offline')"
        echo "Qdrant: $(curl -sf http://127.0.0.1:6333/healthz 2>/dev/null || echo 'offline')"
        echo "Wakeword: $(systemctl --user is-active jarvis-wakeword 2>/dev/null || echo 'inactive')"
        echo "Waybar: $(pgrep -c waybar 2>/dev/null || echo '0') processes"
        echo "Status: $(cat /tmp/jarvis-status.json 2>/dev/null || echo '{}')"
        ;;
    vault-status)
        python3 -c "
from jarvis.mcp_server import _vault_status
import json
result = _vault_status()
print(json.dumps(result, indent=2))
"
        ;;
    vault-sync-obsidian)
        python3 -c "
from jarvis.mcp_server import _vault_sync_to_obsidian
import json
result = _vault_sync_to_obsidian()
print(json.dumps({'synced': len(result), 'files': result}, indent=2))
"
        ;;
    vault-sync-hackmd)
        python3 -c "
from jarvis.mcp_server import _vault_sync_to_hackmd
import json
result = _vault_sync_to_hackmd()
print(json.dumps({'synced': len(result), 'results': result}, indent=2))
"
        ;;
    vault-search-obsidian)
        QUERY="${2:?Usage: jarvis-cli.sh vault-search-obsidian <query>}"
        python3 -c "
from jarvis.mcp_server import _vault_read_from_obsidian
import json
result = _vault_read_from_obsidian('''$QUERY''')
print(json.dumps(result, indent=2))
"
        ;;
    help|*)
        usage
        ;;
esac
