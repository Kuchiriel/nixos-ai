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
#                    | <lane>  (14/11: agente em outra maquina — vai pelo BUS,
#                    cross-machine; sem focus/wtype)
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
# (26/11, medido) O caminho pode ser apontado por AGENTS_MSG_LOG para o
# teste isolar o log (o default continua sendo o log da casa).
set -eu
PATH="$HOME/.nix-profile/bin:/run/current-system/sw/bin:$PATH"
HERE="$(dirname "$(realpath "$0")")"
ROSTER="$HERE/agent-roster.py"
LOG="${AGENTS_MSG_LOG:-$HOME/projects/AGENTS-MSG.log}"
mkdir -p "$(dirname "$LOG")" /tmp/opencode

# ── COMUNICACAO VISIVEL (19/11, pedido do dono) ───────────────────────
# Toda mensagem entre agentes tambem entra na fila vis-enqueue: o plugin
# memory.js injeta via ctx.session.synthetic() na sessao declarada em
# ~/.local/state/jarvis/vis-session quando ela fica ociosa. Assim o dono ve a
# conversa da frota NA JANELA DELE, sem abrir o hub nem o bus. O orcamento
# (VIS_MAX_PER_HOUR, default 12/h com gap de 3 min) ja limita o volume:
# isto e' uma amostra legivel, o arquivo inteiro continua no LOG e no bus.
# Sem script novo: reusa o vis-enqueue que ja existe.
#
# (24/11, medido) A FILA VIROU UM LOG E ATRASOU O DONO. Medido: 88 itens, dos
# quais 80 eram mensagens de agente e 73 dessas eram AVISO/NOTA (nao pediam
# acao nenhuma); a fila esvazia UM item por idle, entao os 8 pedidos de
# acao reais estavam atras de 73 avisos. Agora so entra na fila visivel o
# que PEDE ACAO (o tipo `ask`): aviso e nota ficam no LOG e no bus (onde ja
# estavam), e nao viram um /goal na sessao do dono. O digest/filha real
# volta a ser o que o dono ve primeiro.
vis_visible() {
    local rem="$1" tipo="$2" alvo="$3" texto="$4" sessao_alvo="$5"
    # so pedido de acao vira tarefa visivel; aviso/nota e' informacao, e o
    # dono le isso no bus e no hub.
    [ "$tipo" = "ask" ] || return 0
    command -v "$HOME/bin/vis-enqueue" >/dev/null 2>&1 || return 0
    local alvo_vis=""
    alvo_vis=$(cat "$HOME/.local/state/jarvis/vis-session" 2>/dev/null)
    # se a mensagem ja foi entregue na sessao do dono, nao duplica (a copia ja'
    # visivel la; enfileirar so' geraria um /goal repetindo o texto).
    if [ -n "$alvo_vis" ] && [ "$alvo_vis" = "$sessao_alvo" ]; then return 0; fi
    "$HOME/bin/vis-enqueue" enqueue "[AGENT] $rem : $alvo ($tipo) : $texto" \
        >/dev/null 2>&1 || true
}

# ── config do servidor opencode (API) ─────────────────────────────────
# Lê da configuração centralizada (scripts/agent-config.json) com fallback
# para a variável de ambiente AGENTS_OC_URL.
OC_URL="${AGENTS_OC_URL:-$(python3 -c "
import json, sys
try:
    cfg = json.loads(open('/home/nixos/projects/nixos-ai/scripts/agent-config.json').read())
    print(cfg.get('ambiente', {}).get('AGENTS_OC_URL', os.environ.get('AGENTS_OC_URL','http://127.0.0.1:4599')))
except Exception:
    print(os.environ.get('AGENTS_OC_URL','http://127.0.0.1:4599'), file=sys.stderr)
    sys.exit(1)
" 2>/dev/null || echo "http://100.121.100.103:4599")}"
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
        # (08/11) --pending como FLAG: o AGENTS.md documenta a flag, mas o
        # parser nao a tinha → "--pending" caia no texto e era ENTREGUE como
        # mensagem (ruído no bus, medido: spiritvale-pivot mandou "--pending"
        # para três alvos). Agora a flag lista os pedidos sem resposta.
        --pending) MODO="pending"; shift ;;
        --pending=*) MODO="pending"; shift ;;
        -h|--help) sed -n '2,60p' "$0" | sed 's/^# \{0,1\}//'; exit 0 ;;
        *) break ;;
    esac
done
TEXTO="$*"

# ── pending: pedidos sem resposta ─────────────────────────────────────
if [ "$MODO" = "pending" ]; then
    [ -f "$LOG" ] || { echo "sem log"; exit 0; }
    # (26/11, medido) A CHAVE do pedido e do resposta nao batia: o pedido e
    # gravado como `$5 = id=m-1795...` e a resposta traz `$6 = re=m-1795...`.
    # O awk tirava o prefixo "re=" e guardava `m-1795...`, enquanto o pedido
    # ficava sob `id=m-1795...` => NENHUMA resposta fechava um pedido e a
    # fila de pendentes crescia para sempre (medido: 104 asks, todos ainda
    # "pendentes" mesmo com a resposta entregue). Agora as duas pontas usam a
    # MESMA chave (o id sem prefixo) e o texto do pedido e lido de $7 (antes
    # era $6, que era o campo `re=`).
    awk -F' \\| ' '
        $3=="ask" {split($5,a,"id="); per[a[2]]=1; ordem[++n]=a[2]; dono[a[2]]=$4; txt[a[2]]=$7}
        $6 ~ /re=/ && $6 !~ /re=-/ {split($6,a,"re="); gsub(/ .*/,"",a[2]); resposta[a[2]]=1}
        END {for (i=1;i<=n;i++) if (per[ordem[i]] && !resposta[ordem[i]])
              print "id="ordem[i]" -> "dono[ordem[i]]" | "txt[ordem[i]]}' "$LOG" | tail -20
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
python3 - "$ROSTER" "$MODO" "$LISTAR" "$FORCE" "$NOTA" "$HERE/../modules/ai/jarvis/src" > "$ALVOS_JSON" <<'PYEOF' || RC=$?
import json, subprocess, sys
roster_py, modo, listar, force, nota = sys.argv[1:6]
jarvis_src = sys.argv[6] if len(sys.argv) > 6 else ""
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

# (14/11) O "EU" E ACHADO PELA SESSAO, nao pela janela. A janela do
# opencode no TUI tem endereco VAZIO (nao e uma janela do Hyprland), e
# casar por "address == ''" pegava o primeiro agente com janela vazia:
# eu estava mandando mensagem como Lontra. A sessao e o identificador
# exato (mesma sessao do bloco IDENTITY).
me = None
_sess_own = str((own or {}).get("session") or "")
if _sess_own:
    for a in agents:
        if a.get("session") == _sess_own:
            me = a
            break
if me is None and own and own.get("address"):
    for a in agents:
        if a.get("window") == own.get("address"):
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
        # (14/11) O AGENTE MORA EM OUTRA MAQUINA: o nome nao esta no roster
        # local (celular, Windows), mas o BUS endereca por lane e e
        # cross-machine. A entrega correta e o bus (coord.send), nao a API
        # local (que nao alcanca outra maquina) e NUNCA focus+wtype.
        lane_hit = next((x for x in agents if x.get("lane") == modo), None)
        # o roster e POR MAQUINA: a lane de um agente que roda no celular
        # (ou no Windows) nao esta aqui. O BUS e global e conhece todas as
        # lanes, entao consultamos ele SO neste caminho (o caso comum nao
        # gasta uma chamada da API do GitHub, que tem limite de 60/h).
        if lane_hit is None:
            try:
                import sys as _sys
                _sys.path.insert(0, jarvis_src)
                from jarvis.core.coord import bus_state
                _st, _ = bus_state()
                for _a in (_st or {}).values():
                    if isinstance(_a, dict) and str(_a.get("lane") or "") == modo:
                        lane_hit = {"lane": modo}
                        break
            except Exception:
                pass
        if lane_hit is not None:
            targets.append({"kind": "lane", "address": f"bus:{modo}",
                            "name": modo, "lane": modo, "repo": "", "note": "",
                            "session": "", "busy": False, "pid": 0})
        else:
            print(json.dumps({"erro":
                              f"nome desconhecido no roster e nao e lane "
                              f"conhecida: {modo} (se o agente roda em outra "
                              f"maquina, enderece a LANE dele, ex.: --to "
                              f"termux/vpnsec)", "targets": [], "avisos": []}))
            sys.exit(1)
    elif a.get("state") != "live":
        print(json.dumps({"erro": f"'{modo}' não está vivo (janela fechada?)",
                          "targets": [], "avisos": []}))
        sys.exit(1)
    elif me and not force:
        hit = overlap(me, a)
        if hit:
            print(json.dumps({"erro":
                              f"lane/arquivos sobrepostos com '{modo}' "
                              f"({', '.join(hit)}) — envie como --note ou use "
                              f"--force", "targets": [], "avisos": []}))
            sys.exit(1)
        # (25/11, medido) SEM overlap o alvo TEM de entrar na lista. Antes o
        # `else` era do `if hit:` e o bloco `elif me and not force:` nao
        # acrescentava nada: com claim do remetente e sem overlap o alvo era
        # DESCARTADO em silencio -> "agent-msg: nenhum alvo (modo=<nome>)".
        # Medido: `bash scripts/agent-msg.sh --to challenge-dev ...` devolvia
        # "nenhum alvo" mesmo com a sessao do alvo VIVA na API.
        targets.append(alvo(a))
    else:
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
for t in d['targets']:
    a = t.get('address') or ''
    s = t.get('session') or ''
    # (19/11, medido) 5 dos 6 agentes do roster rodam o TUI dentro de um foot
    # e a janela do Hyprland tem address VAZIO: so' o address filtrava, entao
    # '--to <nome>' devolvia 'nenhum alvo' e a mensagem nao saia. Quem tem
    # sessao do opencode e' alcancavel pela API, entao o marcador @sess:<id>
    # carrega a identidade sem depender da janela.
    print(a if a else ('@sess:' + s))"
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
MINHA_LANE="$(python3 -c "
import json
d=json.load(open('$ALVOS_JSON'))
print((d.get('me') or {}).get('lane') or '')")"
[ "$MSG_ID" = "" ] && MSG_ID="m-$(date +%s)-$$"
if [ -f "$LOG" ] && grep -qF "| id=$MSG_ID |" "$LOG" && [ "$FORCE" -eq 0 ]; then
    echo "agent-msg: id '$MSG_ID' já existe no log (idempotência A2A) — use outro --id" >&2
    exit 5
fi
# dedupe por conteúdo (mesmo alvo+texto em janela curta) - evita loop de spam
DEDUPE_KEY=""
if [ "$FORCE" -eq 0 ]; then
    DEDUPE_KEY=$(python3 - "$MODO" "$TEXTO" <<'PYDED'
import hashlib, sys
mode, text = sys.argv[1], sys.argv[2]
norm = " ".join(text.split()).strip().lower()
print(hashlib.sha256((mode+"|"+norm).encode("utf-8","ignore")).hexdigest()[:16])
PYDED
)
    DEDUPE_FILE="/tmp/opencode/agent-msg-dedupe-${DEDUPE_KEY}.ts"
    mkdir -p /tmp/opencode
    if [ -f "$DEDUPE_FILE" ]; then
        LAST=$(cat "$DEDUPE_FILE" 2>/dev/null || echo 0)
        NOW=$(date +%s)
        AGE=$((NOW - LAST))
        if [ "$AGE" -lt 180 ]; then
            echo "agent-msg: conteúdo duplicado para alvo '$MODO' há ${AGE}s (dedupe 180s) — use --force para reenviar" >&2
            exit 0
        fi
    fi
fi
TEXTO_ESCAPED=$(printf '%s' "$TEXTO" | tr '\n' ' ')
# identidade do remetente (model/session) para auto-identificação
REMETENTE_MODEL="${OPENCODE_MODEL:-${AGENT_MODEL:-}}"
REMETENTE_SESS="${OPENCODE_SESSION_ID:-}"
if [ -z "$REMETENTE_MODEL" ] || [ -z "$REMETENTE_SESS" ]; then
    _ID_JSON=$(command -v oc-identidade >/dev/null 2>&1 && oc-identidade --json 2>/dev/null || true)
    if [ -n "$_ID_JSON" ]; then
        [ -z "$REMETENTE_MODEL" ] && REMETENTE_MODEL=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('model',''))" "$_ID_JSON" 2>/dev/null || true)
        [ -z "$REMETENTE_SESS" ] && REMETENTE_SESS=$(python3 -c "import json,sys; print(json.loads(sys.argv[1]).get('session',''))" "$_ID_JSON" 2>/dev/null || true)
    fi
fi
CABECALHO="[AGENT→AGENT] from $REMETENTE"
[ -n "$REMETENTE_MODEL" ] && CABECALHO="$CABECALHO model=$REMETENTE_MODEL"
[ -n "$REMETENTE_SESS" ] && CABECALHO="$CABECALHO sess=$REMETENTE_SESS"
CABECALHO="$CABECALHO id $MSG_ID"
[ -n "$REPLY_TO" ] && CABECALHO="$CABECALHO re:$REPLY_TO"
[ "$NOTA" -eq 1 ] && CABECALHO="$CABECALHO note" || CABECALHO="$CABECALHO ask ack=required"
TEXTO_FINAL="$CABECALHO: $TEXTO_ESCAPED"

# ── entrega via API do opencode ───────────────────────────────────────
# $1=sessão  $2=path ("/message" | "/prompt_async" | "/abort")  $3=json
oc_post() {
    # (07/11) FONTE UNICA: scripts/agent-api.py fala as duas linguas do
    # opencode (1.x: /session/:id/message|prompt_async; 2.x:
    # /api/session/:id/prompt) e cai da rota nova para a antiga. A copia
    # local tentava a rota nova SEM o /api -> caia no catch-all da SPA
    # (HTML 200) e depois nas 1.x (405 no 2.2.6) = frota silenciosa.
    local SESSAO="$1" PATHNAME="$2" BODY="$3" TEXTO="$4"
    case "$PATHNAME" in
        /abort)
            python3 "$HERE/agent-api.py" --url "$OC_URL" \
                --session "$SESSAO" --abort 2>&1
            ;;
        /message)
            python3 "$HERE/agent-api.py" --url "$OC_URL" \
                --session "$SESSAO" --text "$TEXTO" --note 2>&1
            ;;
        *)
            python3 "$HERE/agent-api.py" --url "$OC_URL" \
                --session "$SESSAO" --text "$TEXTO" 2>&1
            ;;
    esac
}

MINHA=$(hyprctl activewindow -j 2>/dev/null | python3 -c "import json,sys; print(json.load(sys.stdin).get('address',''))" 2>/dev/null || true)
TIPO="ask"; [ "$NOTA" -eq 1 ] && TIPO="note"
[ "$MODO" = "all" ] && TIPO="broadcast"
FALHOU=0

for END in "${ALVOS[@]}"; do
    INFO=$(python3 -c "
import json, sys
d=json.load(open('$ALVOS_JSON'))
end=sys.argv[1]
for t in d['targets']:
    ok = (t.get('address') or '') == end
    if not ok and end.startswith('@sess:'):
        ok = ('@sess:' + str(t.get('session') or '')) == end
    if ok:
        print(t.get('name') or '(janela)', '|', t.get('session') or '', '|',
              '1' if t.get('busy') else '0')
        break
" "$END")
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
            R=$(oc_post "$SESSAO" "/message" "$BODY" "$TEXTO_FINAL" || true)
            echo "agent-msg: nota entregue em $NOME_ALVO ($SESSAO) — sem rodar o agente: $R"
        else
            # PEDIDO: o agente roda (async = não espera a resposta)
            BODY=$(python3 -c '
import json, sys
print(json.dumps({"parts": [{"type": "text", "text": sys.argv[1]}]}))' "$TEXTO_FINAL")
            R=$(oc_post "$SESSAO" "/prompt_async" "$BODY" "$TEXTO_FINAL" || true)
            echo "agent-msg: pedido enviado a $NOME_ALVO ($SESSAO) — agente vai rodar: $R"
        fi
        printf '%s | %s | %s | %s(%s) | id=%s | re=%s | %s\n' \
            "$(date '+%d/%m %H:%M')" "$REMETENTE" "$TIPO" "$NOME_ALVO" "$END" \
            "$MSG_ID" "${REPLY_TO:--}" "$TEXTO_ESCAPED" >> "$LOG"
        [ -n "${DEDUPE_KEY:-}" ] && date +%s > "/tmp/opencode/agent-msg-dedupe-${DEDUPE_KEY}.ts" || true
        vis_visible "$REMETENTE" "$TIPO" "$NOME_ALVO" "$TEXTO_ESCAPED" "$SESSAO"
        continue
    fi

    # sem sessão local → BUS (14/11): o bus é cross-machine e é a fonte da
    # verdade da casa (coord.send publica kind=msg endereçado). O fallback
    # focus+wtype foi REMOVIDO de propósito: a regra da casa proíbe digitar
    # na caixa do dono (bloqueia a digitação dele) e estacionar texto ali
    # trava o teclado.
    DESTINO_BUS="${END#bus:}"
    [ "$DESTINO_BUS" = "$END" ] && DESTINO_BUS="$NOME_ALVO"
    R_BUS=$(PYTHONPATH="$HERE/../modules/ai/jarvis/src" python3 -c "
import sys
from jarvis.core.coord import send
print(send(to=sys.argv[1], message=sys.argv[2], agent=sys.argv[3], lane=sys.argv[4]))
" "$DESTINO_BUS" "$TEXTO_FINAL" "$REMETENTE" "$MINHA_LANE" 2>&1 | tail -2)
    echo "agent-msg: mensagem publicada NO BUS para $DESTINO_BUS (sem sessão local; o bus alcança outra máquina) — $R_BUS"
    printf '%s | %s | %s | %s(%s) | id=%s | re=%s | %s\n' \
        "$(date '+%d/%m %H:%M')" "$REMETENTE" "bus" "$DESTINO_BUS" "$END" \
        "$MSG_ID" "${REPLY_TO:--}" "$TEXTO_ESCAPED" >> "$LOG"
    [ -n "${DEDUPE_KEY:-}" ] && date +%s > "/tmp/opencode/agent-msg-dedupe-${DEDUPE_KEY}.ts" || true
    vis_visible "$REMETENTE" "bus" "$DESTINO_BUS" "$TEXTO_ESCAPED" ""
    continue

  # (14/11) bloco focus+wtype REMOVIDO: codigo morto — todo alvo ou
  # tem sessao local (delivery via API) ou cai no BUS. Nunca digita na
  # caixa do humano (mesma classe do wtype).
done

[ -n "$MINHA" ] && hyprctl dispatch focuswindow "address:$MINHA" >/dev/null 2>&1 || true
[ "$FALHOU" -eq 0 ] || exit 6
