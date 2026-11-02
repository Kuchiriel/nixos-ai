#!/usr/bin/env bash
# agent-msg.sh — O CANAL BOT-A-BOT, agora com ROTEAMENTO e ENTREGA por API.
#
# ENTREGA (02/11, pesquisa + leitura do fonte do opencode v1.18.34):
# A API do opencode entrega a mensagem NA SESSÃO do alvo — sem roubar o
# foco, sem digitar na caixa de input, sem travar o humano:
#   POST /session/:id/message       {parts:[...], noReply?:bool}
#     - noReply=true  → cria a mensagem de usuário e PARA (sem rodar o
#       modelo). É a NOTIFICAÇÃO pura: entra no histórico, zero token.
#     - noReply=false → roda o agente (PEDIDO).
#   POST /session/:id/prompt_async  → mesmo, mas não espera a resposta (204).
#   POST /session/:id/abort         → cancela o turno em andamento.
# FALLBACK: se a API não estiver acessível (ou o alvo não tiver sessão
# conhecida), o pedido ainda sai pelo transporte antigo (focus + wtype +
# Return). A NOTA nunca cai no fallback: estacionar texto na caixa do
# humano bloqueia o typing e a mensagem não entra na fila → inútil.
#
# SEMÂNTICA (o que a pesquisa de mercado/papers mudou):
# - A2A (v1.0, LF/AAIF): roteamento DETERMINÍSTICO (sem LLM no meio) +
#   Agent Card (descoberta) + message/send (pedido) vs push-notification
#   (aviso) + messageId (idempotência) + tasks/cancel.
# - Anthropic (multi-agent, 06/2025): sem fronteira explícita os agentes
#   DUPLICAM trabalho e multi-agente custa ~15x tokens → broadcast é caro.
# - CHI'26 (arXiv 2602.17864): aviso sem filtro QUEBRA o fluxo e aumenta a
#   carga → wake/aviso só para quem é dono do assunto.
#
# MODOS:
#   --to <alvo>      entrega ao alvo: other (default) | all | <nome-do-roster>
#   --note           NOTIFICAÇÃO: a mensagem entra na sessão do alvo, o
#                    agente NÃO roda (noReply=true). Zero token.
#   --ask            PEDIDO: o agente roda (prompt_async).
#   --broadcast      alias explícito de --to all (fan-out explícito, raro)
#   --cancel <id>    aborta o turno do alvo (POST /session/:id/abort)
#   --reply-to <id>  referencia uma mensagem anterior
#   --id <id>        id da mensagem (idempotência A2A); default m-<ts>-<pid>
#   --force          ignora o guard de lane/arquivos sobrepostos
#   --list           dry-run: mostra roster + alvos
#   --pending        lista pedidos sem resposta (do log)
#
# ROSTER: ~/projects/.agents/roster.json (fonte única de "quem existe, em
# que lane e qual sessão"). Sem claim, ninguém é endereçado — o default
# NÃO faz broadcast (2 janelas, 1 assunto).
#
# USO:
#   agent-roster.py claim --name mt5 --lane "mt5/opt" --repo mt5 --files "mql/**"
#   agent-msg.sh --to mt5 "commit 9f2a1c: v3.12 sem DD; vê se roda no teu tree"
#   agent-msg.sh --note "INFO: laya-ft agora é o classificador (sem ação)"
#   agent-msg.sh --cancel m-1793639000-1
#
# LOG (auditoria pós-compact): ~/projects/AGENTS-MSG.log
set -eu
PATH="$HOME/.nix-profile/bin:/run/current-system/sw/bin:$PATH"
HERE="$(dirname "$(realpath "$0")")"
ROSTER="$HERE/agent-roster.py"
LOG="$HOME/projects/AGENTS-MSG.log"
mkdir -p "$(dirname "$LOG")" /tmp/opencode

# ── config do servidor opencode (API) ─────────────────────────────────
OC_URL="${AGENTS_OC_URL:-http://100.121.100.103:4599}"
OC_ENVFILE="${AGENTS_OC_ENVFILE:-$HOME/.config/opencode/server.env}"
OC_USER="${OPENCODE_SERVER_USERNAME:-opencode}"
OC_PASS="${OPENCODE_SERVER_PASSWORD:-}"
if [ -z "$OC_PASS" ] && [ -r "$OC_ENVFILE" ]; then
    OC_PASS=$(sed -n 's/^OPENCODE_SERVER_PASSWORD=//p' "$OC_ENVFILE" | head -1)
    OC_PASS="${OC_PASS%\"}"; OC_PASS="${OC_PASS#\"}"
fi

MODO="other"; NOTA=0; CANCEL_ID=""; REPLY_TO=""; FORCE=0
LISTAR=0; MSG_ID=""; TEXTO=""
while [ $# -gt 0 ]; do
    case "$1" in
        --to)      MODO="${2:?--to precisa de other|all|<nome>|nsncd|plain}"; shift 2 ;;
        --to=*)    MODO="${1#--to=}"; shift ;;
        --ask)     shift ;;
        --ask=*)   MODO="${1#--ask=}"; shift ;;
        --note)    NOTA=1; shift ;;
        --note=*)  MODO="${1#--note=}"; NOTA=1; shift ;;
        --broadcast) MODO="all"; shift ;;
        --cancel)  CANCEL_ID="${2:?--cancel precisa do id da mensagem}"; shift 2 ;;
        --cancel=*) CANCEL_ID="${1#--cancel=}"; shift ;;
        --reply-to) REPLY_TO="${2:?--reply-to precisa do id}"; shift 2 ;;
        --reply-to=*) REPLY_TO="${1#--reply-to=}"; shift ;;
        --id)      MSG_ID="${2:?--id precisa do id}"; shift 2 ;;
        --id=*)    MSG_ID="${1#--id=}"; shift ;;
        --force)   FORCE=1; shift ;;
        --list)    LISTAR=1; shift ;;
        -h|--help) sed -n '2,60p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) break ;;
    esac
done
TEXTO="$*"

# ── pending: pedidos sem resposta ─────────────────────────────────────
if [ "$MODO" = "pending" ]; then
    [ -f "$LOG" ] || { echo "sem log"; exit 0; }
    awk -F' \\| ' '
        $3=="ask" {per[$5]=1; ordem[++n]=$5; dono[$5]=$4; txt[$5]=$6}
        $6 ~ /re=/ {split($6,a,"re="); gsub(/ .*/,"",a[2]); resposta[a[2]]=1}
        END {for (i=1;i<=n;i++) if (per[ordem[i]] && !resposta[ordem[i]])
              print ordem[i]" -> "dono[ordem[i]]" | "txt[ordem[i]]}' "$LOG" | tail -20
    exit 0
fi

# ── cancel: aborta o turno do alvo (POST /session/:id/abort) ──────────
# O alvo vem do LOG (a mensagem que originou o pedido), não do roster.
if [ -n "$CANCEL_ID" ]; then
    LINHA=$(grep -F "| id=$CANCEL_ID |" "$LOG" 2>/dev/null | tail -1)
    [ -n "$LINHA" ] || { echo "agent-msg: id '$CANCEL_ID' não está no log" >&2; exit 1; }
    ALVO_NOME=$(echo "$LINHA" | cut -d'|' -f4 | sed 's/(.*//;s/ //g')
    ALVO_END=$(echo "$LINHA" | cut -d'|' -f4 | sed 's/.*(\(0x[0-9a-f]*\)).*/\1/')
    SESSAO_CANC=$(python3 - "$ROSTER" "$ALVO_NOME" "$ALVO_END" <<'PYEOF'
import json, subprocess, sys
roster_py, nome, end = sys.argv[1:4]
def run(*args):
    try:
        out = subprocess.run([sys.executable, roster_py, *args],
                             capture_output=True, text=True, timeout=20).stdout
        return json.loads(out or "{}")
    except Exception:
        return {}
sess = ""
for a in run("list", "--json").get("agents", []):
    if a.get("name") == nome or a.get("window") == end:
        sess = a.get("session") or ""
        break
if not sess:
    for w in run("windows", "--json").get("all", []):
        if w.get("address") == end:
            sess = w.get("session") or ""
            break
print(sess)
PYEOF
)
    [ -n "$SESSAO_CANC" ] || { echo "agent-msg: não achei a sessão do alvo '$ALVO_NOME' ($ALVO_END)" >&2; exit 1; }
    R=$(python3 - "$OC_URL" "$OC_USER" "$OC_PASS" "$SESSAO_CANC" "/abort" '{}' <<'PYEOF'
import base64, sys, urllib.request
base, user, pw, sid, path, body = sys.argv[1:7]
req = urllib.request.Request(
    f"{base}/session/{sid}{path}", data=body.encode(), method="POST",
    headers={"Content-Type": "application/json",
             "Authorization": "Basic " +
             base64.b64encode(f"{user}:{pw}".encode()).decode()})
try:
    with urllib.request.urlopen(req, timeout=25) as r:
        print(r.status, r.read()[:120].decode(errors="replace"))
except Exception as e:
    print("ERRO", e)
PYEOF
)
    printf '%s | %s | cancel | %s(%s) | id=%s | re=- | abort via API: %s\n' \
        "$(date '+%d/%m %H:%M')" "${JARVIS_AGENT_NAME:-agent-$$}" "$ALVO_NOME" \
        "$ALVO_END" "$CANCEL_ID" "$R" >> "$LOG"
    echo "agent-msg: turno abortado em $ALVO_NOME ($SESSAO_CANC) — $R"
    exit 0
fi

# ── resolve alvos ─────────────────────────────────────────────────────
ALVOS_JSON=$(mktemp /tmp/opencode/agent-msg.XXXXXX.json)
trap 'rm -f "$ALVOS_JSON"' EXIT
RC=0
python3 - "$ROSTER" "$MODO" "$LISTAR" "$FORCE" "$NOTA" > "$ALVOS_JSON" <<'PYEOF' || RC=$?
import json, subprocess, sys
roster_py, modo, listar, force, nota = sys.argv[1:6]
force = force == "1"

def run(*args):
    try:
        out = subprocess.run([sys.executable, roster_py, *args],
                             capture_output=True, text=True, timeout=20).stdout
        return json.loads(out or "{}")
    except Exception:
        return {}

win = run("windows", "--json")
roster = run("list", "--json")
agents = roster.get("agents", [])
own = win.get("own") or {}
others = win.get("others", [])
meta = {w.get("address"): w for w in win.get("all", [])}

def by_name(name):
    for a in agents:
        if a.get("name") == name:
            return a
    return None

def files_of(a):
    return [f for f in (a.get("files") or []) if f]

def overlap(a, b):
    sa, sb = set(files_of(a)), set(files_of(b))
    hits = set()
    for x in sa:
        for y in sb:
            if x == y or x.startswith(y + "/") or y.startswith(x + "/"):
                hits.add(x)
            elif "**" in x and y.startswith(x.split("**")[0]):
                hits.add(y)
            elif "**" in y and x.startswith(y.split("**")[0]):
                hits.add(x)
    return sorted(hits)

def alvo(a, kind="agent"):
    end = a.get("window") or a.get("address", "")
    w = meta.get(end, {})
    return {"kind": kind, "address": end,
            "name": a.get("name", ""), "lane": a.get("lane", ""),
            "repo": a.get("repo", ""), "note": a.get("note", ""),
            "session": a.get("session") or w.get("session", ""),
            "busy": bool(a.get("busy", w.get("busy", False))),
            "pid": a.get("pid", w.get("pid", 0))}

me = None
for a in agents:
    if own and a.get("window") == own.get("address"):
        me = a
        break

targets, avisos = [], []
if modo == "all":
    for w in others:
        targets.append(alvo(w, "window"))
elif modo == "other":
    for a in agents:
        if a.get("state") != "live":
            continue
        if me and a.get("name") == me.get("name"):
            continue
        if me and not force:
            hit = overlap(me, a)
            if hit:
                avisos.append(
                    f"pulado '{a.get('name')}': lane/arquivos sobrepostos "
                    f"({', '.join(hit)}) — risco de trabalho duplicado "
                    f"(Anthropic: fronteiras explícitas); use --force")
                continue
        targets.append(alvo(a))
    if not targets:
        avisos.append(
            "sem roster (ou ninguém fora da minha lane): NADA foi enviado. "
            "Faça claim (agent-roster.py claim --name <n> --lane <lane>) "
            "ou use --broadcast explicitamente.")
elif modo in ("nsncd", "plain"):
    for w in others:
        t = w.get("title") or ""
        if (modo == "nsncd") == ("nsncd" in t):
            targets.append(alvo(w, "window"))
            break
else:
    a = by_name(modo)
    if a is None:
        print(json.dumps({"erro": f"nome desconhecido no roster: {modo}",
                          "targets": [], "avisos": []}))
        sys.exit(1)
    if a.get("state") != "live":
        print(json.dumps({"erro": f"'{modo}' não está vivo (janela fechada?)",
                          "targets": [], "avisos": []}))
        sys.exit(1)
    if me and not force:
        hit = overlap(me, a)
        if hit:
            print(json.dumps({"erro":
                              f"lane/arquivos sobrepostos com '{modo}' "
                              f"({', '.join(hit)}) — envie como --note ou use "
                              f"--force", "targets": [], "avisos": []}))
            sys.exit(1)
    targets.append(alvo(a))

print(json.dumps({"targets": targets, "avisos": avisos, "me": me or {}},
                 ensure_ascii=False))
PYEOF
if [ "$RC" -ne 0 ]; then
    python3 -c "
import json, sys
try:
    d=json.load(open('$ALVOS_JSON'))
except Exception:
    d={}
print('agent-msg: '+d.get('erro','falha ao resolver alvos'), file=sys.stderr)
"
    exit 1
fi

ALVOS=()
while IFS= read -r addr; do [ -n "$addr" ] && ALVOS+=("$addr"); done < <(
    python3 -c "
import json
d=json.load(open('$ALVOS_JSON'))
print('\n'.join(t['address'] for t in d['targets']))"
)

# ── list (dry-run) + avisos ───────────────────────────────────────────
python3 -c "
import json, sys
d=json.load(open('$ALVOS_JSON'))
for a in d['avisos']: print('agent-msg: '+a, file=sys.stderr)
me=d.get('me') or {}
if '$LISTAR' == '1':
    print('eu:', me.get('name','(sem claim)'), '| lane:', me.get('lane','-'))
    for t in d['targets']:
        print(f\"  alvo: {t['name'] or '(janela)'} lane={t['lane'] or '-'} \"
              f\"addr={t['address']} sessao={t['session'] or '-'} \"
              f\"ocupado={'sim' if t['busy'] else 'nao'}\")
"
if [ "$LISTAR" -eq 1 ]; then exit 0; fi
[ "${#ALVOS[@]}" -gt 0 ] || { echo "agent-msg: nenhum alvo (modo=$MODO)" >&2; exit 3; }
[ -n "$TEXTO" ] || { echo 'uso: agent-msg.sh [--to <alvo>] [--note|--ask] "texto"' >&2; exit 1; }

# ── envelope + idempotência ───────────────────────────────────────────
REMETENTE="${JARVIS_AGENT_NAME:-$(python3 -c "
import json
d=json.load(open('$ALVOS_JSON'))
print((d.get('me') or {}).get('name') or 'agent-$$')")}"
[ "$MSG_ID" = "" ] && MSG_ID="m-$(date +%s)-$$"
if [ -f "$LOG" ] && grep -qF "| id=$MSG_ID |" "$LOG" && [ "$FORCE" -eq 0 ]; then
    echo "agent-msg: id '$MSG_ID' já existe no log (idempotência A2A) — use outro --id" >&2
    exit 5
fi
TEXTO_ESCAPED=$(printf '%s' "$TEXTO" | tr '\n' ' ')
CABECALHO="[AGENT→AGENT] from $REMETENTE id $MSG_ID"
[ -n "$REPLY_TO" ] && CABECALHO="$CABECALHO re:$REPLY_TO"
[ "$NOTA" -eq 1 ] && CABECALHO="$CABECALHO note"
TEXTO_FINAL="$CABECALHO: $TEXTO_ESCAPED"

# ── entrega via API do opencode ───────────────────────────────────────
# $1=sessão  $2=path ("/message" | "/prompt_async" | "/abort")  $3=json
oc_post() {
    python3 - "$OC_URL" "$OC_USER" "$OC_PASS" "$1" "$2" "$3" <<'PYEOF'
import base64, json, sys, urllib.error, urllib.request
base, user, pw, sid, path, body = sys.argv[1:7]
url = f"{base}/session/{sid}{path}"
req = urllib.request.Request(
    url, data=body.encode(), method="POST",
    headers={"Content-Type": "application/json",
             "Authorization": "Basic " +
             base64.b64encode(f"{user}:{pw}".encode()).decode()})
try:
    with urllib.request.urlopen(req, timeout=25) as r:
        sys.stdout.write(f"{r.status} {r.read()[:160].decode(errors='replace')}")
except urllib.error.HTTPError as e:
    sys.stdout.write(f"HTTP {e.code} {e.read()[:200].decode(errors='replace')}")
    sys.exit(1)
except Exception as e:
    sys.stdout.write(f"ERRO {e}")
    sys.exit(1)
PYEOF
}

MINHA=$(hyprctl activewindow -j 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('address',''))" 2>/dev/null || true)
TIPO="ask"; [ "$NOTA" -eq 1 ] && TIPO="note"
[ "$MODO" = "all" ] && TIPO="broadcast"
FALHOU=0

for END in "${ALVOS[@]}"; do
    INFO=$(python3 -c "
import json
d=json.load(open('$ALVOS_JSON'))
for t in d['targets']:
    if t['address']=='$END':
        print(t.get('name') or '(janela)', '|', t.get('session') or '', '|',
              '1' if t.get('busy') else '0')
")
    NOME_ALVO=$(echo "$INFO" | cut -d'|' -f1 | tr -d ' ')
    SESSAO=$(echo "$INFO" | cut -d'|' -f2 | tr -d ' ')
    OCUPADO=$(echo "$INFO" | cut -d'|' -f3 | tr -d ' ')

    # CANCEL é tratado antes (resolve o alvo pelo log)
    if [ -n "$SESSAO" ]; then
        if [ "$NOTA" -eq 1 ]; then
            # NOTA: mensagem entra na sessão, o agente NÃO roda (noReply=true)
            BODY=$(python3 -c '
import json, sys
print(json.dumps({"parts": [{"type": "text", "text": sys.argv[1]}],
                  "noReply": True}))' "$TEXTO_FINAL")
            R=$(oc_post "$SESSAO" "/message" "$BODY" || true)
            echo "agent-msg: nota entregue em $NOME_ALVO ($SESSAO) — sem rodar o agente: $R"
        else
            # PEDIDO: o agente roda (async = não espera a resposta)
            BODY=$(python3 -c '
import json, sys
print(json.dumps({"parts": [{"type": "text", "text": sys.argv[1]}]}))' "$TEXTO_FINAL")
            R=$(oc_post "$SESSAO" "/prompt_async" "$BODY" || true)
            echo "agent-msg: pedido enviado a $NOME_ALVO ($SESSAO) — agente vai rodar: $R"
        fi
        printf '%s | %s | %s | %s(%s) | id=%s | re=%s | %s\n' \
            "$(date '+%d/%m %H:%M')" "$REMETENTE" "$TIPO" "$NOME_ALVO" "$END" \
            "$MSG_ID" "${REPLY_TO:--}" "$TEXTO_ESCAPED" >> "$LOG"
        continue
    fi

    # sem sessão conhecida (API não serve) → fallback NO TRANSPORTE VELHO
    if [ "$NOTA" -eq 1 ]; then
        echo "agent-msg: alvo '$NOME_ALVO' sem sessão (API indisponível) — nota NÃO pode ser entregue sem API (estacionar texto na caixa trava o humano). Use --to (pedido)." >&2
        FALHOU=1
        continue
    fi
    hyprctl dispatch focuswindow "address:$END"
    sleep 1
    ATUAL=$(hyprctl activewindow -j 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('address',''))" 2>/dev/null || true)
    if [ "$ATUAL" != "$END" ]; then
        echo "agent-msg: FOCO NAO PEGOU (alvo=$END atual=$ATUAL) — nada digitado" >&2
        FALHOU=1
        continue
    fi
    wtype "$TEXTO_FINAL"
    sleep 0.4
    wtype -k Return
    echo "enviado p/ $END ($NOME_ALVO) [fallback focus+wtype]"
    printf '%s | %s | %s | %s(%s) | id=%s | re=%s | %s\n' \
        "$(date '+%d/%m %H:%M')" "$REMETENTE" "$TIPO" "$NOME_ALVO" "$END" \
        "$MSG_ID" "${REPLY_TO:--}" "$TEXTO_ESCAPED" >> "$LOG"
done

[ -n "$MINHA" ] && hyprctl dispatch focuswindow "address:$MINHA" >/dev/null 2>&1 || true
[ "$FALHOU" -eq 0 ] || exit 6
