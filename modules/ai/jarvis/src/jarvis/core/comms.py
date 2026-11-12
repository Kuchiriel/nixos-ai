"""comms.py — a camada de comunicação UNIFICADA dos agentes (dono, 07/11).

POR QUE ESTE MÓDULO EXISTE
-------------------------
Até 07/11 havia três sistemas que não se falavam, cada um com seu quadro,
seu transporte e seu público:

  1. O BUS de coord (`core/coord.py` + MCP `coord`): é onde os agentes
     opencode se falam — claims, mensagens endereçadas, wake, colisão de
     escopo. Fonte da verdade: um issue do GitHub com blocos `coord-json`.
  2. O TELEGRAM do JARVIS (`providers/telegram.py`): o dono no celular, com
     25 comandos, missões e aprovações. A ponte dele com o opencode era
     `opencode run` (one-shot: sessão nova, sem histórico, sem roster,
     sem noReply) — ou seja, o Telegram **não** alcançava os agentes vivos.
  3. OS BOTS DO `team/` (`~/projects/team`): `queue.md` (quadro-negro),
     `tg.sh` (Telegram multi-bot), `handoff.sh`. Rodavam de madrugada
     (`team-suite.timer`, 03:30) — mas no **jogo de teste** (dungeon),
     que não ajuda em nada.

Este módulo é o TEÚDO: o **bus é a fonte da verdade**, a **API do opencode
é o transporte de entrega**, e o **Telegram vira um terminal do mesmo bus**.
Fila: UMA (o bus). Sem kanban paralelo, sem fila de missão separada.

CONTRATO DE ENTREGA (medido no `scripts/agent-msg.sh`, que é o caminho
canônico — aqui em Python para o mesmo bus poder servir Telegram, o
serviço de madrugada e qualquer agente):

  NOTA   POST {base}/session/{sid}/message
           {"parts":[{"type":"text","text":...}],"noReply":true}
           → a mensagem ENTRA na sessão do agente e ele NÃO roda (zero token).
  PEDIDO POST {base}/session/{sid}/prompt_async
           {"parts":[{"type":"text","text":...}]}
           → o agente roda (assíncrono).

Auth: Basic, de `~/.config/opencode/server.env`
(OPENCODE_SERVER_USERNAME / OPENCODE_SERVER_PASSWORD). Base: `AGENTS_OC_URL`
(default = a tailnet do opencode serve, a mesma do agent-msg.sh).
"""
from __future__ import annotations

import base64
import json
import os
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

# ── config do transporte ─────────────────────────────────────────────────
def _find_roster() -> Path:
    """Acha o agent-roster.py subindo a árvore (não depende da profundidade)."""
    for parent in Path(__file__).resolve().parents:
        cand = parent / "scripts" / "agent-roster.py"
        if cand.is_file():
            return cand
    return Path("/home/nixos/projects/nixos-ai/scripts/agent-roster.py")


ROSTER_PY = _find_roster()
SERVER_ENV = Path(
    os.environ.get("AGENTS_OC_ENVFILE", "~/.config/opencode/server.env")
).expanduser()
DEFAULT_BASE = "http://100.121.100.103:4599"


def oc_base() -> str:
    """Base URL da API do opencode serve."""
    return os.environ.get("AGENTS_OC_URL", DEFAULT_BASE).rstrip("/")


def _auth_header() -> str:
    user = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
    pw = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
    if not pw and SERVER_ENV.is_file():
        for line in SERVER_ENV.read_text(encoding="utf-8", errors="ignore").splitlines():
            line = line.strip()
            if line.startswith("OPENCODE_SERVER_PASSWORD="):
                pw = line.split("=", 1)[1].strip().strip('"').strip("'")
                break
    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return "Basic " + token


def _post(path: str, body: dict[str, Any], timeout: int = 25) -> tuple[bool, str]:
    url = f"{oc_base()}{path}"
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        method="POST",
        headers={
            "Content-Type": "application/json",
            "Authorization": _auth_header(),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return True, f"{r.status} {r.read()[:160].decode(errors='replace')}"
    except urllib.error.HTTPError as e:
        return False, f"HTTP {e.code} {e.read()[:200].decode(errors='replace')}"
    except Exception as e:  # noqa: BLE001 — a entrega nunca deve derrubar o chamador
        return False, f"ERRO {e}"


# ── roster: quem está vivo (e com que sessão) ───────────────────────────
def _roster(*args: str) -> dict[str, Any]:
    if not ROSTER_PY.is_file():
        return {}
    try:
        out = subprocess.run(
            [sys.executable, str(ROSTER_PY), *args],
            capture_output=True, text=True, timeout=20,
        ).stdout
        return json.loads(out or "{}")
    except Exception:
        return {}


_LIVE_CACHE: tuple[float, list[dict[str, Any]]] = (0.0, [])


def live_agents(max_age_s: float = 5.0) -> list[dict[str, Any]]:
    """Agentes vivos: nome, codinome, lane, sessão, repo e escopo.

    Junta o roster (quem fez claim) com as janelas opencode vivas (quem tem
    sessão para receber mensagem). É a lista que o Telegram mostra e que a
    entrega usa. O CODINOME vem junto: é pelo codinome que o bus endereça
    (o roster e por máquina, o bus e cross-machine — medir 07/11: 13 nomes
    para 6 agentes).
    """
    global _LIVE_CACHE
    ts, cached = _LIVE_CACHE
    if cached and (time.time() - ts) <= max_age_s:
        return cached
    try:
        from jarvis.core.coord_roster import roster_agents as _ra

        roster = _ra()
    except Exception:
        roster = _roster("list", "--json").get("agents", []) or []
    win = _roster("windows", "--json") or {}
    by_addr = {w.get("address"): w for w in (win.get("all") or [])}
    own = win.get("own") or {}
    out: list[dict[str, Any]] = []
    for a in roster:
        w = by_addr.get(a.get("window") or "") or {}
        # A sessão vem da JANELA VIVA (o roster pode ter session velha);
        # cai no session do roster se a janela não souber.
        sess = w.get("session") or a.get("session") or ""
        out.append(
            {
                "name": a.get("name") or "?",
                "codename": a.get("codename") or "",
                "aliases": list(a.get("aliases") or []),
                "model": a.get("model") or "",
                "lane": a.get("lane") or "",
                "repo": a.get("repo") or "",
                "files": a.get("files") or [],
                "session": sess,
                "busy": bool(w.get("busy")),
                "window": a.get("window") or w.get("address") or "",
                "note": (a.get("note") or "")[:120],
                "state": a.get("state") or "",
            }
        )
    if own:
        out.append(
            {
                "name": own.get("name") or "eu",
                "lane": own.get("lane") or "",
                "repo": own.get("repo") or "",
                "files": [],
                "session": own.get("session") or "",
                "busy": bool(own.get("busy")),
                "window": own.get("address") or "",
                "note": "esta sessao",
            }
        )
    _LIVE_CACHE = (time.time(), out)
    return out


def find_agent(name: str) -> dict[str, Any] | None:
    needle = (name or "").strip().lower()
    for a in live_agents():
        if a["name"].lower() == needle:
            return a
    for a in live_agents():
        if needle and (needle in a["name"].lower() or needle in (a["lane"] or "").lower()):
            return a
    return None


# ── entrega ──────────────────────────────────────────────────────────────
def deliver(agent: str, text: str, *, request: bool = False) -> tuple[bool, str]:
    """Entrega uma mensagem a um agente vivo.

    request=False → NOTA: entra na sessão dele, ele NÃO roda (zero token).
    request=True  → PEDIDO: o agente roda (assíncrono).

    Se o agente não tem sessão conhecida, devolve (False, motivo) — o
    chamador decide (NUNCA estacionar texto na caixa do dono: bloqueia o
    teclado e não entra na fila).
    """
    # Caminho CANÔNICO: coord_roster.send_message = grava no bus (cross-
    # machine, auditável) + wake local via agent-msg.sh. Se o wake local
    # falhar, a mensagem continua no bus (nada se perde).
    try:
        from jarvis.core.coord_roster import send_message

        detail = send_message(agent, text, note=not request)
        ok = "ERROR" not in str(detail)[:40]
        return ok, str(detail)
    except Exception as e:  # noqa: BLE001
        pass
    # Fallback: entrega direta na API (sem o bus) — para o caso do roster
    # estar indisponível.
    a = find_agent(agent)
    if not a:
        return False, f"agente '{agent}' não está no roster"
    sess = a.get("session") or ""
    if not sess:
        return False, (
            f"agente '{a['name']}' sem sessão (API não serve) — "
            "use o bus (coord_msg) ou abra a sessão"
        )
    body = {"parts": [{"type": "text", "text": text}]}
    path = "/prompt_async" if request else "/message"
    if not request:
        body["noReply"] = True
    ok, detail = _post(f"/session/{sess}{path}", body)
    return ok, f"{a['name']} ({sess}) — {detail}"


# ── o quadro (kanban) — o BUS é a fonte da verdade ───────────────────────
def board() -> dict[str, Any]:
    """O quadro único: claims ativas no bus + agentes vivos + colisões."""
    try:
        from jarvis.core.coord import active_claims, bus_state, collisions, current_state

        state, _issue = bus_state()
        claims = active_claims(state)
        cols = collisions(state)
    except Exception as e:  # noqa: BLE001 — o quadro não pode derrubar o Telegram
        return {"error": str(e), "claims": {}, "agents": [], "collisions": []}
    agents = live_agents()
    live = {a["name"] for a in agents}
    return {
        "claims": claims,
        "agents": agents,
        "collisions": cols,
        "stale": sorted(n for n in claims if n not in live),
        "bus_updated_at": _bus_updated(),
    }


def _bus_updated() -> str:
    try:
        from jarvis.core.coord import bus_updated_at

        return bus_updated_at()
    except Exception:
        return ""


def pending_for(agent: str) -> list[dict[str, Any]]:
    """O que foi endereçado a um agente (msgs, handoffs, status)."""
    try:
        from jarvis.core.coord import pending

        return pending(agent=agent)
    except Exception:
        return []


def board_text(limit: int = 12) -> str:
    """O quadro em texto (para o Telegram e para o relatório da madrugada)."""
    b = board()
    if b.get("error"):
        return f"quadro indisponível: {b['error']}"
    lines = ["QUADRO DOS AGENTES (fonte: bus de coord)"]
    claims = b.get("claims") or {}
    agents = b.get("agents") or []
    if not claims and not agents:
        return lines[0] + "\n(nenhum agente registrado)"
    def claim_of(a: dict[str, Any]) -> dict[str, Any]:
        # O bus endereça por QUALQUER alias declarado no roster (medido
        # 07/11: 13 nomes para 6 agentes — "jarvis@nitro-v15", "Cervo",
        # "Arara", "sweep-2026-11" são o mesmo agente).
        keys = [a.get("name"), a.get("codename")]
        keys.extend(a.get("aliases") or [])
        for key in keys:
            if key and key in claims:
                return claims[key]
        return {}

    for a in agents[:limit]:
        c = claim_of(a)
        mark = "▸" if c else "•"
        ident_extra = []
        if a.get("origin"):
            ident_extra.append(a.get("origin"))
        if a.get("mbti") or a.get("persona"):
            ident_extra.append(f"{a.get('mbti') or '-'}({a.get('persona') or '-'})")
        extra = f" [{'; '.join(ident_extra)}]" if ident_extra else ""
        lines.append(
            f"{mark} {a.get('codename') or a['name']} [{a.get('lane') or '-'}]{extra}"
            f"{' (ocupado)' if a.get('busy') else ''}"
            f"{(' · ' + a['model']) if a.get('model') else ''}"
            f" — {c.get('intent') or c.get('kind') or 'sem claim'}"
        )
    for name in (b.get("stale") or [])[:6]:
        c = claims.get(name) or {}
        lines.append(f"· {name} (claim de {c.get('age', '?')}h, sem janela viva) — {c.get('intent', '')}")
    cols = b.get("collisions") or []
    for c in cols[:4]:
        lines.append(f"⚠ COLISÃO: {c.get('a')} x {c.get('b')} em {c.get('scope') or c.get('file') or '?'}")
    if b.get("bus_updated_at"):
        lines.append(f"bus atualizado em {b['bus_updated_at']}")
    return "\n".join(lines)


def notify(text: str) -> bool:
    """Manda um texto para o Telegram do dono (via o canal do JARVIS)."""
    try:
        from jarvis.core.config import get_config
        from jarvis.providers.telegram import send_notification

        send_notification(text, get_config())
        return True
    except Exception as e:  # noqa: BLE001
        print(f"comms.notify falhou: {e}", file=sys.stderr)
        return False


# (10/11, sweep-2026-11) O QUE EXIGE ACAO E O QUE E INFORMATIVO.
# Medido: o digest da noite contava tudo que estava endereçado ao agente
# (391 itens para sweep-2026-11, 143 para a coord-naming) e listava os 5
# últimos, que podiam ser todos status de outra lane. Quem recebia abria a
# lista para descobrir que nada era dele. O numero era contabilidade, nao
# fila. O sinal que faltava ja existe: o coord.pending marca `_why`
# ("enderecado" ou "escopo sobreposto").
#
# A SEPARACAO E POR KIND, e nao por palavra do texto: `status` e, por
# convencao da casa, um RELATORIO DE ESTADO (e assim que o dono le), mesmo
# quando endereçado a voce; o evento de bloqueio explicito e o kind
# `blocked`. Medido 10/11: uma heuristica por palavra ("esperando",
# "preciso") classificava 347 dos 393 itens do sweep como acao, porque os
# status longos da lane do celular citam essas palavras em algum ponto.
# Regra por kind: 0 falsos positivos, e o que exige acao e o que foi
# pedido ou transferido.

_BLOQUEIO = ("bloque", "trava", "travado", "esperando", "aguardando",
             "parado", "depende de", "deadlock")

# (10/11) o digest da noite e entregue como msg (o transporte nao tem kind
# proprio), mas o texto comeca com este prefixo e ele e RELATORIO do que
# esta pendente, nao um pedido: sem reconhecer isso, cada noite acrescentava
# um item "acionavel" e a contagem crescia sozinha.
_DIGEST_PREFIX = "[noite]"


def _nomeia_bloqueio(texto: str) -> bool:
    t = str(texto or "").lower()
    return any(k in t for k in _BLOQUEIO)


def classify_pending(pend: list[dict[str, Any]]) -> tuple[list, list]:
    """Separa o que exige acao do que e informativo.

    EXIGE ACAO: msg/done/handoff/blocked endereçados a voce (o que foi
    pedido, transferido ou travado para voce).
    INFORMATIVO: o resto — status (relatorio de estado, por convencao da
    casa), claim e o que entrou por escopo sobreposto.

    Devolve (acao, informativo), preservando a ordem de chegada.
    """
    acao: list[dict[str, Any]] = []
    info: list[dict[str, Any]] = []
    for p in pend or []:
        kind = str(p.get("kind") or "")
        why = str(p.get("_why") or "")
        nota = str(p.get("note") or "")
        if (why == "endereçado"
                and kind in ("msg", "done", "handoff", "blocked")
                and not nota.startswith(_DIGEST_PREFIX)):
            acao.append(p)
        else:
            # (10/11) o proprio digest da noite entra no bus como msg
            # (o transporte nao tem kind proprio e mexer nele e da lane do
            # coord), mas ele e RELATORIO, nao pedido. Sem esta regra cada
            # noite acrescentava um item "acionavel" e a contagem crescia
            # sozinha: medido, 324 dos 393 itens pendentes do sweep eram
            # digests antigos.
            info.append(p)
    return acao, info


# (10/11) quantos itens o digest ENTREGA (a janela). O total do historico
# do bus entra a parte, como numero de contexto, e nao como fila.
DIGEST_WINDOW = 5


def digest_lines(name: str, pend: list[dict[str, Any]],
                 window: int = DIGEST_WINDOW) -> list[str]:
    """As linhas do digest da noite para um agente (funcao pura, testavel).

    A primeira linha e a que importa: da JANELA mostrada, quantos exigem
    ACAO do agente. O total do historico do bus vem a parte, explicito,
    porque sem ele o numero parece fila (medido: 393 "pendentes" do sweep,
    dos quais 5 no digest e zero acionaveis).
    """
    janela = list(pend or [])[-window:]
    acao, info = classify_pending(janela)
    cabecalho = (f"[noite] {len(janela)} item(ns) no digest para {name}: "
                 f"{len(acao)} exige(m) acao")
    if info:
        cabecalho += f", {len(info)} informativo(s)"
    if len(pend or []) > len(janela):
        cabecalho += f" | {len(pend)} no historico do bus"
    linhas = [cabecalho + ":"]
    for p in acao:
        linhas.append(
            f"  - {p.get('kind')} de {p.get('agent')}: "
            f"{(p.get('note') or p.get('intent') or '')[:160]}"
        )
    for p in info:
        linhas.append(
            f"  [info] {p.get('kind')} de {p.get('agent')}: "
            f"{(p.get('note') or p.get('intent') or '')[:120]}"
        )
    return linhas


def night_pass(agent: str = "", *, deliver_notes: bool = True) -> dict[str, Any]:
    """A passada da madrugada: junta o quadro, entrega as pendências e
    reporta ao dono.

    É o que o serviço de madrugada passa a rodar (em vez de trabalhar no
    jogo de teste). Entrega NOTAS (zero token): o agente recebe o resumo
    na sessão e roda quando acordar — ou quando o watcher o acordar.
    """
    report: dict[str, Any] = {"at": time.strftime("%Y-%m-%d %H:%M:%S"), "delivered": [], "pending": {}}
    targets = [agent] if agent else [a["name"] for a in live_agents()]
    for name in targets:
        pend = pending_for(name)
        if not pend:
            continue
        report["pending"][name] = len(pend)
        janela = pend[-DIGEST_WINDOW:]
        acao, info = classify_pending(janela)
        report.setdefault("pending_digest", {})[name] = len(janela)
        report.setdefault("pending_acao", {})[name] = len(acao)
        report.setdefault("pending_informativo", {})[name] = len(info)
        if not deliver_notes:
            continue
        # (10/11) a linha que importa primeiro: quantos exigem acao. O
        # resto vira uma linha de informativo, e a lista mostra os
        # acionaveis (os que o leitor tem de abrir) antes dos outros.
        linhas = digest_lines(name, pend)
        ok, detail = deliver(name, "\n".join(linhas))
        if ok:
            report["delivered"].append(name)
        else:
            report.setdefault("errors", []).append(f"{name}: {detail}")
    try:
        notify(f"[madrugada] quadro dos agentes\n\n{board_text()}")
        report["notified"] = True
    except Exception as e:  # noqa: BLE001
        report["notified"] = False
        report.setdefault("errors", []).append(f"notify: {e}")
    return report
