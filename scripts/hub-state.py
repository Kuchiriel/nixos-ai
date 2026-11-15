#!/usr/bin/env python3
"""hub-state.py — o estado CONSOLIDADO da casa, num JSON so.

(15/11, crouton-alpha) O dono pediu "liga tudo": agentes, claims, fila,
kanban, spawns, modelos, rate-limit, servicos — tudo junto, e sem duplicar
o que a casa ja tem. Este script apenas AGREGA o que ja existe:

  agentes  -> agent-roster.py list --json      (fonte unica do roster)
  claims   -> comms.board()                   (bus + claims + colisoes)
  fila     -> ~/projects/AGENTS-QUEUE.md (topo: o estado real de hoje)
  kanban   -> jarvis workitem --list/--burndown (nightwatch.task_queue)
  spawns   -> ~/.local/state/jarvis/spawns/*.json (o que o hub criou)
  modelos  -> scripts/model-catalog.py        (catalogo real + rate-limit)
  servicos -> systemctl --user (o que esta de pe)

saida: JSON (--pretty para humano)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
REPO = HOME / "projects/nixos-ai"
SRC = REPO / "modules/ai/jarvis/src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


def run(cmd: list, timeout: int = 60) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, cwd=str(REPO))
        return (p.stdout or p.stderr or "").strip()
    except Exception as exc:  # noqa: BLE001
        return f"erro: {exc}"


def roster() -> list:
    out = run(["python3", str(REPO / "scripts/agent-roster.py"), "list", "--json"], 40)
    try:
        d = json.loads(out)
        return d.get("agents") if isinstance(d, dict) else d
    except Exception:
        return []


def board() -> dict:
    """Claims/colisoes do bus — SEM releer o GitHub aqui.

    (15/11) Ler o bus aqui custava ~20s (gh) e DUPLICAVA o /api/bus do
    hub. Agora o estado usa so o roster local (rapido) e a conversa vem
    do /api/bus, que e a fonte unica.
    """
    try:
        from jarvis.core.comms import live_agents
        return {
            "agentes_vivos": [a.get("codename") or a.get("name") for a in (live_agents() or [])],
            "claims": "ver /api/bus (fonte unica do bus)",
        }
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def queue_top(n: int = 12) -> list:
    p = HOME / "projects/AGENTS-QUEUE.md"
    try:
        lines = [l.rstrip() for l in p.read_text(errors="ignore").splitlines()[:n] if l.strip()]
        return lines
    except Exception:
        return []


def workitems() -> dict:
    # o jarvis-cli.sh e BASH e usa o env da casa (jarvis-env.sh): chamar com
    # python3 quebrava (SyntaxError) e devolvia vazio.
    cli = str(REPO / "scripts/jarvis-cli.sh")
    out = run(["bash", cli, "workitem", "--list"], 45)
    burn = run(["bash", cli, "workitem", "--burndown"], 45)
    return {"lista": out[:1200], "burndown": burn[:800]}


def spawns() -> list:
    out = []
    d = HOME / ".local/state/jarvis/spawns"
    try:
        for f in sorted(d.glob("*.json"))[-10:]:
            try:
                out.append(json.loads(f.read_text()))
            except Exception:
                pass
    except Exception:
        pass
    return out


def services() -> dict:
    out = run(["systemctl", "--user", "list-units", "--type=service", "--no-pager", "--plain"], 30)
    rows = {}
    for line in out.splitlines():
        parts = line.split()
        if len(parts) >= 4 and parts[0].endswith(".service"):
            rows[parts[0][:-8]] = parts[2]
    return rows


def models() -> dict:
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("mc", REPO / "scripts/model-catalog.py")
        m = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(m)
        return m.build()
    except Exception as exc:  # noqa: BLE001
        return {"error": str(exc)}


def build() -> dict:
    return {
        "ts": int(__import__("time").time()),
        "agentes": roster(),
        "board": board(),
        "fila": queue_top(),
        "kanban": workitems(),
        "spawns": spawns(),
        "servicos": services(),
        "modelos": models(),
    }


def main() -> int:
    data = build()
    if "--pretty" in sys.argv:
        print(f"agentes: {len(data['agentes'])} | claims: {len(data['board'].get('claims', []))} "
              f"| spawns: {len(data['spawns'])} | servicos: {len(data['servicos'])}")
        for a in data["agentes"][:8]:
            print(f"  {a.get('codename','?'):10s} {a.get('state','?'):6s} {str(a.get('lane'))[:26]:26s} {str(a.get('session'))[:22]}")
        print("servicos:")
        for k, v in list(data["servicos"].items())[:12]:
            print(f"  {k:34s} {v}")
    else:
        print(json.dumps(data, ensure_ascii=False, default=str))
    return 0


if __name__ == "__main__":
    sys.exit(main())
