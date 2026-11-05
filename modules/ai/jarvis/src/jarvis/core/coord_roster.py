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
    """Raiz do repo nixos-ai (sobe até achar scripts/agent-roster.py)."""
    here = Path(__file__).resolve()
    for parent in here.parents:
        if (parent / "scripts" / "agent-roster.py").exists():
            return parent
    try:
        from jarvis.core.paths import find_repo_root
        return Path(find_repo_root())
    except Exception:
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


def agent_id() -> str:
    forced = os.environ.get("COORD_AGENT")
    if forced:
        return forced
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
    """Roster em texto: codinome · nome · lane · contexto · estado."""
    agents = roster_agents()
    if not agents:
        return ("roster vazio (ou agent-roster.py indisponível) — "
                "reivindique com: agent-roster.py claim --name <N> --lane <L>")
    lines = ["roster (codinome · nome · lane · estado · contexto):"]
    for entry in agents:
        lines.append(
            f"- {entry.get('codename') or '-'} · {entry.get('name')} · "
            f"{entry.get('lane') or '-'} · {entry.get('state') or '?'} · "
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
    """Cartão de visita: codinome, lane, repo, escopo e contexto."""
    target = name or agent_id()
    try:
        raw = _run(["python3", _script("agent-roster.py"), "whoami",
                    "--name", target, "--json"], timeout=20)
        entry = json.loads(raw)
    except Exception as exc:
        return f"ERROR: whoami({target}) falhou: {exc}"
    return "\n".join([
        f"{entry.get('codename') or '-'} ({entry.get('name')})",
        f"  lane:      {entry.get('lane') or '-'}",
        f"  repo:      {entry.get('repo') or '-'}",
        f"  arquivos:  {', '.join(entry.get('files') or []) or '-'}",
        f"  contexto:  {entry.get('context') or '(vazio)'}",
        f"  sessao:    {entry.get('session') or '-'}",
        f"  estado:    {entry.get('state') or '?'}",
    ])


def set_context(context: str, name: str | None = None) -> str:
    """Atualiza a frase de contexto desta IA (muda quando o contexto muda)."""
    target = name or agent_id()
    if not context.strip():
        return "ERROR: contexto vazio — escreva UMA frase sobre o que você está fazendo"
    return _run(["python3", _script("agent-roster.py"), "set-context",
                 "--name", target, "--context", context.strip()], timeout=20)


def send_message(target: str, message: str, note: bool = True) -> str:
    """Entrega mensagem a um par (por codinome ou nome). `--note` não roda o turno."""
    if not message.strip():
        return "ERROR: mensagem vazia"
    name = resolve_name(target)
    cmd = ["bash", _script("agent-msg.sh"), "--to", name]
    if note:
        cmd.append("--note")
    cmd.append(message.strip())
    return _run(cmd, timeout=60)


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
