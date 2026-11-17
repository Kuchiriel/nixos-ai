#!/usr/bin/env python3
"""wake-fix-inbox — promove itens pendentes do inbox para delivery=steer.

Descoberto 17/11 com a API V2 (OpenAPI /docs/openapi.json):
  POST /api/session/{id}/prompt  -> "durably admit ... and schedule execution
                                     unless resume is false"
  PATCH /api/session/{id}/inbox/{inboxID} {"delivery":"steer"}
                                 -> "Steering wakes session execution"

Na pratica o POST com delivery=steer gravou o item como QUEUE no inbox e a
sessao ficou `running` sem executar. O PATCH e' o que acorda de verdade.

Uso: wake-fix-inbox [--agent CODINOME] [--dry-run]
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import sys
import urllib.request
from pathlib import Path

HOME = Path.home()
BASE = os.environ.get("AGENTS_OC_URL", "http://100.121.100.103:4599")
ENVFILE = HOME / ".config/opencode/server.env"
ROSTER = HOME / "projects/.agents/roster.json"


def auth() -> dict[str, str]:
    pw = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
    if not pw and ENVFILE.is_file():
        for line in ENVFILE.read_text().splitlines():
            if line.startswith("OPENCODE_SERVER_PASSWORD="):
                pw = line.split("=", 1)[1].strip().strip("\"'")
                break
    user = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
    token = base64.b64encode(f"{user}:{pw}".encode()).decode()
    return {"Authorization": f"Basic {token}", "Content-Type": "application/json"}


def req(path: str, method: str = "GET", body: dict | None = None):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(BASE + path, data=data, method=method, headers=auth())
    with urllib.request.urlopen(r, timeout=15) as resp:
        raw = resp.read().decode()
        return resp.status, (json.loads(raw) if raw else {})


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    roster = json.loads(ROSTER.read_text(encoding="utf-8"))
    itens = roster if isinstance(roster, list) else (roster.get("agents") or roster.get("roster") or [])
    vistos: set[str] = set()
    total = 0
    for it in itens:
        if not isinstance(it, dict):
            continue
        cod = str(it.get("codename") or it.get("name") or "")
        sid = str(it.get("session") or "")
        if a.agent and a.agent.lower() not in (cod.lower(), str(it.get("name", "")).lower()):
            continue
        if not sid or sid in vistos:
            continue
        vistos.add(sid)
        try:
            _, d = req(f"/api/session/{sid}/inbox")
        except Exception as exc:
            print(f"{cod}: inbox erro {str(exc)[:70]}")
            continue
        msgs = d.get("data") or []
        pend = [m for m in msgs if m.get("delivery") == "queue"]
        print(f"{cod}: {len(msgs)} no inbox, {len(pend)} em queue")
        for m in pend:
            iid = m.get("id")
            if not iid:
                continue
            if a.dry_run:
                continue
            try:
                st, _ = req(f"/api/session/{sid}/inbox/{iid}", "PATCH", {"delivery": "steer"})
                print(f"  steer {iid} -> HTTP {st}")
                total += 1
            except Exception as exc:
                print(f"  steer {iid} ERRO {str(exc)[:70]}")
    print(f"total promovidos: {total}" + (" (dry-run)" if a.dry_run else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
