#!/usr/bin/env python3
"""bus-tail.py — as ultimas mensagens coord-json do bus, em JSON.

(15/11, crouton-alpha) O hub (node) nao consegue executar o `gh` (SIGTERM
imediatio: o binario do nixpkgs morre quando o node o execa), entao a
leitura do bus foi para ca: este script, em python, usa o mesmo `gh` que a
casa usa (funciona) e devolve JSON.

uso: bus-tail.py [limite]
saida: {"items":[{ts,from,to,kind,text,lane}...]}
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import sys

ISSUE = "Kuchiriel/mt5"
GH = os.environ.get("GH_BIN", "gh")


def main() -> int:
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else 40
    try:
        r = subprocess.run(
            [GH, "api", f"repos/{ISSUE}/issues/12/comments?per_page=60", "-q", ".[].body"],
            capture_output=True, text=True, timeout=90)
    except Exception as exc:  # noqa: BLE001
        print(json.dumps({"items": [], "err": f"gh falhou: {exc}"[:200]}))
        return 0
    if r.returncode != 0:
        print(json.dumps({"items": [], "err": (r.stderr or "gh falhou")[:200]}))
        return 0
    out = []
    for body in (r.stdout or "").split("```coord-json\n")[1:]:
        raw = body.split("```")[0]
        try:
            j = json.loads(raw)
        except Exception:
            continue
        if not isinstance(j, dict):
            continue
        out.append({
            "ts": str(j.get("ts") or "")[:19].replace("T", " "),
            "from": j.get("agent") or j.get("from") or "?",
            "to": j.get("to") or "-",
            "kind": j.get("kind") or "msg",
            "lane": j.get("lane") or "",
            "text": re.sub(r"\s+", " ", str(j.get("message") or j.get("intent") or j.get("note") or ""))[:400],
        })
    print(json.dumps({"items": out[-limit:]}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
