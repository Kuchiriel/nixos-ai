"""coord.py — bus de coordenação entre agentes (protocolo `coord-json`).

POR QUE ISTO EXISTE (05/11/2026): duas IAs trabalham no mesmo repo e a
coordenação dependia de o dono avisar ("ela leu teu push", "confere o remoto").
O gargalo era humano. O bus passa a ser o próprio GitHub: um issue fixo com a
label `coord` carrega as intenções (claims) das IAs; cada uma lê antes de mexer
e reivindica os arquivos que vai tocar; o código detecta colisão de escopo.

O PROTOCOLO (não a implementação) é o contrato — o mesmo usado pelo cliente
Node do repo mt5 (`tools/coord.mjs`), para que implementações em linguagens
diferentes se entendam:

  - bus: um issue do repo com a label `coord` (append-only: comentário nunca
    conflita com outro comentário);
  - mensagem: comentário com um bloco ```coord-json``` contendo
    {kind, agent, lane, files[], intent, pr, head, note, ts};
  - estado atual: a última mensagem de cada agente;
  - colisão: duas claims ativas cujos globs de arquivo se sobrepõem;
  - claim velha: mais antiga que o TTL (6 h por padrão) = morta.

O transporte é trocável sem quebrar o contrato: o mesmo protocolo pode viver
num MCP (este módulo), num CLI Node (mt5) ou num canal Tailscale.

CONFIG (env, fora do repo — nunca commitar segredo):
  COORD_REPO   owner/repo do bus      (default: Kuchiriel/mt5)
  COORD_LABEL  label do issue         (default: coord)
  COORD_AGENT  identidade desta IA    (default: jarvis@<host>)
  COORD_TTL_H  horas de validade da claim (default: 6)

USO:
  from jarvis.core.coord import post, read, check
  post(kind="claim", lane="infra", files="backtest/*", intent="reconciliar")
  read()
  check(agent="opencode-matheus", files="backtest/make_ini.py")

Referência: arXiv 2605.18747 ("Code as Agent Harness") — "consistent shared
state across multiple agents" é desafio em aberto; repositório + artefatos
estruturados são o workspace comum que permite coordenar, revisar e verificar
coletivamente. O bus segue essa linhagem: estado compartilhado + artefato
estruturado (a claim) + verificação mecânica (colisão), não conversa.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import time
from typing import Any

JSON_FENCE = re.compile(r"```coord-json\s*([\s\S]*?)```")
DEFAULT_REPO = "Kuchiriel/mt5"
DEFAULT_LABEL = "coord"
DEFAULT_TTL_H = 6.0
CLAIM_KINDS = ("claim", "status", "blocked", "done", "handoff", "msg")
ACTIVE_KINDS = ("claim", "status", "blocked")
# Cache local do bus: o watcher faz polling (e ele e o que mantem as IAs em
# sync) e a API do GitHub tem limite (60 req/h por token). Sem cache, um poll
# por minuto estoura o limite e a sincronia para de funcionar.
DEFAULT_CACHE_TTL_S = 60.0

_CACHE: dict[str, Any] = {"at": 0.0, "state": {}, "issue": None,
                           "updated_at": "", "payloads": []}


def _gh_path() -> str:
    """Caminho do `gh` (o MCP roda como usuário; o token fica no hosts.yml)."""
    found = shutil.which("gh")
    if found:
        return found
    for candidate in ("/run/current-system/sw/bin/gh", "/usr/bin/gh"):
        if os.path.exists(candidate):
            return candidate
    return "gh"


def gh(*args: str, timeout: int = 30) -> str:
    """Roda o `gh` e devolve stdout (erro vira RuntimeError com o stderr)."""
    proc = subprocess.run(
        [_gh_path(), *args],
        capture_output=True,
        text=True,
        timeout=timeout,
    )
    if proc.returncode != 0:
        raise RuntimeError((proc.stderr or proc.stdout or "gh falhou").strip()[:500])
    return proc.stdout


def gh_json(*args: str, timeout: int = 30) -> Any:
    out = gh(*args, timeout=timeout)
    try:
        return json.loads(out) if out.strip() else None
    except json.JSONDecodeError:
        return None


def repo() -> str:
    return os.environ.get("COORD_REPO", DEFAULT_REPO)


def label() -> str:
    return os.environ.get("COORD_LABEL", DEFAULT_LABEL)


def agent_id() -> str:
    forced = os.environ.get("COORD_AGENT")
    if forced:
        return forced
    return f"jarvis@{socket.gethostname().split('.')[0]}"


def ttl_hours() -> float:
    try:
        return float(os.environ.get("COORD_TTL_H", DEFAULT_TTL_H))
    except ValueError:
        return DEFAULT_TTL_H


def cache_ttl_s() -> float:
    """TTL do cache local do bus.

    O watcher faz polling (a cada ciclo) e a API do GitHub tem limite
    (60 req/h por token): sem cache, um poll por minuto estoura o limite e a
    sincronia entre IAs — que depende do watcher — deixa de funcionar.
    """
    try:
        return float(os.environ.get("COORD_CACHE_TTL_S", DEFAULT_CACHE_TTL_S))
    except ValueError:
        return DEFAULT_CACHE_TTL_S


def invalidate_cache() -> None:
    """Invalidar o cache (usado depois de publicar: o próximo read é fresco)."""
    _CACHE["at"] = 0.0


def norm_glob(pattern: str) -> str:
    """Normaliza um glob de arquivo (mesma regra do cliente Node)."""
    return str(pattern or "").strip().removeprefix("./").rstrip("/")


def overlaps(a: str, b: str) -> bool:
    """Diz se dois globs de arquivo podem tocar o mesmo arquivo."""
    A, B = norm_glob(a), norm_glob(b)
    if not A or not B:
        return False
    if A == B:
        return True
    if "*" in A or "*" in B:
        pa = A.split("*")[0].rstrip("/")
        pb = B.split("*")[0].rstrip("/")
        if not pa or not pb:
            return True  # "**" cobre tudo
        return pa.startswith(pb) or pb.startswith(pa)
    return A.startswith(B + "/") or B.startswith(A + "/")


def _files_of(payload: dict[str, Any]) -> list[str]:
    files = payload.get("files") or []
    if isinstance(files, str):
        files = files.split(",")
    out: list[str] = []
    for item in files:
        for part in str(item).split(","):
            cleaned = norm_glob(part)
            if cleaned:
                out.append(cleaned)
    return out


def parse_payloads(bodies: list[str]) -> list[dict[str, Any]]:
    """Extrai os payloads coord-json dos comentários do bus."""
    out: list[dict[str, Any]] = []
    for body in bodies:
        match = JSON_FENCE.search(body or "")
        if not match:
            continue
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            out.append(payload)
    return out


def current_state(payloads: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Última mensagem de cada agente = estado atual."""
    state: dict[str, dict[str, Any]] = {}
    for payload in payloads:
        name = payload.get("agent") or "?"
        previous = state.get(name)
        if previous is None or str(payload.get("ts") or "") >= str(previous.get("ts") or ""):
            state[name] = payload
    return state


def _age_h(payload: dict[str, Any]) -> float:
    stamp = payload.get("ts") or ""
    try:
        created = time.mktime(time.strptime(str(stamp)[:19], "%Y-%m-%dT%H:%M:%S"))
    except (ValueError, TypeError):
        return 0.0
    return max(0.0, (time.time() - created) / 3600.0)


def active_claims(state: dict[str, dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Claims que ainda valem (kind ativo e dentro do TTL)."""
    return {
        name: payload
        for name, payload in state.items()
        if payload.get("kind") in ACTIVE_KINDS and _age_h(payload) <= ttl_hours()
    }


def collisions(state: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    """Claims ativos de agentes diferentes com escopo de arquivo sobreposto."""
    active = active_claims(state)
    names = sorted(active)
    found: list[dict[str, Any]] = []
    for i, a in enumerate(names):
        for b in names[i + 1:]:
            hits = [
                f"{fa} ↔ {fb}"
                for fa in _files_of(active[a])
                for fb in _files_of(active[b])
                if overlaps(fa, fb)
            ]
            hits = list(dict.fromkeys(hits))
            if hits:
                found.append({
                    "a": a,
                    "b": b,
                    "a_kind": active[a].get("kind"),
                    "b_kind": active[b].get("kind"),
                    "hit": hits,
                })
    return found


def find_issue(create: bool = False) -> int | None:
    """Número do issue do bus (cria se não existir e create=True)."""
    issues = gh_json(
        "issue", "list", "--repo", repo(), "--label", label(),
        "--state", "open", "--json", "number,title,url", "--limit", "10",
    ) or []
    if issues:
        return int(issues[0]["number"])
    if not create:
        return None
    body = (
        "# 🤝 Barramento de coordenação entre IAs\n\n"
        "Cada IA publica aqui sua **intenção** (claim) e lê antes de mexer.\n"
        "Mensagem = comentário com bloco ` ```coord-json ` — o estado atual de\n"
        "cada agente é o último comentário dele.\n\n"
        "Ferramenta: `node tools/coord.mjs {post|read|check}` (repo mt5) ou as\n"
        "tools `coord_post`/`coord_read`/`coord_check` do MCP do JARVIS.\n"
    )
    url = gh(
        "issue", "create", "--repo", repo(), "--label", label(),
        "--title", "🤝 COORD — claims e estado entre IAs", "--body", body,
    )
    match = re.search(r"issues/(\d+)", url)
    if not match:
        raise RuntimeError(f"não achei o número do issue criado: {url[:200]}")
    return int(match.group(1))


def comment_bodies(issue_number: int, pages: int = 20) -> list[str]:
    """Todos os comentários do issue (paginado)."""
    bodies: list[str] = []
    for page in range(1, pages + 1):
        chunk = gh_json(
            "api",
            f"repos/{repo()}/issues/{issue_number}/comments?per_page=100&page={page}",
        ) or []
        bodies.extend(str(c.get("body") or "") for c in chunk)
        if len(chunk) < 100:
            break
    return bodies


def bus_state(force: bool = False) -> tuple[dict[str, dict[str, Any]], int | None]:
    """Estado atual do bus (issue + último mensaje de cada agente).

    CACHE LOCAL (COORD_CACHE_TTL_S, default 60 s): o watcher faz polling e a
    API do GitHub tem limite (60 req/h por token). Sem cache, um poll por
    minuto estoura o limite e a sincronia entre IAs para. Quem escreve no bus
    chama `invalidate_cache()` para o próximo read já vir fresco.
    """
    now = time.time()
    if (not force and _CACHE["issue"] is not None
            and (now - float(_CACHE["at"])) < cache_ttl_s()):
        return dict(_CACHE["state"]), _CACHE["issue"]
    number = find_issue(create=False)
    if number is None:
        _CACHE.update({"at": now, "state": {}, "issue": None})
        return {}, None
    state = current_state(parse_payloads(comment_bodies(number)))
    _CACHE.update({"at": now, "state": state, "issue": number})
    return dict(state), number


def bus_payloads(force: bool = False) -> list[dict[str, Any]]:
    """Todos os payloads do bus (não só o último de cada agente) + updated_at.

    `updated_at` = timestamp do payload mais recente: o watcher usa como
    cursor (`since`) para saber o que é novo sem reprocessar tudo.
    """
    now = time.time()
    if (not force and _CACHE.get("payloads")
            and (now - float(_CACHE["at"])) < cache_ttl_s()):
        return list(_CACHE["payloads"])
    number = find_issue(create=False)
    if number is None:
        _CACHE.update({"at": now, "payloads": [], "issue": None})
        return []
    payloads = parse_payloads(comment_bodies(number))
    _CACHE.update({"at": now, "payloads": payloads, "issue": number,
                   "state": current_state(payloads)})
    return list(payloads)


def bus_updated_at() -> str:
    """Timestamp do payload mais recente do bus (cursor do watcher)."""
    payloads = bus_payloads()
    stamps = sorted(str(p.get("ts") or "") for p in payloads)
    return stamps[-1] if stamps else ""


def pending(
    agent: str | None = None,
    codename: str | None = None,
    files: str | list[str] | None = None,
    lane: str | None = None,
    since: str | None = None,
) -> list[dict[str, Any]]:
    """Só o que ME cabe: mensagens endereçadas a mim + claims que colidem.

    Endereçamento (formato do peer, 05/11/2026):
      - `to` = codinome (humano) do destinatário; `*` = todos da lane;
      - `to` pode ser a **lane** (para quem ainda não tem codinome);
      - claim de outro agente com arquivo sobreposto ao meu escopo também é
        "minha" (é o que pode virar colisão de verdade).
    `since` filtra por `ts` (cursor incremental do watcher).
    """
    me = agent or agent_id()
    my_files = _files_of({"files": files or []})
    out: list[dict[str, Any]] = []
    for payload in bus_payloads():
        ts = str(payload.get("ts") or "")
        if since and ts and ts <= str(since):
            continue
        kind = payload.get("kind")
        to = str(payload.get("to") or "")
        addressed = False
        if to in (me, codename or ""):
            addressed = True
        elif to == "*" and lane and str(payload.get("lane") or "") == lane:
            addressed = True
        elif to and to == lane:
            addressed = True
        overlapping = False
        if kind in ("claim", "status", "blocked"):
            their = _files_of(payload)
            for mine in my_files:
                for theirs in their:
                    if overlaps(mine, theirs):
                        overlapping = True
                        break
                if overlapping:
                    break
        if addressed or overlapping:
            item = dict(payload)
            item["_why"] = "endereçado" if addressed else "escopo sobreposto"
            out.append(item)
    return out


def open_prs() -> list[dict[str, Any]]:
    try:
        return gh_json(
            "pr", "list", "--repo", repo(), "--state", "open",
            "--json", "number,title,headRefName,updatedAt", "--limit", "20",
        ) or []
    except RuntimeError:
        return []


def post(
    kind: str = "claim",
    agent: str | None = None,
    lane: str = "",
    files: str | list[str] | None = None,
    intent: str = "",
    pr: int | None = None,
    note: str = "",
    head: str = "",
    to: str = "",
) -> str:
    """Publica uma claim/status/msg no bus (append-only) e devolve o issue usado.

    `to` = destinatário (codinome humano, `*` = todos da lane, ou a lane);
    sempre presente no payload (mesmo vazio) — é o que permite endereçar sem
    adivinhar (formato acordado com o Urubu em 05/11/2026).
    """
    if kind not in CLAIM_KINDS:
        raise ValueError(f"kind inválido: {kind} (use {'|'.join(CLAIM_KINDS)})")
    payload = {
        "kind": kind,
        "agent": agent or agent_id(),
        "to": to or "",
        "lane": lane or "",
        "files": _files_of({"files": files or []}),
        "intent": intent or "",
        "note": note or "",
        "pr": pr,
        "head": head or "",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
    }
    number = find_issue(create=True)
    body = (
        f"**{kind}** de `{payload['agent']}`"
        f"{' na lane `' + payload['lane'] + '`' if payload['lane'] else ''}"
        f"{' → `' + payload['to'] + '`' if payload['to'] else ''}"
        f"{' · PR #' + str(payload['pr']) if payload['pr'] else ''}\n\n"
        "```coord-json\n" + json.dumps(payload, indent=2, ensure_ascii=False) + "\n```"
    )
    gh("api", f"repos/{repo()}/issues/{number}/comments", "-f", f"body={body}")
    invalidate_cache()
    return (f"coord: {kind} de {payload['agent']} publicado no issue #{number} "
            f"({repo()}, label {label()})"
            + (f" → {payload['to']}" if payload["to"] else ""))


def send(
    to: str,
    message: str,
    agent: str | None = None,
    lane: str = "",
) -> str:
    """Publica uma mensagem endereçada no bus (kind=msg).

    O bus é a fonte da verdade: a entrega local (roster+msg) passa a ser só o
    **wake** do destinatário — assim a mensagem é cross-machine, auditável e
    chega mesmo para quem está em outra máquina da tailnet.
    """
    if not (message or "").strip():
        raise ValueError("mensagem vazia")
    return post(kind="msg", agent=agent, lane=lane, to=to,
                note=(message or "").strip())


def read() -> str:
    """Estado do bus em texto: agentes, claims, colisões e PRs abertos."""
    state, number = bus_state()
    if number is None:
        return (f"coord: ainda não existe issue de coordenação "
                f"(repo {repo()}, label {label()}) — crie com coord_post")
    lines = [f"coord: bus = {repo()} issue #{number} (label {label()})"]
    lines.append(f"bus_updated_at: {bus_updated_at()}")
    if not state:
        lines.append("agentes: (ninguém publicou claim ainda)")
    for name, payload in sorted(state.items()):
        age = _age_h(payload)
        stale = " ⚠️ VELHO" if age > ttl_hours() else ""
        files = ", ".join(_files_of(payload)) or "—"
        what = payload.get("intent") or payload.get("note") or "—"
        to = payload.get("to") or ""
        lines.append(
            f"- {name} · {payload.get('kind')} · {payload.get('lane') or '—'} · "
            f"{files} · {what} · {age:.1f}h{stale}"
            + (f" · → {to}" if to else "")
        )
    found = collisions(state)
    if found:
        lines.append("⚠️ COLISÕES:")
        for c in found:
            lines.append(f"   {c['a']} × {c['b']} → {' · '.join(c['hit'])}")
    else:
        lines.append("colisões: nenhuma")
    prs = open_prs()
    if prs:
        lines.append("PRs abertos:")
        for pr in prs:
            lines.append(f"- #{pr.get('number')} {pr.get('title')} ({pr.get('headRefName')})")
    return "\n".join(lines)


def check(agent: str | None = None, files: str | list[str] | None = None) -> str:
    """Verifica colisão de escopo. Sai com texto explícito se houver."""
    name = agent or agent_id()
    state, _ = bus_state()
    mine = state.get(name)
    scope = _files_of({"files": files or []})
    if mine:
        scope = scope or _files_of(mine)
    if not scope:
        return f"coord: sem escopo informado para {name} — informe files= ou publique uma claim"
    hits: list[str] = []
    for other, payload in state.items():
        if other == name:
            continue
        if payload.get("kind") not in ACTIVE_KINDS:
            continue
        if _age_h(payload) > ttl_hours():
            continue
        for mine_file in scope:
            for their_file in _files_of(payload):
                if overlaps(mine_file, their_file):
                    hits.append(f"{other}: {mine_file} ↔ {their_file}")
    hits = list(dict.fromkeys(hits))
    if hits:
        return ("coord: COLISÃO de claim — não edite antes de resolver:\n  "
                + "\n  ".join(hits))
    return (f"coord: escopo livre para {name} ({', '.join(scope)}) — "
            "nenhum outro agente ativo neste escopo")
