#!/usr/bin/env python3
"""
fleet-dispatch — fecha o loop da frota no host.

Pega a próxima tarefa da fila frota (DISCOVERED/READY), escolhe um agente
IDLE do hub (:8091) ou do roster, manda um wake steer e faz claim do item.
Se não houver tarefa pendente ou nenhum agente idle, sai limpo.

Modelado no bin/fleet-dispatch do termux, adaptado para as ferramentas do host:
  - task_queue (nightwatch.TaskQueue) para fila + claim
  - hub :8091 /api/agents para encontrar agentes idle
  - agent-msg.sh para entregar o wake
  - coord_post para publicar no bus

Uso:
  scripts/fleet-dispatch          # próximo da fila frota
  scripts/fleet-dispatch --projeto frota  # projeto específico
  scripts/fleet-dispatch --dry-run   # só mostra o que faria
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import urllib.request
from pathlib import Path

REPO = Path(os.environ.get("JARVIS_REPO", "/home/nixos/projects/nixos-ai"))
SRC = REPO / "modules" / "ai" / "jarvis" / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

sys.path.insert(0, str(REPO / "scripts"))
from agent_config import cfg as _agent_cfg  # noqa: E402

HUB_URL = _agent_cfg().url("agent_hub")
AGENT_MSG = str(REPO / "scripts" / "agent-msg.sh")
LOG = Path.home() / ".local" / "state" / "jarvis" / "fleet-dispatch.log"


def say(msg: str) -> None:
    LOG.parent.mkdir(parents=True, exist_ok=True)
    with open(LOG, "a") as fh:
        fh.write(f"{msg}\n")


def hub_agents() -> list[dict]:
    """Lista agentes do hub (:8091 /api/agents)."""
    try:
        req = urllib.request.Request(
            f"{HUB_URL}/api/agents",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            d = json.loads(r.read() or b"{}")
        return d.get("agents", []) if isinstance(d, dict) else []
    except Exception as exc:
        say(f"ERRO: hub :8091 indisponível ({exc})")
        return []


def agente_idle() -> dict | None:
    """Escolhe um agente IDLE (não spawn) do hub."""
    for a in hub_agents():
        cod = str(a.get("codename") or "")
        if a.get("status") == "idle" and not cod.startswith("spawn"):
            return a
    return None


def wake(agente: dict, texto: str) -> str:
    """Manda wake steer para o agente via agent-msg.sh."""
    nome = str(agente.get("name") or agente.get("codename") or "")
    if not nome:
        return "ERRO: agente sem nome"
    cmd = ["bash", AGENT_MSG, "--to", nome, "--note", texto]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
        return p.stdout.strip() or p.stderr.strip()
    except Exception as exc:
        return f"ERRO: wake falhou ({exc})"


def proximo_item(projeto: str = "frota") -> dict | None:
    """Próximo work item DISCOVERED/READY do projeto."""
    from nightwatch.task_queue import TaskQueue
    q = TaskQueue(project=projeto)
    for t in q.get_all_tasks():
        if t.status in ("DISCOVERED", "READY"):
            return {"id": t.id, "descricao": t.description or "(sem descrição)"}
    return None


def claim(item_id: str, agente: str, projeto: str = "frota") -> str:
    """Faz claim do item para o agente."""
    from nightwatch.task_queue import TaskQueue
    q = TaskQueue(project=projeto)
    try:
        q.update_task(item_id, status="IN_PROGRESS")
        say(f"claim: item={item_id} agente={agente} status=IN_PROGRESS")
        return "ok"
    except Exception as exc:
        return f"ERRO: claim falhou ({exc})"


def publicar_bus(item_id: str, descricao: str, agente: str) -> None:
    """Publica no bus (issue #12) que o item foi pego."""
    cli = str(REPO / "scripts" / "jarvis-cli.sh")
    texto = (
        f"ID:{item_id} FILA DA FROTA — {descricao}. "
        f"Agente: {agente}. "
        f"Ao terminar: coord_workitem action=done item_id={item_id} project={projeto} "
        f"e rode: {REPO}/scripts/fleet-dispatch"
    )
    payload = json.dumps({"kind": "status", "agent": "fleet-dispatch", "lane": "frota", "note": texto})
    try:
        subprocess.run(
            ["bash", cli, "tool", "coord_post", payload],
            capture_output=True, text=True, timeout=30,
        )
    except Exception:
        pass  # best-effort: o bus não pode travar o dispatch


def main() -> int:
    projeto = "frota"
    dry_run = "--dry-run" in sys.argv
    for a in sys.argv[1:]:
        if a.startswith("--projeto="):
            projeto = a.split("=", 1)[1]

    item = proximo_item(projeto)
    if not item:
        print(f"(fila {projeto} vazia — sem tarefas DISCOVERED/READY)")
        say(f"fila {projeto} vazia")
        return 0

    iid = item["id"]
    desc = item["descricao"]
    print(f"item={iid} descricao={desc[:60]}")

    ag = agente_idle()
    if not ag:
        print("(nenhum agente idle disponível no hub :8091)")
        say(f"item={iid} sem agente idle")
        return 0

    cod = str(ag.get("codename") or ag.get("name") or "?")
    print(f"agente escolhido: {cod} (lane={ag.get('lane')})")

    if dry_run:
        print(f"[dry-run] acordaria {cod} com o item {iid}")
        say(f"[dry-run] item={iid} agente={cod}")
        return 0

    tarefa = (
        f"ID:{iid} FILA DA FROTA — {desc}. "
        f"ACEITE: artefato commitado no repo canônico + 1 linha no bus (issue #12). "
        f"Ao terminar, marque o item done "
        f"(coord_workitem action=done item_id={iid} project={projeto}) "
        f"e rode: {REPO}/scripts/fleet-dispatch — para acordar o próximo agente. "
        f"Não responda só 'feito': entregue."
    )

    out = wake(ag, tarefa)
    print(f"wake: {out[:120]}")

    cl = claim(iid, cod, projeto)
    print(f"claim: {cl}")

    publicar_bus(iid, desc, cod)
    say(f"item={iid} agente={cod} :: {desc[:50]} :: wake={out[:40]} claim={cl}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
