"""coord_roster.py — coordenação LOCAL entre agentes (roster + mensagem + peers).

PAPEL: o bus global (`core/coord.py`) resolve a coordenação ENTRE máquinas
(GitHub + tailnet). Aqui fica a coordenação LOCAL desta máquina: **quem são os
agentes** (codinome + uma frase de contexto que muda quando o contexto muda),
**como entregar mensagem** a um par, e **quem está na tailnet**.

FUNDAÇÃO (não reimplementada — casca fina sobre os CLIs, para que MCP e CLI
nunca divirjam):
  - `scripts/agent-roster.py` — roster: claim, codinome, contexto, set-context,
    whoami. (05/11/2026, dono: "nome humano + uma frase que muda quando o
    contexto muda".)
  - `scripts/agent-msg.sh` — entrega via API do opencode (`--to` = pede turno,
    `--note` = notifica sem rodar).
  - `tailscale status --json` — peers da tailnet.

Por que casca e não cópia: a lógica de claim/colisão já tem dono (o roster) e
duplicá-la cria duas verdades — foi o que a coordination entre lanes já custou
no repo mt5 (307 trades pré-fix vs commitado). Aqui a regra é: **chamar o
dono da verdade**.

CONFIG (env):
  AGENTS_ROSTER  caminho do roster (default: <repo>/.agents/roster.json)
  COORD_AGENT    identidade padrão desta IA (default: jarvis@<host>)
"""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
from pathlib import Path
from typing import Any

DEFAULT_AGENT = "jarvis"


def _repo_root() -> Path:
    """Raiz do repo nixos-ai (sobe até achar scripts/agent-roster.py).

    (14/11, crouton-alpha) BUG CORRIGIDO: o fallback usava
    jarvis.core.paths.find_repo_root(), que resolve o PROJECT ROOT — e o
    walk-up dele achou /home/nixos (tem .git) ou o JARVIS_WORKSPACE_ROOT
    (/home/nixos/projects). Resultado: _script() virava
    /home/nixos/scripts/agent-roster.py (INEXISTENTE) → roster VAZIO e wake
    quebrado em TODO serviço jarvis (Telegram, MCP, heal). Medido: o
    jarvis-telegram via o store nao achava o roster nenhum.
    Agora: se o path resolvido não tem scripts/agent-roster.py, cai no
    fallback ~/projects/nixos-ai (que TEM o script) e, em último caso, no
    repo do proprio source (build local).
    """
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "scripts" / "agent-roster.py").exists():
            return parent
    candidates = []
    try:
        from jarvis.core.paths import find_repo_root
        candidates.append(Path(find_repo_root()))
    except Exception:
        pass
    candidates.append(Path.home() / "projects" / "nixos-ai")
    for cand in candidates:
        if (cand / "scripts" / "agent-roster.py").exists():
            return cand
    return here.parents[6]


def _script(name: str) -> str:
    return str(_repo_root() / "scripts" / name)


def _run(cmd: list[str], timeout: int = 30) -> str:
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    out = (proc.stdout or "").strip()
    err = (proc.stderr or "").strip()
    if proc.returncode != 0:
        raise RuntimeError(err or out or f"{cmd[0]} falhou (rc={proc.returncode})")
    return out


def _session_from_cmdline(pid: int) -> str:
    """Sessão opencode (`-s ses_...`) de um processo, se houver."""
    try:
        argv = Path(f"/proc/{pid}/cmdline").read_bytes().decode(errors="replace")
    except OSError:
        return ""
    parts = [p for p in argv.split("\0") if p]
    for i, part in enumerate(parts):
        if part == "-s" and i + 1 < len(parts):
            return parts[i + 1]
        if part.startswith("ses_"):
            return part
    return ""


def _ppid_of(pid: int) -> int:
    """PPID de um processo (campo 4 de /proc/<pid>/stat)."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(errors="replace")
    except OSError:
        return 0
    # comm pode conter espacos/parenteses -> corta no ULTIMO ')'
    rest = stat.rsplit(")", 1)[-1].split()
    try:
        return int(rest[1])
    except (IndexError, ValueError):
        return 0


def _session_from_ancestors(start: int | None = None, max_up: int = 8) -> str:
    """Sobe a arvore de ppid procurando um opencode com `-s ses_...` no argv.

    Cobre o MCP server de `opencode serve`: ele nao recebe OPENCODE_SESSION_ID
    e o OPENCODE_PID pode estar estale (ou o ancestral direto e o proprio
    `serve`, sem sessao). Sem isso a identidade cai em `jarvis@<host>` e
    whoami/claim vao para o agente errado.
    """
    pid = start if start is not None else os.getpid()
    for _ in range(max_up):
        pid = _ppid_of(pid)
        if pid <= 1:
            break
        ses = _session_from_cmdline(pid)
        if ses:
            return ses
    return ""


def current_session() -> str:
    """Sessão opencode do chamador.

    Medido 08/11: o bash tool recebe OPENCODE_SESSION_ID no env; o MCP server
    NÃO (o app só injeta no shell). Mas o MCP server recebe OPENCODE_PID = o
    processo opencode pai, cujo argv tem `-s ses_...` (a TUI). Sem essa ponte,
    todo MCP caía em `jarvis@<host>` e whoami/pending/set_context iam para o
    agente ERRADO (Arara) — o roster chegou a ter 3 agentes na mesma sessão.

    Ordem: env -> OPENCODE_PID -> arvore de ppid (cobre o MCP de serve, onde
    o PID do env pode estar morto/estale).
    """
    ses = (os.environ.get("OPENCODE_SESSION_ID") or "").strip()
    if ses:
        return ses
    pid = (os.environ.get("OPENCODE_PID") or "").strip()
    if pid.isdigit():
        ses = _session_from_cmdline(int(pid))
        if ses:
            return ses
    return _session_from_ancestors()


def _entry_for_session(session: str) -> dict[str, Any] | None:
    """Entrada do roster da sessão; se houver histórico, o claim mais recente."""
    matches = [e for e in roster_agents() if e.get("session") == session]
    if not matches:
        return None
    return max(matches, key=lambda e: e.get("claimed_at") or 0)


def agent_id() -> str:
    forced = os.environ.get("COORD_AGENT")
    if forced:
        return forced
    ses = current_session()
    if ses:
        entry = _entry_for_session(ses)
        if entry and entry.get("name"):
            return str(entry["name"])
    return f"{DEFAULT_AGENT}@{socket.gethostname().split('.')[0]}"


def roster_agents() -> list[dict[str, Any]]:
    """Agentes do roster (codinome, contexto, lane, estado)."""
    try:
        raw = _run(["python3", _script("agent-roster.py"), "list", "--json"], timeout=20)
    except Exception:
        return []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []
    agents = data.get("agents") if isinstance(data, dict) else data
    return list(agents or [])


def roster_text() -> str:
    """Roster em texto: codinome · nome · origem/modelo/MBTI · lane · estado · contexto."""
    agents = roster_agents()
    if not agents:
        return ("roster vazio (ou agent-roster.py indisponível) — "
                "reivindique com: agent-roster.py claim --name <N> --lane <L>")
    lines = ["roster (codinome · nome · origem/modelo/MBTI · lane · estado · contexto):"]
    for entry in agents:
        ident = []
        if entry.get("origin"):
            ident.append(entry.get("origin"))
        if entry.get("model"):
            ident.append(entry.get("model"))
        if entry.get("mbti") or entry.get("persona"):
            ident.append(f"{entry.get('mbti') or '-'}({entry.get('persona') or '-'})")
        ident_s = " / ".join(ident) if ident else "-"
        lines.append(
            f"- {entry.get('codename') or '-'} · {entry.get('name')} · "
            f"{ident_s} · {entry.get('lane') or '-'} · {entry.get('state') or '?'} · "
            f"{entry.get('context') or '(sem contexto)'}"
        )
    return "\n".join(lines)


def resolve_name(target: str) -> str:
    """Aceita nome OU codinome e devolve o nome do roster."""
    if not target:
        raise ValueError("alvo vazio")
    for entry in roster_agents():
        if entry.get("name") == target or entry.get("codename") == target:
            return str(entry.get("name"))
    raise ValueError(f"'{target}' não está no roster (use o codinome ou o nome)")


def whoami(name: str | None = None) -> str:
    """Cartão de visita: codinome, identidade, lane, repo, escopo e contexto."""
    target = name or agent_id()
    try:
        raw = _run(["python3", _script("agent-roster.py"), "whoami",
                    "--name", target, "--json"], timeout=20)
        entry = json.loads(raw)
    except Exception as exc:
        return f"ERROR: whoami({target}) falhou: {exc}"
    lines = [
        f"{entry.get('codename') or '-'} ({entry.get('name')})",
        f"  origem:    {entry.get('origin') or '-'}",
        f"  modelo:    {entry.get('model') or '-'}",
        f"  persona:   {entry.get('mbti') or '-'}{(' (' + entry.get('persona') + ')') if entry.get('persona') else ''}",
        f"  lane:      {entry.get('lane') or '-'}",
        f"  repo:      {entry.get('repo') or '-'}",
        f"  arquivos:  {', '.join(entry.get('files') or []) or '-'}",
        f"  contexto:  {entry.get('context') or '(vazio)'}",
        f"  sessao:    {entry.get('session') or '-'}",
        f"  estado:    {entry.get('state') or '?'}",
    ]
    return "\n".join(lines)


def set_context(context: str, name: str | None = None) -> str:
    """Atualiza a frase de contexto desta IA (muda quando o contexto muda)."""
    target = name or agent_id()
    if not context.strip():
        return "ERROR: contexto vazio — escreva UMA frase sobre o que você está fazendo"
    return _run(["python3", _script("agent-roster.py"), "set-context",
                 "--name", target, "--context", context.strip()], timeout=20)


def _origin_context() -> str:
    """O pedido original: a tarefa/contexto do AGENTE QUE MANDA.

    (15/11) Medido num video sobre times de modelos: os especialistas
    perdiam o pedido original (recebiam so o resumo do planejador) e o
    time inteiro ficava fraco. Aqui a origem vem do ROSTER do remetente
    (campo `task`, depois `context`) — o que a casa ja guarda.
    """
    try:
        me = agent_id()
    except Exception:
        me = ""
    if not me:
        return ""
    for entry in roster_agents():
        if entry.get("name") != me and entry.get("codename") != me:
            continue
        task = str(entry.get("task") or "").strip()
        if task:
            return task[:700]
        for key in ("context", "note"):
            val = str(entry.get(key) or "").strip()
            if val:
                return val[:700]
        break
    return ""


def send_message(target: str, message: str, note: bool = True) -> str:
    """Entrega mensagem a um par (por codinome ou nome).

    DUAS ETAPAS, e a ordem importa:
    1. **bus primeiro** (kind=msg, to=<codinome>): a mensagem fica gravada,
       cross-machine e auditável — quem está em outra máquina da tailnet
       recebe no próximo poll do watcher;
    2. **wake local** (agent-msg.sh): só o acerto de guarda (a entrega local
       vira *wake*, não o registro).

    Se o wake local falhar, a mensagem continua no bus ⇒ nada se perde.
    """
    if not message.strip():
        return "ERROR: mensagem vazia"
    # O destinatario pode ser (a) do roster LOCAL (da para acordar aqui) ou
    # (b) alguem que so existe no BUS (outra maquina: Termux/Android, o
    # opencode do Windows). O bus e global; a entrega local e um bonus.
    # Bug corrigido em 05/11 (achado pelo Urubu): validar so contra o roster
    # local rejeitava o caso cross-machine - que e exatamente o que o bus
    # existe para resolver.
    # (14/11) Match tolerante: o Telegram manda o codinome como o dono
    # digita ("Falcão" com acento) e o roster guarda "Falcao" (sem acento).
    # Antes: igualdade exata -> o /to caia no bus e nunca acordava ninguem.
    def _norm(x: object) -> str:
        import unicodedata
        return unicodedata.normalize("NFKD", str(x or "")).encode("ascii", "ignore").decode().lower().strip()

    name = target
    codename = target
    needle = _norm(target)
    for entry in roster_agents():
        if (_norm(entry.get("name")) == needle
                or _norm(entry.get("codename")) == needle
                or any(_norm(a) == needle for a in (entry.get("aliases") or []))):
            name = str(entry.get("name"))
            codename = str(entry.get("codename") or "") or name
            break
    lane = lane_of(name)
    bus_note = ""
    try:
        from jarvis.core.coord import send as bus_send
        bus_note = bus_send(to=codename, message=message, lane=lane)
    except Exception as exc:
        bus_note = f"(bus indisponível: {exc})"
    # (14/11) Presença local: casa por NOME **ou CODINOME** (o Telegram manda
    # o codinome — "Falcão" — e o roster guarda name=spiritvale-pivot,
    # codename=Falcao; antes, so name casava e o /to caia no bus).
    local_match = None
    for entry in roster_agents():
        if (_norm(entry.get("name")) == _norm(name)
                or _norm(entry.get("codename")) == _norm(codename)
                or any(_norm(a) == _norm(target) for a in (entry.get("aliases") or []))):
            local_match = entry
            break
    if local_match is None:
        return (f"{bus_note}\n(destinatário '{target}' não está nesta máquina: "
                "a mensagem ficou no bus e será lida no próximo poll do watcher)")
    # nome canonico do registro (para a API e para o agent-msg.sh)
    name = str(local_match.get("name") or name)
    # (14/11, crouton-alpha) ACORDAR PELO PROMPT, NAO PELO BUS.
    # O bug medido: agent-msg.sh decide "vivo" pela JANELA Hyprland
    # (windows --json) — invisivel para servico headless (Telegram, cron,
    # ssh). O /to do Telegram postava no bus e devolvia "sucesso" sem nunca
    # acordar ninguem: a frota silenciava.
    # Ordem nova: (1) API do opencode (agent-api.py) — headless, acorda de
    # verdade; (2) agent-msg.sh (janela viva, com guarda de lane); (3) o bus
    # fica so como REGISTRO cross-machine, nunca como transporte.
    api_note = ""
    session = ""
    try:
        session = _session_of(name)
    except Exception:
        session = ""
    if session:
        payload = message.strip()
        # (15/11, crouton-alpha) O ESPECIALISTA PRECISA VER O PEDIDO ORIGINAL.
        # Medido num video sobre times de modelos (Kimi 4B planejador +
        # especialistas): "Meus especialistas sao so [o que o planejador
        # escreveu]. Eles nunca viram meu pedido original" — e o time ficou
        # fraco. Aqui acontece igual: o par acorda com o RESUMO do remetente e
        # perde o pedido original. Entao quem entrega anexa o contexto
        # original do REMETENTE (a tarefa que ele esta executando).
        _origem = _origin_context()
        if _origem and not note:
            payload = ("[PEDIDO ORIGINAL (contexto do remetente)]: " + _origem
                       + "\n\n[TAREFA PARA VOCE]: " + payload)
            # (15/11) PORT DO LEGADO: o playbook do papel do alvo vai junto.
            # O legado (team/roles/*.md) tinha as regras de conducao; o
            # video de 15/11 mediu que o time falha quando o especialista
            # acorda sem o pedido original e sem as regras do papel.
            try:
                from jarvis.core.playbook import playbook_for_agent
                _alvo = next((a for a in roster_agents()
                              if str(a.get("codename") or "").lower() == str(target).lower()
                              or str(a.get("name") or "").lower() == str(target).lower()
                              or str(target).lower() in [str(x).lower() for x in (a.get("aliases") or [])]),
                             None)
                _play = playbook_for_agent(_alvo) if _alvo else ""
                if _play:
                    payload = ("[PLAYBOOK DO PAPEL (regras de conducao)]\n"
                               + _play + "\n\n" + payload)
            except Exception:
                pass
        cmd_api = ["python3", _script("agent-api.py"), "--session", session,
                   "--text", payload]
        cmd_api.append("--note" if note else "--ask")
        try:
            api_note = _run(cmd_api, timeout=90)
        except Exception as exc:
            api_note = f"(api falhou: {exc})"
    cmd = ["bash", _script("agent-msg.sh"), "--to", name]
    if note:
        cmd.append("--note")
    cmd.append(message.strip())
    try:
        local = _run(cmd, timeout=60)
    except Exception as exc:
        local = f"(wake por janela falhou: {exc})"
    # A API e a verdade: se ela entregou, a mensagem JA acordou o par.
    if api_note and not api_note.startswith("(api falhou"):
        return f"{bus_note}\n(prompt: {api_note})\n(local: {local})"
    return f"{bus_note}\n(local: {local})"



def _session_of(name: str) -> str:
    """Sessao opencode do agente (viva no roster), por nome ou codinome."""
    for entry in roster_agents():
        if entry.get("name") == name or entry.get("codename") == name:
            sess = str(entry.get("session") or "")
            if sess:
                return sess
            pid = entry.get("pid")
            if pid:
                try:
                    return _session_from_cmdline(int(pid))
                except Exception:
                    return ""
    return ""

def codename_of(name: str) -> str:
    """Codinome humano de um agente do roster (vazio se não tiver)."""
    for entry in roster_agents():
        if entry.get("name") == name:
            return str(entry.get("codename") or "")
    return ""


def lane_of(name: str) -> str:
    """Lane de um agente do roster."""
    for entry in roster_agents():
        if entry.get("name") == name:
            return str(entry.get("lane") or "")
    return ""


def peers() -> str:
    """Peers da tailnet (Tailscale) — quem o MCP pode alcançar."""
    binary = shutil.which("tailscale") or "/run/current-system/sw/bin/tailscale"
    try:
        raw = _run([binary, "status", "--json"], timeout=20)
        data = json.loads(raw)
    except Exception as exc:
        return f"ERROR: tailscale indisponível: {exc}"
    entries = []
    if isinstance(data, dict):
        peers_map = data.get("Peer") or data.get("peer") or {}
        self_map = data.get("Self") or data.get("self") or {}
        if self_map:
            entries.append(("SELF", self_map))
        for key, value in (peers_map.items() if isinstance(peers_map, dict) else []):
            entries.append((key, value))
    lines = ["tailnet (peer · IP · OS · estado):"]
    for key, entry in entries:
        if not isinstance(entry, dict):
            continue
        ips = entry.get("TailscaleIPs") or []
        ip = ips[0] if ips else "?"
        online = "online" if entry.get("Online") else "offline"
        lines.append(f"- {entry.get('HostName') or key} · {ip} · "
                     f"{entry.get('OS') or '?'} · {online}")
    return "\n".join(lines)
