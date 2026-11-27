#!/usr/bin/env python3
"""agent-provider-guard.py — detecta falhas do PROVIDER de LLM e avisa (ping).

Por que existe (03/11/2026): o turno do agente morreu com
`ProviderHeaderTimeoutError: Provider response headers timed out after
300000ms` (nvidia/minimax, contexto ~145k) e o dono só descobriu 15 min
depois, quando o opencode desistiu (3 retries x 5 min). Os mesmos requests
também levam `Too Many Requests` (429, NIM free tier saturado) e
`Bad Request` (400 = prompt+max_tokens > contexto do modelo). Nada disso
é erro de tool — o agent-pains.sh não vê; o watcher não avisa.

O que faz: lê o log do opencode, classifica os erros de provider das
últimas N minutos, deduplica e — para cada evento NOVO — manda um ping
(notify-send no desktop do dono) e uma nota (agent-msg.sh --note) para a
peer, para o problema não ser silencioso.

Uso:
    agent-provider-guard.py scan [--since-min 15] [--max 5]
                                 [--dry-run] [--no-notify] [--no-peer]
    agent-provider-guard.py classes

Contrato:
    AGENTS_OC_LOG     log do opencode (default ~/.local/share/opencode/log/opencode.log)
    AGENTS_GUARD_STATE arquivo de dedup (default ~/.local/state/jarvis/provider-guard.seen.json)
    AGENTS_GUARD_PEER nome no roster p/ a nota (default coord-naming; vazio = não nota)
    saída             1 linha por evento NOVO (stdout); exit 0 SEMPRE (não quebra o watcher)
    --dry-run         não notifica e não grava estado (só mostra)

Exemplo:
    python3 scripts/agent-provider-guard.py scan --since-min 20 --dry-run
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

HOME = Path.home()
LOG_DEFAULT = HOME / ".local/share/opencode/log/opencode.log"
STATE_DEFAULT = HOME / ".local/state/jarvis/provider-guard.seen.json"
AGENT_MSG = Path(__file__).resolve().parent / "agent-msg.sh"

# cooldown por (classe, provider, sessao): 1 ping a cada 15 min, mesmo com
# dezenas de linhas iguais no log (429 repete a cada retry -> spam no peer)
COOLDOWN_SEC = 900

# (24/11, medido) CLASSES NUNCA PRODUZIU "RATE_LIMIT": o classificador
# devolvia "RATE" (veja a lista abaixo) e a rotacao comparava com
# "RATE_LIMIT" — duas strings diferentes. Resultado: a rotacao automatica de
# modelo (o commit 86a5cc12, 15/11) NUNCA rodou, porque a condicao nunca era
# verdadeira. Agora a lista e' explicita e compartilhada com o classificador.
ROTATE_CLASSES = ("RATE", "RATE_LIMIT", "QUOTA", "MODEL")

# classificação: (padrão no texto do erro, classe, dica acionável)
#
# (24/11, medido) Os padroes foram medidos no texto REAL do log do 2.2.6, que
# nao bate com as mensagens HTTP crabras. Amostra do log vivo:
#   "AI.Error: API rate limit exceeded ..."
#   "AI.Error: Too Many Requests ..."
#   "AI.Error: nv-gate: request too large for the upstream context ..."
#   "AI.Error: Invalid request ..." (com o status HTTP em outra parte da linha)
#   "AI.Error: Model 'nemotron-3-nano:30b' is currently unavailable."
# O classificador antigo procurava "Too Many Requests" (que o 2.2.6 escreve
# como "API rate limit exceeded") e "Bad Request" (que ele escreve como
# "Invalid request"), entao TODO evento caia em OTHER: medido, 10 de 10
# eventos classificados como OTHER depois do fix do regex.
CLASSES = (
    ("ProviderHeaderTimeoutError", "TIMEOUT",
     "provider nao mandou headers em 5 min (contexto grande/fornecedor lento); "
     "opencode tenta +2x antes de desistir — considere trocar de modelo"),
    ("API rate limit exceeded", "RATE",
     "429 do provider (free tier saturado; varios agentes na mesma chave); "
     "espere ~1 min ou troque de provider"),
    ("Too Many Requests", "RATE",
     "429 do provider (free tier saturado; varios agentes na mesma chave); "
     "espere ~1 min ou troque de provider"),
    ("rate limit", "RATE",
     "429 do provider (free tier saturado); troque de provider"),
    ("daily free allocation", "QUOTA",
     "cota diaria do provider esgotada (o erro traz o valor); troque de provider"),
    ("exceeds the available context size", "CTX",
     "request passou do contexto do server local; compacte a sessao"),
    ("request too large for the upstream context", "CTX",
     "o request passou do contexto REAL do modelo no upstream; "
     "compacte a sessao ou troque de modelo"),
    ("Bad Request", "BADREQ",
     "400 do provider: prompt_tokens + max_tokens > contexto do modelo "
     "(ou request invalido); compacte a sessao"),
    ("Invalid request", "BADREQ",
     "400 do provider (o 2.2.6 escreve 'Invalid request' onde o outro "
     "escrevia 'Bad Request'); prompt invalido ou acima do contexto; "
     "compacte a sessao"),
    ("is currently unavailable", "MODEL",
     "o modelo do provider saiu do catalogo (EOL ou indisponivel); "
     "troque de modelo"),
    ("no longer available on OpenRouter", "MODEL",
     "o modelo saiu do catalogo do OpenRouter (EOL); troque de modelo"),
    # (26/11, medido no log vivo, lane endpoint-ovhcloud) O 2.2.6 anuncia
    # EOL com esta frase, e ela nao casa com "is currently unavailable"
    # nem com "no longer available on OpenRouter". Medido em 7 dias: 28
    # eventos com este texto caiam em OTHER, e OTHER nao esta em
    # ROTATE_CLASSES — a sessao ficava no modelo morto.
    ("has reached its end of life", "MODEL",
     "o modelo do provider foi encerrado (EOL anunciado pelo upstream); "
     "troque de modelo"),
    # (26/11, medido) O 2.2.6 escreve o 429 como "Provider request failed
    # with HTTP 429", sem o texto "Too Many Requests" que o classificador
    # procurava: 11 eventos em 7 dias cairam em OTHER.
    ("Provider request failed with HTTP 429", "RATE",
     "429 do provider (free tier saturado ou cota do plano); "
     "espere ~1 min ou troque de provider"),
    ("Service temporarily overloaded", "RATE",
     "provider sobrecarregado (503/overloaded); transitorio, "
     "espere e tente de novo ou troque de provider"),
    ("AI_APICallError", "API",
     "erro de API do provider; veja o log"),
)

# (24/11, medido) O FORMATO DO LOG MUDOU COM O OPENCODE 2.2.6 E O GUARD
# FICOU CEGO. O regex antigo exigia, na mesma linha:
#   message="stream error" ... providerID=... modelID=... session.id=...
#       ... error.error="..."
# Medido no log vivo: 172 linhas com level=ERROR, ZERO casam com esse regex.
# O 2.2.6 escreve o erro assim:
#   timestamp=... level=ERROR run=... message="Failed to drain Session"
#       cause="AI.Error: API rate limit exceeded\n ..." sessionID=ses_...
# Consequencia medida: o provider do operator (ovhcloud/gpt-oss-20b) devolveu
# 429 por 4 dias seguidos (21/11, 22/11, 23/11, 24/11) e o guard NENHUM
# evento viu: sem aviso ao dono, sem rotacao de modelo, sem prova no bus.
#
# A ORDEM DOS CAMPOS VARIA (no log real, `cause=` vem ANTES de `sessionID=`),
# por isso cada campo e' buscado por uma regex propria em vez de um regex
# unico e ordenado.
TS_RE = re.compile(r'timestamp=(?P<ts>\S+)\s+level=ERROR')
MSG_RE = re.compile(r'message="(?:stream error|Failed to drain Session)"')
PROVIDER_RE = re.compile(r'providerID=(?P<v>\S+)')
MODEL_RE = re.compile(r'modelID=(?P<v>\S+)')
SESSION_RE = re.compile(r'(?:sessionID=|session\.id=)(?P<v>\S+)')
ERROR_RE = re.compile(r'(?:error\.error="(?P<v1>[^"]+)"|cause="(?P<v2>(?:[^"\\]|\\.)*)")')
# (26/11, medido) O 2.2.6 nao escreve providerID= nem modelID= nas linhas
# de erro (medido: 0 de 63 linhas ERROR 'Failed to drain Session' tem
# qualquer um dos dois), mas o texto do erro nomeia o modelo morto:
# "The model 'google/gemma-4-31b-it' has reached its end of life ...".
MODEL_IN_ERROR_RE = re.compile(r"The model '(?P<v>[^']+)'")

# (26/11) O provider vem do CONFIG do opencode: o id do modelo no config
# e' "google/gemma-4-31b-it" e o prefixo do catalogo e' o provider
# ("nvidia/google/gemma-4-31b-it"). Sem isso a nota saia como
# "PROVIDER OTHER em /" (medido: 223 de 361 notas no AGENTS-MSG.log).
OC_CONFIG = HOME / ".config/opencode/opencode.json"
_OC_PROVIDERS: dict[str, dict[str, str]] | None = None


def _opencode_providers() -> dict[str, dict[str, str]]:
    """{provider: {model_id_sem_provider: id_com_provider}} do config local.

    Cacheado no processo: o config muda por reload do opencode, nao por
    request, entao reler a cada evento seria desperdicio.
    """
    global _OC_PROVIDERS
    if _OC_PROVIDERS is not None:
        return _OC_PROVIDERS
    out: dict[str, dict[str, str]] = {}
    try:
        data = json.loads(OC_CONFIG.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — sem config, sem provider (e normal)
        _OC_PROVIDERS = out
        return out
    for pid, pv in (data.get("provider") or {}).items():
        models = (pv or {}).get("models") or {}
        if isinstance(models, dict):
            for mid in models:
                out.setdefault(pid, {})[mid] = f"{pid}/{mid}"
        elif isinstance(models, list):
            for entry in models:
                mid = entry.get("id") if isinstance(entry, dict) else entry
                if isinstance(mid, str):
                    out.setdefault(pid, {})[mid] = f"{pid}/{mid}"
    _OC_PROVIDERS = out
    return out


def model_from_error(error: str) -> str:
    """O id do modeloquoted no texto do erro (o 2.2.6 so nomeia o modelo la)."""
    m = MODEL_IN_ERROR_RE.search(error or "")
    return m.group("v").strip() if m else ""


def provider_for_model(model_id: str,
                       providers: dict[str, dict[str, str]] | None = None) -> str:
    """Provider que serve este modelo, pelo config do opencode.

    Aceita o id com ou sem o prefixo do provider ('google/gemma-4-31b-it'
    e 'nvidia/google/gemma-4-31b-it' dao o mesmo provider). O catalogo pode
    ser injetado no teste; sem ele, vem do config local.
    """
    if not model_id:
        return ""
    catalog = _opencode_providers() if providers is None else providers
    for pid, models in catalog.items():
        if model_id in models:
            return pid
        if model_id in models.values():
            return pid
        if f"{pid}/{model_id}" in models.values():
            return pid
    return ""


# (26/11, medido) Quando o texto do erro NAO nomeia o modelo (429 com corpo
# de cota, overloaded, CTX), o par provider/model vem da sessao pela API do
# opencode: GET /api/session/<id> devolve o model da sessao. Medido: 13ms
# por chamada. A mesma API e a mesma credencial que o agent-model.py usa
# (mesmo arquivo server.env, mesmo host), entao nao ha fonte nova.
SERVE = os.environ.get("AGENTS_OC_URL", "http://100.121.100.103:4599")
SERVER_ENV = HOME / ".config/opencode/server.env"
_SESSION_CACHE: dict[str, tuple[str, str]] = {}


def _server_password() -> str:
    pw = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
    if not pw and SERVER_ENV.is_file():
        try:
            for line in SERVER_ENV.read_text(encoding="utf-8").splitlines():
                if line.startswith("OPENCODE_SERVER_PASSWORD="):
                    pw = line.split("=", 1)[1].strip().strip('"')
                    break
        except OSError:
            pass
    return pw


def session_provider_model(session: str) -> tuple[str, str]:
    """(provider, model) do modelo ATUAL da sessao, pela API do opencode."""
    if not session:
        return "", ""
    if session in _SESSION_CACHE:
        return _SESSION_CACHE[session]
    pair = ("", "")
    try:
        import base64
        token = base64.b64encode(f"opencode:{_server_password()}".encode()).decode()
        req = urllib.request.Request(
            f"{SERVE}/api/session/{session}",
            headers={"Authorization": f"Basic {token}"})
        with urllib.request.urlopen(req, timeout=8) as resp:
            data = json.loads(resp.read() or "{}")
        data = data.get("data", data)
        model = data.get("model") or {}
        mid = model.get("id") or ""
        if mid:
            pair = (model.get("providerID", ""), mid)
    except Exception:  # noqa: BLE001 — sem sessao, sem provider (e normal)
        pair = ("", "")
    _SESSION_CACHE[session] = pair
    return pair


# (27/11, medido) O cooldown que o agent-model.py e o team.py consultam
# (provider-cooldown.json) e' por ID DE MODELO. Sem marcar o modelo morto
# nele, o EOL continua candidato em toda rotacao. Medido em 24h: o mesmo
# EOL (google/gemma-4-31b-it) reapareceu 6 vezes na mesma sessao.
MODEL_COOLDOWN = HOME / ".local/state/jarvis/provider-cooldown.json"


def mark_model_cooldown(provider: str, model: str) -> None:
    """Marca o modelo como caido no cooldown que a rotacao consulta.

    O id tem de ser o do CATALOGO (provider/modelo): e' a chave que o
    agent-model.py e o team.py leem. A sessao e o texto do erro dao o
    provider e o modelo SEPARADOS (o id do modelo ainda sem o prefixo do
    provider), entao o id do catalogo e' provider + "/" + modelo — e ele
    so e' valido se o config do opencode conhece esse par.
    """
    if not provider or not model:
        return
    catalog = _opencode_providers().get(provider, {})
    if model not in catalog:
        return
    model_id = catalog[model]
    try:
        MODEL_COOLDOWN.parent.mkdir(parents=True, exist_ok=True)
        data = {}
        if MODEL_COOLDOWN.is_file():
            data = json.loads(MODEL_COOLDOWN.read_text(encoding="utf-8"))
        data[model_id] = time.time()
        MODEL_COOLDOWN.write_text(json.dumps(data, indent=1), encoding="utf-8")
    except Exception:  # noqa: BLE001 — cooldown e' melhor-esforco
        pass


def _unquote(text: str | None) -> str:
    """Volta as sequencias de escape do campo quoted do log."""
    if not text:
        return ""
    return (text.replace("\\n", " ").replace('\\"', '"')
                .replace("\\\\", "\\").strip())


def classify(error: str) -> tuple[str, str]:
    for pattern, cls, hint in CLASSES:
        if pattern in error:
            return cls, hint
    return "OTHER", "erro de provider não classificado"


def parse_events(log_path: Path, since_min: int,
                 session_lookup=session_provider_model) -> list[dict]:
    """Eventos de provider das últimas `since_min` minutos (mais novo primeiro).

    `session_lookup` resolve (provider, model) da sessao quando o log nao
    traz providerID/modelID (o 2.2.6 nao traz). É injetável para o teste
    hermético não depender da rede.
    """
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=since_min)
    events: list[dict] = []
    # lê só o rabo do log (26MB+): 4MB cobre com folga N minutos de atividade
    try:
        with log_path.open("rb") as fh:
            fh.seek(0, os.SEEK_END)
            size = fh.tell()
            fh.seek(max(0, size - 4_000_000))
            tail = fh.read().decode("utf-8", errors="replace")
    except OSError:
        return events
    for line in tail.splitlines():
        if not TS_RE.search(line) or not MSG_RE.search(line):
            continue
        ts_m = TS_RE.search(line)
        err_m = ERROR_RE.search(line)
        if not ts_m or not err_m:
            continue
        try:
            ts = datetime.fromisoformat(ts_m["ts"].replace("Z", "+00:00"))
        except ValueError:
            continue
        if ts < cutoff:
            continue
        # (24/11) O erro vem em dois formatos: error.error= (log antigo) e
        # cause= (log do 2.2.6, com escapes). A sessao tambem: session.id=
        # (antigo) ou sessionID= (2.2.6).
        error = _unquote(err_m.group("v1") or err_m.group("v2"))
        sess_m = SESSION_RE.search(line)
        prov_m = PROVIDER_RE.search(line)
        model_m = MODEL_RE.search(line)
        if not error:
            continue
        cls, hint = classify(error)
        # (26/11, medido) As linhas do 2.2.6 nao tem providerID= nem
        # modelID=, entao provider e model saiam vazios e a nota virava
        # "PROVIDER OTHER em /". O texto do erro nomeia o modelo; o
        # provider vem do config do opencode.
        provider = (prov_m["v"].strip('"') if prov_m else "")
        model = (model_m["v"].strip('"') if model_m else "")
        if not model:
            model = model_from_error(error)
        if not provider and model:
            provider = provider_for_model(model)
        if not provider or not model:
            # (26/11, medido) 30 dos 58 eventos de 7 dias nao nomeiam o
            # modelo no texto (429 com corpo de cota, overloaded, CTX).
            # A sessao sabe qual provider/modelo era: GET /api/session/<id>.
            sprov, smodel = session_lookup(
                sess_m["v"].strip('"') if sess_m else "")
            provider = provider or sprov
            model = model or smodel
        events.append({
            "ts": ts.isoformat(),
            "epoch": int(ts.timestamp()),
            "provider": provider,
            "model": model,
            "session": (sess_m["v"].strip('"') if sess_m else ""),
            "error": error[:200],
            "class": cls,
            "hint": hint,
        })
    events.sort(key=lambda e: e["epoch"], reverse=True)
    return events


def load_state(path: Path) -> tuple[set[str], dict[str, int]]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set(), {}
    seen = set(data.get("seen") or [])
    cooldown = {str(k): int(v) for k, v in (data.get("cooldown") or {}).items()}
    return seen, cooldown


def save_state(path: Path, seen: set[str], cooldown: dict[str, int]) -> None:
    # mantém os 300 mais recentes (a chave é o timestamp do evento)
    ordered = sorted(seen)[-300:]
    trimmed = {k: v for k, v in sorted(cooldown.items(), key=lambda kv: kv[1])[-200:]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"seen": ordered, "cooldown": trimmed}, indent=0),
                    encoding="utf-8")


def ping(title: str, body: str) -> None:
    notifier = shutil.which("notify-send") or "/run/current-system/sw/bin/notify-send"
    try:
        subprocess.run([notifier, "-u", "critical", "-a", "opencode", title, body],
                       timeout=5, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass


def peer_note(text: str, peer: str) -> None:
    if not peer or not AGENT_MSG.exists():
        return
    try:
        subprocess.run(["bash", str(AGENT_MSG), "--note", text, peer],
                       timeout=15, check=False,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except (OSError, subprocess.SubprocessError):
        pass



AGENT_MODEL = HOME / "projects/nixos-ai/scripts/agent-model.py"


def rotate_model(session: str, provider: str, model: str) -> str:
    """Troca o modelo da sessao quando o provider caiu (429).

    (15/11, crouton-alpha) O guard JA classificava 429 e escrevia "troque
    de provider" no aviso — mas nao trocava. Agora ele troca: usa o
    agent-model.py, que roda UM turno na sessao com o proximo modelo
    disponivel (cooldown-aware) e marca o provider caido em cooldown.
    Medido: 'opencode run -s <sess> -m <model>' e o caminho que troca de
    verdade (o PATCH /api/session nao troca o modelo do TUI em execucao).
    """
    if not session or not AGENT_MODEL.is_file():
        return ""
    try:
        p = subprocess.run(
            ["python3", str(AGENT_MODEL), "--run", session,
             "[provider-guard] Troca automatica de modelo: o provider "
             f"{provider}/{model} caiu em rate-limit. Retome a tarefa em "
             " andamento no novo modelo; NAO repita o que ja foi feito.",
             "--max-tries", "2"],
            capture_output=True, text=True, timeout=420)
        out = (p.stdout or "").strip()
        try:
            d = json.loads(out)
            if d.get("ok"):
                return f"modelo trocado para {d.get('model')}"
            return "troca falhou: " + str(d.get("error") or d.get("tried"))[:160]
        except Exception:
            return (out or p.stderr or "")[:160]
    except Exception as exc:  # noqa: BLE001
        return f"troca falhou: {exc}"

def cmd_scan(args: argparse.Namespace) -> int:
    log_path = Path(os.environ.get("AGENTS_OC_LOG", str(LOG_DEFAULT)))
    state_path = Path(os.environ.get("AGENTS_GUARD_STATE", str(STATE_DEFAULT)))
    peer = "" if args.no_peer else os.environ.get("AGENTS_GUARD_PEER", "coord-naming")
    if not log_path.exists():
        print(f"provider-guard: log ausente ({log_path})")
        return 0
    seen, cooldown = load_state(state_path)
    events = parse_events(log_path, args.since_min)
    fresh = [e for e in events if str(e["epoch"]) not in seen][: args.max]
    if not fresh:
        print(f"provider-guard: sem evento novo em {args.since_min}min")
        return 0
    now = int(datetime.now().timestamp())
    for e in fresh:
        when = datetime.fromtimestamp(e["epoch"]).strftime("%H:%M")
        key = f"{e['class']}|{e['provider']}|{e['session']}"
        line = (f"{e['class']} {e['provider']}/{e['model']} "
                f"sessao={e['session']} as {when}: {e['hint']}")
        seen.add(str(e["epoch"]))
        if now - cooldown.get(key, 0) < COOLDOWN_SEC:
            continue
        print(line)
        if args.dry_run:
            cooldown[key] = max(e["epoch"], now)
            continue
        if not args.no_notify:
            ping(f"opencode: {e['class']} ({e['provider']})", line[:220])
        # (27/11, medido) Modelo EOL: marca no cooldown que a rotacao
        # consulta (provider-cooldown.json, por id do catalogo), senao o
        # modelo morto volta a ser candidato em toda rotacao. Medido em
        # 24h: o mesmo EOL reapareceu 6 vezes na mesma sessao.
        if e["class"] == "MODEL" and "end of life" in e["error"]:
            mark_model_cooldown(e["provider"], e["model"])
        # (15/11) ROTACAO AUTOMATICA: so para 429 (rate-limit). O
        # provider cai em cooldown e a sessao segue em outro modelo.
        rot = ""
        if e["class"] in ROTATE_CLASSES and not args.no_rotate and e.get("session"):
            rot = rotate_model(e["session"], e.get("provider", ""), e.get("model", ""))
            if rot:
                print(f"provider-guard: rotacao: {rot}")
        if peer:
            extra = f" | rotacao: {rot}" if rot else ""
            peer_note(f"PROVIDER {e['class']} em {e['provider']}/{e['model']} "
                      f"(sessao {e['session']}, {when}): {e['hint']}{extra}", peer)
        cooldown[key] = max(e["epoch"], now)
    if not args.dry_run:
        save_state(state_path, seen, cooldown)
    return 0


def cmd_classes(_: argparse.Namespace) -> int:
    for pattern, cls, hint in CLASSES:
        print(f"{cls:8s} {pattern} -> {hint}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd")
    scan = sub.add_parser("scan", help="procura eventos novos e notifica")
    scan.add_argument("--since-min", type=int, default=15)
    scan.add_argument("--max", type=int, default=5)
    scan.add_argument("--dry-run", action="store_true")
    scan.add_argument("--no-rotate", action="store_true",
                      help="nao troca o modelo automaticamente no 429")
    scan.add_argument("--no-notify", action="store_true")
    scan.add_argument("--no-peer", action="store_true")
    sub.add_parser("classes", help="lista as classes de erro")
    args = ap.parse_args()
    if args.cmd == "classes":
        return cmd_classes(args)
    if args.cmd in (None, "scan"):
        if args.cmd is None:
            args = ap.parse_args(["scan"])
        if getattr(args, "no_notify", False):
            args.no_peer = True
        return cmd_scan(args)
    ap.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
