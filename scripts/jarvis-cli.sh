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
#   read-ai <url>                    — Read shared ChatGPT/Gemini/Claude conversation
#   remember <fact>                  — Store episodic memory
#   recall <query>                   — Recall memories
#   lessons <query>                  — Recall lessons from past errors
#   rehydrate [--json] [json]        — Rehydrate session context (guards, queue, handoff, memories, lessons, RAG, sessions, roster)
#   session-resume [--json] [json|key val|id|dir] — Resume prior opencode session (session_id/directory/query; ergonomic args supported)
#   vault-list                       — List vault notes
#   vault-write <title> <content>    — Write to vault
#   rag-search <query>               — Semantic code search
#   rag-index <dir>                  — Index directory for RAG
#   hackmd-list                      — List HackMD notes
#   hackmd-read <id>                 — Read HackMD note
#   hackmd-write <title> <content>   — Write HackMD note
#   tools [--json]                   — List every MCP tool + CLI native/coverage (JSON for machine use)
#   tools-search <query> [--json]    — Meta-tool discovery by intent (embedding-ranked, low-token)
#   tools-call <name> [json]         — Call any tool via meta-tool router
#   tool [--json] <name> [json]      — Call any MCP tool directly by name (JSON-wrapped output in --json mode)
#   time                             — Current local time (ISO/date/time/tz)
#   bench-stt <wav> [wav...]         — ASR_BENCH: measure STT (VAD on/off, RTF)
#   status                           — Show JARVIS status
#   help                             — Show this help

set -euo pipefail

# Env COMPARTILHADO com o MCP (mesmo PYTHONPATH + keys): sem isso a CLI
# perdia `requests`, o provider de LLM abria o breaker e rag-index pendurava.
# (06/11) Caminho derivado do próprio script: o literal anterior quebrava
# qualquer checkout/worktree fora de /home/nixos/projects/nixos-ai.
SCRIPT_DIR="$(cd "$(dirname "$(realpath "$0")")" && pwd)"
# shellcheck source=/dev/null
. "$SCRIPT_DIR/../modules/ai/jarvis/jarvis-env.sh"
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
        "$PY" - "$FILE" "$OFFSET" "$LIMIT" <<'PY'
import json
import sys
from jarvis.core.devtools import handle_dev_tool
result = handle_dev_tool(
    "read_file",
    {"path": sys.argv[1], "offset": int(sys.argv[2]), "limit": int(sys.argv[3])},
)
print(json.dumps(json.loads(result) if isinstance(result, str) else result,
                 indent=2, ensure_ascii=False))
PY
        ;;
    write)
        FILE="${2:?Usage: jarvis-cli.sh write <file> <content>}"
        CONTENT="${3:?Usage: jarvis-cli.sh write <file> <content>}"
        "$PY" - "$FILE" "$CONTENT" <<'PY'
import json
import sys
from jarvis.core.devtools import handle_dev_tool
result = handle_dev_tool("write_file", {"path": sys.argv[1], "content": sys.argv[2]})
print(json.dumps(json.loads(result) if isinstance(result, str) else result,
                 indent=2, ensure_ascii=False))
PY
        ;;
    replace)
        FILE="${2:?Usage: jarvis-cli.sh replace <file> <old> <new>}"
        OLD="${3:?Usage: jarvis-cli.sh replace <file> <old> <new>}"
        NEW="${4:?Usage: jarvis-cli.sh replace <file> <old> <new>}"
        "$PY" - "$FILE" "$OLD" "$NEW" <<'PY'
import json
import sys
from jarvis.core.devtools import handle_dev_tool
result = handle_dev_tool(
    "str_replace",
    {"path": sys.argv[1], "old": sys.argv[2], "new": sys.argv[3]},
)
print(json.dumps(json.loads(result) if isinstance(result, str) else result,
                 indent=2, ensure_ascii=False))
PY
        ;;
    shell)
        CMD="${2:?Usage: jarvis-cli.sh shell <command>}"
        "$PY" - "$CMD" <<'PY'
import json
import sys
from jarvis.core.devtools import handle_dev_tool
result = handle_dev_tool("execute_shell", {"cmd": sys.argv[1]})
print(json.dumps(json.loads(result) if isinstance(result, str) else result,
                 indent=2, ensure_ascii=False))
PY
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
        # (06/11) `nix eval --json '<expr>'` tratava a expressão como PATH
        # ("getting status of .../1+1"). O handler MCP agora usa --expr +
        # argv; a CLI delega para ele (uma fonte, sem escape de shell).
        "$PY" - "$EXPR" <<'PY'
import sys
from jarvis.mcp_server import call_tool
print(call_tool("nix_eval", {"expr": sys.argv[1]}))
PY
        ;;
    nix-check)
        "$PY" -c "
from jarvis.mcp_server import call_tool
print(call_tool('nix_check', {}))
"
        ;;
    nix-search)
        QUERY="${2:?Usage: jarvis-cli.sh nix-search <query>}"
        "$PY" - "$QUERY" <<'PY'
import sys
from jarvis.mcp_server import _handle_nix_search
print(_handle_nix_search({"query": sys.argv[1]}))
PY
        ;;
    chatgpt)
        URL="${2:?Usage: jarvis-cli.sh chatgpt <url>}"
        "$PY" - "$URL" <<'PY'
import sys
from jarvis.mcp_server import call_tool
print(call_tool("jarvis_read_chatgpt", {"url": sys.argv[1]}))
PY
        ;;
    read-ai)
        URL="${2:?Usage: jarvis-cli.sh read-ai <url>}"
        "$PY" - "$URL" <<'PY'
import sys
from jarvis.mcp_server import call_tool
print(call_tool("jarvis_read_ai_conversation", {"url": sys.argv[1]}))
PY
        ;;
    remember)
        FACT="${2:?Usage: jarvis-cli.sh remember <fact>}"
        "$PY" - "$FACT" <<'PY'
import sys
from jarvis.mcp_server import _handle_remember
print(_handle_remember({"text": sys.argv[1]}))
PY
        ;;
    recall)
        QUERY="${2:?Usage: jarvis-cli.sh recall <query>}"
        "$PY" - "$QUERY" <<'PY'
import sys
from jarvis.mcp_server import _handle_recall
print(_handle_recall({"query": sys.argv[1]}))
PY
        ;;
    lessons)
        QUERY="${2:?Usage: jarvis-cli.sh lessons <query>}"
        "$PY" - "$QUERY" <<'PY'
import sys
from jarvis.mcp_server import _handle_lessons
print(_handle_lessons({"query": sys.argv[1]}))
PY
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
        "$PY" - "$TITLE" "$CONTENT" <<'PY'
import sys
from jarvis.mcp_server import _handle_vault_write
print(_handle_vault_write({"name": sys.argv[1], "content": sys.argv[2]}))
PY
        ;;
    rag-search)
        QUERY="${2:?Usage: jarvis-cli.sh rag-search <query> [collection] [limit]}"
        COLL="${3:-code}"
        LIMIT="${4:-5}"
        "$PY" - "$QUERY" "$COLL" "$LIMIT" <<'PY'
import sys
from jarvis.mcp_server import _handle_rag_search
print(_handle_rag_search({
    "query": sys.argv[1],
    "collection": sys.argv[2],
    "limit": int(sys.argv[3]),
}))
PY
        ;;
    rag-index)
        DIR="${2:?Usage: jarvis-cli.sh rag-index <directory>}"
        "$PY" - "$DIR" <<'PY'
import sys
from jarvis.mcp_server import _handle_rag_index
print(_handle_rag_index({"path": sys.argv[1]}))
PY
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
        "$PY" - "$ID" <<'PY'
import sys
from jarvis.mcp_server import call_tool
print(call_tool("jarvis_hackmd_read", {"note_id": sys.argv[1]}))
PY
        ;;
    hackmd-write)
        TITLE="${2:?Usage: jarvis-cli.sh hackmd-write <title> <content>}"
        CONTENT="${3:?Usage: jarvis-cli.sh hackmd-write <title> <content>}"
        "$PY" - "$TITLE" "$CONTENT" <<'PY'
import sys
from jarvis.mcp_server import call_tool
print(call_tool("jarvis_hackmd_write",
                {"title": sys.argv[1], "content": sys.argv[2]}))
PY
        ;;
    hackmd-sync)
        FILE="${2:?Usage: jarvis-cli.sh hackmd-sync <file> [title]}"
        TITLE="${3:-$(basename "$FILE" .md)}"
        "$PY" - "$FILE" "$TITLE" <<'PY'
import sys
from jarvis.mcp_server import call_tool
print(call_tool("jarvis_hackmd_sync",
                {"path": sys.argv[1], "title": sys.argv[2]}))
PY
        ;;
    status)
        echo "=== JARVIS Status ==="
        # (03/11) Portas lidas do REGISTRY (fonte única: models.nix) — não
        # literais: o default (4B-MTP+LoRA) e o router (bonsai) são
        # grupos diferentes, mostrados separados para não mentir.
        . "$SCRIPT_DIR/jarvis-registry.sh"
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
        _wake="$(systemctl --user is-active jarvis-wakeword 2>/dev/null || true)"
        echo "Wakeword: ${_wake:-inactive}"
        echo "Waybar: $(pgrep -c waybar 2>/dev/null || echo '0') processes"
        echo "Status: $(cat /tmp/jarvis-status.json 2>/dev/null || echo '{}')"
        # Session continuity pipeline (index + consolidation) — freshness for rehydrate/session_resume.
        "$PY" - <<'PY'
import json, os, time
def load(p):
    try:
        with open(p, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None
now = int(time.time())
idx_s = os.path.expanduser('~/.local/state/jarvis/sessions-index-state.json')
con_s = os.path.expanduser('~/.local/state/jarvis/sessions-consolidation-state.json')
idx = load(idx_s) or {}
con = load(con_s) or {}
def age_from_mtime(path):
    try:
        return max(0, now - int(os.path.getmtime(path)))
    except Exception:
        return None
def fmt_age(sec):
    if sec is None: return 'n/a'
    if sec < 120: return f'{sec}s'
    if sec < 7200: return f'{sec//60}m'
    return f'{sec//3600}h'
con_map = con.get('sessions') if isinstance(con.get('sessions'), dict) else (con.get('stored') if isinstance(con.get('stored'), dict) else {})
con_count = len(con_map) if isinstance(con_map, dict) else (con.get('count', 'n/a'))
con_last = con.get('last_time_updated')
if con_last in (None, '', 'n/a') and isinstance(con_map, dict) and con_map:
    try:
        con_last = max(v for v in con_map.values() if isinstance(v, (int, float)))
    except Exception:
        con_last = 'n/a'
print('Sessions index: last_time_updated=%s state_age=%s last_run_indexed=%s errors=%s' % (
    idx.get('last_time_updated', 'n/a'), fmt_age(age_from_mtime(idx_s)),
    idx.get('last_run_indexed', 'n/a'), idx.get('last_run_errors', 'n/a')))
print('Sessions consolidation: last_time_updated=%s state_age=%s sessions=%s' % (
    con_last if con_last is not None else 'n/a', fmt_age(age_from_mtime(con_s)), con_count))
PY
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
        PATH_ARG="${2:-.}"
        "$PY" - "$PATH_ARG" <<'PY'
import sys
from jarvis.core.classify import get_security_summary, format_security_summary
summary = get_security_summary(sys.argv[1])
print(format_security_summary(summary))
PY
        ;;
    classify-file)
        FILE_ARG="${2:?Usage: jarvis-cli.sh classify-file <file>}"
        "$PY" - "$FILE_ARG" <<'PY'
import json
import sys
from jarvis.core.classify import classify_file
result = classify_file(sys.argv[1])
print(json.dumps(result.to_dict(), indent=2))
PY
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
        "$PY" - "${2:-60}" <<'PY'
import sys
from jarvis.core.watchdog import run_watchdog_loop
run_watchdog_loop(interval=int(sys.argv[1]))
PY
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
        "$PY" - "$QUERY" <<'PY'
import json
import sys
from jarvis.mcp_server import _vault_read_from_obsidian
print(json.dumps(_vault_read_from_obsidian(sys.argv[1]), indent=2))
PY
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
        # 03/11: cobertura CLI x MCP. O MCP expoe 46 tools; a CLI so tinha
        # ~24 atalhos. Esta lista mostra o que falta ("tool" cobre tudo).
        # (06/11) o path entra por argv: nomes com apóstrofo quebravam o -c.
        AS_JSON="${2:-}"
        "$PY" - "$0" "$AS_JSON" <<'PY'
import json
import re
import sys
from jarvis.mcp_server import JARVIS_TOOLS
as_json = (len(sys.argv) > 2 and sys.argv[2] == '--json')
native = set()
for line in open(sys.argv[1]):
    m = re.match(r'^    ([a-z0-9_|-]+)\)\s*$', line)
    if m:
        for alt in m.group(1).split('|'):
            native.add(alt.replace('_', '-'))
aliases = {
    'read_file': 'read', 'write_file': 'write', 'str_replace': 'replace',
    'execute': 'shell', 'nix_eval': 'nix-eval', 'nix_check': 'nix-check',
    'nix_search': 'nix-search', 'read_chatgpt': 'chatgpt',
    'read_ai_conversation': 'read-ai', 'rag_search': 'rag-search',
    'rag_index': 'rag-index', 'vault_list': 'vault-list',
    'vault_write': 'vault-write', 'vault_status': 'vault-status',
    'vault_search_obsidian': 'vault-search-obsidian',
    'vault_sync_obsidian': 'vault-sync-obsidian',
    'vault_sync_hackmd': 'vault-sync-hackmd',
    'hackmd_list': 'hackmd-list', 'hackmd_read': 'hackmd-read',
    'hackmd_write': 'hackmd-write', 'hackmd_sync': 'hackmd-sync',
    'observe_screen': 'observe',
    'capture_screen': 'screen', 'make_scenarios': 'make-scenarios',
    'web_search': 'web-search',
    'session_resume': 'session-resume',
    'tools_search': 'tools-search', 'tools_call': 'tools-call',
}
covered, missing = [], []
for t in JARVIS_TOOLS:
    n = t['name']
    cli = aliases.get(n, n)
    (covered if cli in native else missing).append(n)
if as_json:
    print(json.dumps({
        'mcp_tools': len(JARVIS_TOOLS),
        'cli_native': sorted(covered),
        'only_via_tool': sorted(missing),
        'counts': {'cli_native': len(covered), 'only_via_tool': len(missing)},
    }, ensure_ascii=False))
else:
    print('MCP tools: %d | CLI native: %d | so via tool: %d' % (len(JARVIS_TOOLS), len(covered), len(missing)))
    print('--- CLI native ---')
    print(' '.join(sorted(covered)))
    print('--- only via tool ---')
    print(' '.join(sorted(missing)))
PY
        ;;
    rehydrate)
        # 03/11: o rehydrate era o tool mais usado do MCP (68 chamadas/7d) e
        # nao tinha atalho na CLI. Mapeia 1:1 na tool do MCP.
        A1="${2:-}"
        A2="${3:-}"
        "$PY" - "$A1" "$A2" <<'PY'
import json, sys
from jarvis.mcp_server import call_tool
a1 = (sys.argv[1] if len(sys.argv) > 1 else '').strip()
a2 = (sys.argv[2] if len(sys.argv) > 2 else '').strip()
as_json = (a1 == '--json' or a2 == '--json')
raw = a2 if a1 == '--json' else a1
if raw == '--json':
    raw = ''
args = json.loads(raw) if raw else {}
out = call_tool('rehydrate', args)
if as_json:
    print(json.dumps({'tool': 'rehydrate', 'text': out}, ensure_ascii=False))
else:
    print(out)
PY
        ;;
    session-resume|session_resume)
        A1="${2:-}"
        A2="${3:-}"
        A3="${4:-}"
        A4="${5:-}"
        "$PY" - "$A1" "$A2" "$A3" "$A4" <<'PY'
import json, sys
from jarvis.mcp_server import call_tool
vals = [(sys.argv[i] if len(sys.argv) > i else '').strip() for i in range(1, 5)]
as_json = '--json' in vals
vals = [v for v in vals if v != '--json']
a1 = vals[0] if len(vals) > 0 else ''
a2 = vals[1] if len(vals) > 1 else ''
a3 = vals[2] if len(vals) > 2 else ''
args = {}
if a1.startswith('{'):
    try:
        args = json.loads(a1) if a1 else {}
    except Exception:
        args = {}
elif a1 in ('session_id', 'directory', 'query', 'limit'):
    if a1 == 'limit':
        try:
            args['limit'] = int(a2) if a2 else 5
        except Exception:
            args['limit'] = 5
    elif a2:
        args[a1] = a2
elif a1:
    # bare value: treat as directory if path-like, else session_id
    if '/' in a1 or a1.startswith('.'):
        args['directory'] = a1
    else:
        args['session_id'] = a1
# support: session-resume directory <path> <limit>
if a1 == 'directory' and a3.isdigit():
    args['limit'] = int(a3)
out = call_tool('session_resume', args)
if as_json:
    print(json.dumps({'tool': 'session_resume', 'args': args, 'text': out}, ensure_ascii=False))
else:
    print(out)
PY
        ;;
    tools-search|tools_search)
        QUERY="${2:-}"
        AS_JSON="${3:-}"
        "$PY" - "$QUERY" "$AS_JSON" <<'PY'
import json, sys
q = sys.argv[1] if len(sys.argv) > 1 else ''
as_json = (len(sys.argv) > 2 and sys.argv[2] == '--json') or q == '--json'
if q == '--json':
    q = ''
if as_json:
    try:
        from jarvis.mcp_server import _meta_search_results
        r = _meta_search_results(q, 8)
        print(json.dumps(r, ensure_ascii=False))
    except Exception as e:
        try:
            from jarvis.mcp_server import call_tool
            text = call_tool('tools_search', {'query': q})
        except Exception as e2:
            text = f'ERROR: {e2}'
        print(json.dumps({'query': q, 'mode': 'fallback', 'text': text, 'error': str(e)}, ensure_ascii=False))
else:
    from jarvis.mcp_server import call_tool
    print(call_tool('tools_search', {'query': q}))
PY
        ;;
    tools-call|tools_call)
        NAME="${2:?Usage: jarvis-cli.sh tools-call <name> <json-args>}"
        ARGS="${3:-}"
        "$PY" - "$NAME" "$ARGS" <<'PY'
import json, sys
from jarvis.mcp_server import call_tool
raw = (sys.argv[2] if len(sys.argv) > 2 else '').strip()
args = json.loads(raw) if raw else {}
print(call_tool('tools_call', {'name': sys.argv[1], 'args': args}))
PY
        ;;
    time)
        "$PY" -c '
import datetime, json
now = datetime.datetime.now().astimezone()
print(json.dumps({"iso": now.isoformat(timespec="seconds"), "date": now.strftime("%Y-%m-%d"), "time": now.strftime("%H:%M:%S"), "tz": str(now.tzinfo)}, ensure_ascii=False))
'
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
        P2="${2:-}"
        P3="${3:-}"
        P4="${4:-}"
        "$PY" - "$P2" "$P3" "$P4" <<'PY'
import json, sys
from jarvis.mcp_server import call_tool
vals = [(sys.argv[i] if len(sys.argv) > i else '').strip() for i in range(1, 4)]
as_json = '--json' in vals
vals = [v for v in vals if v != '--json']
name = vals[0] if len(vals) > 0 else ''
raw = vals[1] if len(vals) > 1 else ''
if not name:
    raise SystemExit('Usage: jarvis-cli.sh tool [--json] <name> <json-args>')
if raw:
    try:
        args = json.loads(raw)
    except Exception:
        if name == 'tools_search':
            args = {'query': raw}
        else:
            raise SystemExit(f'erro: args de {name} devem ser JSON: {raw[:120]}')
else:
    args = {}
if as_json and name == 'tools_search':
    from jarvis.mcp_server import _meta_search_results
    q = (args.get('query', '') if isinstance(args, dict) else '') or ''
    print(json.dumps(_meta_search_results(q, 8), ensure_ascii=False))
else:
    out = call_tool(name, args)
    if as_json:
        try:
            parsed = json.loads(out) if isinstance(out, str) else out
            print(json.dumps({'tool': name, 'ok': True, 'result': parsed}, ensure_ascii=False))
        except Exception:
            print(json.dumps({'tool': name, 'ok': True, 'text': out}, ensure_ascii=False))
    else:
        print(out)
PY
        ;;
    bench-stt)
        shift
        "$PY" -m jarvis.core.asr_bench "$@"
        ;;
    # (06/11) PASSTHROUGH para o CLI do JARVIS: speak, stt, benchmark,
    # doctor, voice, emotion, agent, ask, run, dev, watchdog, heal,
    # self-test, metrics, triggers, screenshot, hwdetect, hwprofile,
    # index, rag, migrate, parity, intent, profile, services, state,
    # commands, list. O wrapper vira a FRENTE ÚNICA: tools do MCP +
    # subcomandos do CLI, sempre pelo mesmo env (jarvis-env.sh).
    # É o que o meta-tool da voz usa (ação `jarvis`).
    speak|stt|benchmark|doctor|voice|emotion|agent|ask|run|dev|watchdog|heal|self-test|metrics|triggers|screenshot|hwdetect|hwprofile|index|rag|migrate|parity|intent|profile|services|state|commands|list|control|create|forget|handoff|pause|resume|regression|notify|telegram|consolidate|nightwatch|idle|keygen|launcher|summarize|worker|eval-rag|reset-state)
        _cmd="$1"   # (12/11) o shift consumia o subcomando: o main nunca recebia
        shift        # ("invalid choice") — repassa o comando antes dos args
        "$PY" -m jarvis.cli.main "$_cmd" "$@"
        ;;
    help|*)
        usage
        ;;
esac
