#!/usr/bin/env bash
# agent-pains.sh — registro automático de "dores" de CLI e lições aprendidas (genérico do monorepo).
#
# USO:
#   ./agent-pains.sh add --kind cli|lesson|tool|env --project <path> \
#                         --sig "<assinatura do erro>" --fix "<como resolver>" [--ctx "<extra>"]
#   ./agent-pains.sh scan [--since-min 60] [--max 300]     # varre o storage do opencode e registra erros de tool
#   ./agent-pains.sh list [--kind K] [--project P] [--limit N]
#   ./agent-pains.sh digest [--days N] [--limit N]          # markdown pronto pro AGENTS.md
#   ./agent-pains.sh render                                  # reescreve o PAINS.md a partir do jsonl
#
# CONTRATO:
#   - Store: $PROJECTS_ROOT/docs/pains/pains.jsonl (fonte) + PAINS.md (render human).
#   - Dedup por (kind + sig normalizada): erro repetido vira contador, não linha nova.
#   - `scan` lê $OPENCODE_STORE/part/*/*.json (state.status == "error") e infere o projeto
#     pelo diretório da sessão; é idempotente (dedup) e pode rodar a cada ciclo do watcher.
#   - Sai != 0 se nenhum erro novo for encontrado no `scan` (o watcher usa isso pra log).
#   - Nada é apagado: pains são append-only e o histórico conta.
set -euo pipefail

PROJECTS_ROOT="${PROJECTS_ROOT:-$HOME/projects}"
OPENCODE_STORE="${OPENCODE_STORE:-$HOME/.local/share/opencode}"
PAINS_DIR="${PAINS_DIR:-$PROJECTS_ROOT/docs/pains}"
JSONL="$PAINS_DIR/pains.jsonl"
MD="$PAINS_DIR/PAINS.md"

cmd="${1:-help}"; shift || true

mkdir -p "$PAINS_DIR"
touch "$JSONL"

norm_sig() {
  # normaliza Paths/números/hex/ids p/ o mesmo erro ter a mesma assinatura
  sed -E \
    -e "s#(/[A-Za-z0-9._~@%+:,=-]+){2,}#<path>#g" \
    -e 's#[0-9a-f]{8,}-[0-9a-f-]{4,}#<uuid>#g' \
    -e 's#[0-9a-f]{16,}#<hash>#g' \
    -e 's#[0-9]{4}-[0-9]{2}-[0-9]{2}[T ][0-9:.+Z-]*#<timestamp>#g' \
    -e 's#[0-9]{4,}\.[0-9]{2,}\.[0-9]+#<version>#g' \
    -e 's#[0-9]+\.[0-9]+#<num>#g' \
    -e 's#[0-9]+#<n>#g' \
    -e 's/[[:space:]]+/ /g' \
    -e 's/^[[:space:]]+//; s/[[:space:]]+$//' | cut -c1-220
}

json_escape() { python3 -c 'import json,sys; print(json.dumps(sys.stdin.read().strip()))'; }

cmd_add() {
  local kind="" project="" sig="" fix="" ctx=""
  while [ $# -gt 0 ]; do
    case "$1" in
      --kind) kind="$2"; shift 2;;
      --project) project="$2"; shift 2;;
      --sig|--signature) sig="$2"; shift 2;;
      --fix) fix="$2"; shift 2;;
      --ctx) ctx="$2"; shift 2;;
      *) echo "flag desconhecida: $1" >&2; exit 2;;
    esac
  done
  [ -n "$kind" ] && [ -n "$sig" ] || { echo "uso: add --kind K --project P --sig S --fix F" >&2; exit 2; }
  local key; key=$(printf '%s|%s' "$kind" "$(printf '%s' "$sig" | norm_sig)")
  local n; n=$(grep -c -F "\"key\": \"$(printf '%s' "$key" | json_escape | tr -d '"')\"" "$JSONL" 2>/dev/null || true)
  [ -n "$n" ] || n=0
  local ts; ts=$(date -Is)
  if [ "$n" -gt 0 ]; then
    python3 - "$JSONL" "$key" "$ts" "$fix" <<'PY'
import json, sys
path, key, ts, fix = sys.argv[1:5]
rows = [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]
for r in rows:
    if r.get('key') == key:
        r['count'] = r.get('count', 1) + 1
        r['last_seen'] = ts
        if fix and fix != '-':
            r['fix'] = fix
with open(path, 'w', encoding='utf-8') as fh:
    for r in rows:
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"pain atualizada (count={next(r['count'] for r in rows if r.get('key')==key)})")
PY
  else
    python3 - "$JSONL" "$key" "$kind" "$project" "$sig" "$fix" "$ctx" "$ts" <<'PY'
import json, sys
path, key, kind, project, sig, fix, ctx, ts = sys.argv[1:9]
row = {"key": key, "kind": kind, "project": project, "sig": sig,
       "fix": fix, "ctx": ctx, "count": 1, "first_seen": ts, "last_seen": ts}
with open(path, 'a', encoding='utf-8') as fh:
    fh.write(json.dumps(row, ensure_ascii=False) + "\n")
print("pain registrada")
PY
  fi
  render
}

cmd_scan() {
  local since_min=60 max=300
  while [ $# -gt 0 ]; do
    case "$1" in
      --since-min) since_min="$2"; shift 2;;
      --max) max="$2"; shift 2;;
      *) shift;;
    esac
  done
  [ -d "$OPENCODE_STORE" ] || { echo "sem store: $OPENCODE_STORE"; exit 1; }
  python3 - "$OPENCODE_STORE" "$since_min" "$max" <<'PY'
import json, os, glob, sys, time, re, sqlite3
store, since_min, maxn = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
cutoff = time.time() - since_min * 60
cutoff_ms = int(cutoff * 1000)
rows = []   # (session_id, tool, error, input)

def norm(sig):
    sig = re.sub(r'(/[A-Za-z0-9._~@%+:,=-]+){2,}', '<path>', sig)
    sig = re.sub(r'[0-9a-f]{8,}-[0-9a-f-]{4,}', '<uuid>', sig)
    sig = re.sub(r'[0-9]{4,}\.[0-9]{2,}\.[0-9]+', '<version>', sig)
    sig = re.sub(r'[0-9]+\.[0-9]+', '<num>', sig)
    sig = re.sub(r'[0-9]+', '<n>', sig)
    return re.sub(r'\s+', ' ', sig).strip()[:240]

# 1) sqlite (store vivo) + 2) sqlite legado + 3) storage em json
for db in (os.path.join(store, 'opencode.db'), os.path.join(store, 'opencode-stable.db')):
    if not os.path.exists(db):
        continue
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        for sid, data in con.execute(
                "select session_id,data from part where time_created>? order by time_created desc",
                (cutoff_ms,)):
            try: j = json.loads(data)
            except Exception: continue
            if j.get('type') != 'tool':
                continue
            st = j.get('state') or {}
            if st.get('status') != 'error':
                continue
            msg = str(st.get('error') or '').strip()
            if not msg:
                continue
            if 'rejected permission' in msg:
                continue
            rows.append((sid, j.get('tool', '?'), msg, st.get('input') or {}))
        con.close()
    except Exception:
        pass

for f in glob.glob(os.path.join(store, 'storage', 'part', '*', '*.json')):
    try:
        if os.path.getmtime(f) < cutoff:
            continue
        d = json.load(open(f))
    except Exception:
        continue
    if d.get('type') != 'tool':
        continue
    st = d.get('state') or {}
    if st.get('status') != 'error':
        continue
    msg = str(st.get('error') or '').strip()
    if msg:
        rows.append(('', d.get('tool', '?'), msg, st.get('input') or {}))

# projeto por sessao
proj = {}
for db in (os.path.join(store, 'opencode.db'), os.path.join(store, 'opencode-stable.db')):
    if not os.path.exists(db):
        continue
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        for sid, directory in con.execute("select id,directory from session"):
            proj[sid] = directory or ''
        con.close()
    except Exception:
        pass
for f in glob.glob(os.path.join(store, 'storage', 'session', '*', '*.json')):
    try:
        d = json.load(open(f))
        proj[d.get('id')] = d.get('directory') or ''
    except Exception:
        pass

out, seen = [], set()
for sid, tool, msg, inp in rows:
    cmd = ''
    if isinstance(inp, dict):
        cmd = inp.get('command') or inp.get('filePath') or inp.get('pattern') or inp.get('path') or ''
    sig = norm(f"[{tool}] {msg}")
    if sig in seen:
        continue
    seen.add(sig)
    out.append({"sig": sig, "tool": tool, "cmd": str(cmd)[:200],
                "project": proj.get(sid, ''), "raw": msg[:300]})
print(json.dumps({'n': len(out), 'items': out[:maxn]}, ensure_ascii=False))
PY
}

cmd_scan_apply() {
  local since_min=60 max=300
  while [ $# -gt 0 ]; do
    case "$1" in
      --since-min) since_min="$2"; shift 2;;
      --max) max="$2"; shift 2;;
      *) shift;;
    esac
  done
  local tmp; tmp=$(mktemp)
  cmd_scan --since-min "$since_min" --max "$max" > "$tmp"
  local n; n=$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["n"])' "$tmp" 2>/dev/null || echo 0)
  if [ "$n" = "0" ]; then echo "0 erros novos"; rm -f "$tmp"; return 1; fi
  python3 - "$tmp" "$JSONL" <<'PY'
import json, sys, time
tmp, jsonl = sys.argv[1], sys.argv[2]
d = json.load(open(tmp))
rows = [json.loads(l) for l in open(jsonl, encoding='utf-8') if l.strip()]
by = {r['key']: r for r in rows}
ts = time.strftime('%Y-%m-%dT%H:%M:%S%z')
novos = 0
for it in d['items']:
    sig = it['sig']
    tool, rest = sig.split('] ', 1)
    key = f"cli|{rest}"
    if key in by:
        by[key]['count'] = by[key].get('count', 1) + 1
        by[key]['last_seen'] = ts
        if it.get('project'):
            by[key]['project'] = it['project']
    else:
        by[key] = {"key": key, "kind": "cli", "project": it.get('project', ''),
                   "sig": rest, "fix": "-", "ctx": f"auto-scan {tool}: {it.get('cmd', '')[:160]}",
                   "count": 1, "first_seen": ts, "last_seen": ts}
        novos += 1
with open(jsonl, 'w', encoding='utf-8') as fh:
    for r in by.values():
        fh.write(json.dumps(r, ensure_ascii=False) + "\n")
print(f"{novos} pains novas, {d['n']} assinaturas vistas")
PY
  rm -f "$tmp"
  cmd_render
}

cmd_list() {
  local kind="" project="" limit=40
  while [ $# -gt 0 ]; do
    case "$1" in
      --kind) kind="$2"; shift 2;;
      --project) project="$2"; shift 2;;
      --limit) limit="$2"; shift 2;;
      *) shift;;
    esac
  done
  python3 - "$JSONL" "$kind" "$project" "$limit" <<'PY'
import json, sys
path, kind, project, limit = sys.argv[1], sys.argv[2], sys.argv[3], int(sys.argv[4])
rows = [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]
if kind: rows = [r for r in rows if r.get('kind') == kind]
if project: rows = [r for r in rows if project in (r.get('project') or '')]
rows.sort(key=lambda r: (r.get('last_seen') or '', r.get('count', 0)), reverse=True)
for r in rows[:limit]:
    print(f"[{r.get('kind')}] x{r.get('count', 1)} {r.get('last_seen', '')[:10]} {r.get('project', '')}")
    print(f"    {r.get('sig', '')[:200]}")
    if r.get('fix') and r['fix'] != '-':
        print(f"    FIX: {r['fix'][:200]}")
PY
}

cmd_digest() {
  local days=7 limit=15
  while [ $# -gt 0 ]; do
    case "$1" in
      --days) days="$2"; shift 2;;
      --limit) limit="$2"; shift 2;;
      *) shift;;
    esac
  done
  python3 - "$JSONL" "$days" "$limit" <<'PY'
import json, sys, time
path, days, limit = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
cut = time.time() - days * 86400
rows = [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]
rows = [r for r in rows if (r.get('last_seen') or '') >= time.strftime('%Y-%m-%d', time.localtime(cut))]
rows.sort(key=lambda r: r.get('count', 0), reverse=True)
print(f"## Pains/erros recorrentes (últimos {days} dias, top {limit})")
print()
print("| tipo | x | desde | erro | correção |")
print("|---|---|---|---|---|")
for r in rows[:limit]:
    sig = (r.get('sig') or '').replace('|', '\\|')[:120]
    fix = (r.get('fix') or '-').replace('|', '\\|')[:120]
    print(f"| {r.get('kind')} | {r.get('count', 1)} | {r.get('first_seen', '')[:10]} | {sig} | {fix} |")
PY
}

cmd_render() {
  python3 - "$JSONL" "$MD" <<'PY'
import json, sys
path, md = sys.argv[1], sys.argv[2]
rows = [json.loads(l) for l in open(path, encoding='utf-8') if l.strip()]
rows.sort(key=lambda r: (r.get('kind', ''), -(r.get('count', 1)), r.get('first_seen', '')))
with open(md, 'w', encoding='utf-8') as fh:
    fh.write("# PAINS — erros de CLI e lições aprendidas (monorepo)\n\n")
    fh.write("> Registro automático. `agent-pains.sh scan` lê os erros de tool do storage do opencode;\n")
    fh.write("> `add` registra lição/erro com a correção. Deduplicado por assinatura normalizada.\n\n")
    for kind in sorted({r.get('kind', 'cli') for r in rows}):
        sub = [r for r in rows if r.get('kind', 'cli') == kind]
        fh.write(f"## {kind} ({len(sub)})\n\n")
        fh.write("| x | desde | projeto | assinatura | correção |\n|---|---|---|---|---|\n")
        for r in sub:
            sig = (r.get('sig') or '').replace('|', '\\|')[:160]
            fix = (r.get('fix') or '-').replace('|', '\\|')[:200]
            proj = (r.get('project') or '').replace('|', '\\|')
            fh.write(f"| {r.get('count', 1)} | {r.get('first_seen', '')[:10]} | {proj} | {sig} | {fix} |\n")
        fh.write("\n")
print(f"render: {md}")
PY
}

case "$cmd" in
  add) cmd_add "$@";;
  scan) cmd_scan "$@";;
  scan-apply) cmd_scan_apply "$@";;
  list) cmd_list "$@";;
  digest) cmd_digest "$@";;
  render) cmd_render;;
  help|"") sed -n '2,20p' "$0";;
  *) echo "comando desconhecido: $cmd" >&2; exit 2;;
esac
