"""Make.com via API como tool MCP (Automancerz prospecção).

Read: list/get cenários, logs, detalhe. Write (run) exige
confirm=true explícito (nunca disparo acidental).
Credenciais: MAKE_API_KEY + MAKE_ZONE (env).
"""
from __future__ import annotations

import json
import os
import urllib.request
import urllib.error


def _api(method: str, path: str, body: dict | None = None) -> dict:
    key = os.environ.get("MAKE_API_KEY", "")
    zone = os.environ.get("MAKE_ZONE", "us2.make.com")
    if not key:
        return {"error": "MAKE_API_KEY ausente no env"}
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"https://{zone}/api/v2/{path}", data=data,
        headers={"Authorization": f"Token {key}",
                 "Content-Type": "application/json"},
        method=method)
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return {"ok": True, "data": json.loads(r.read().decode() or "{}")}
    except urllib.error.HTTPError as e:
        return {"error": f"HTTP {e.code}: {e.read().decode()[:200]}"}
    except Exception as e:
        return {"error": str(e)[:200]}


def _summarize_scenarios(payload) -> str:
    if isinstance(payload, list):
        items = payload
    elif isinstance(payload, dict):
        items = payload.get("scenarios", [])
    else:
        items = []
    lines = [f"{s.get('id')} | {s.get('name')} | "
             f"{'ATIVO' if s.get('isActive') else 'inativo'}"
             for s in items]
    return "\n".join(lines) or "(nenhum cenário)"


MAKE_TOOLS = [
    {
        "name": "jarvis_make_scenarios",
        "description": "List Make scenarios (id, name, active). Team 750102 default.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "team_id": {"type": "integer", "description": "Team ID (default 750102)"}
            },
        },
    },
    {
        "name": "jarvis_make_scenario_get",
        "description": "Get scenario blueprint summary (modules, schedule, validity).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scenario_id": {"type": "integer", "description": "Scenario ID"}
            },
            "required": ["scenario_id"],
        },
    },
    {
        "name": "jarvis_make_executions",
        "description": "List recent executions of a scenario (id, status).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scenario_id": {"type": "integer", "description": "Scenario ID"}
            },
            "required": ["scenario_id"],
        },
    },
    {
        "name": "jarvis_make_run",
        "description": "RUN a scenario (costs ops). Requires confirm=true.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "scenario_id": {"type": "integer", "description": "Scenario ID"},
                "confirm": {"type": "boolean", "description": "Must be true"},
            },
            "required": ["scenario_id", "confirm"],
        },
    },
]


def handle_make(name: str, args: dict) -> str:
    """Despacha tools jarvis_make_*."""
    if name == "jarvis_make_scenarios":
        tid = args.get("team_id", 750102)
        r = _api("GET", f"scenarios?teamId={tid}")
        if "error" in r:
            return f"ERROR: {r['error']}"
        return _summarize_scenarios(r["data"])
    if name == "jarvis_make_scenario_get":
        sid = args.get("scenario_id")
        r = _api("GET", f"scenarios/{sid}")
        if "error" in r:
            return f"ERROR: {r['error']}"
        d = r["data"]
        mods = [n.get("module", "?")
                for n in d.get("blueprint", {}).get("flow", [])]
        return (f"{d.get('name')} | ativo={d.get('isActive')} "
                f"invalid={d.get('isinvalid')} sched={d.get('scheduling')} "
                f"next={d.get('nextExec')}\nmódulos: {' → '.join(mods)}")
    if name == "jarvis_make_executions":
        sid = args.get("scenario_id")
        r = _api("GET", f"scenarios/{sid}/executions")
        if "error" in r:
            return f"ERROR: {r['error']}"
        xs = r["data"] if isinstance(r["data"], list) else r["data"].get("executions", [])
        return "\n".join(
            f"{x.get('id')} | status={x.get('status')}" for x in xs[:5]) or "(sem runs)"
    if name == "jarvis_make_run":
        if args.get("confirm") is not True:
            return "ERROR: passe confirm=true para executar (consome operações)"
        sid = args.get("scenario_id")
        r = _api("POST", f"scenarios/{sid}/run", {})
        if "error" in r:
            return f"ERROR: {r['error']}"
        return json.dumps(r["data"])[:500]
    return f"ERROR: unknown make tool {name}"
