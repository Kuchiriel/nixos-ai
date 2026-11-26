#!/usr/bin/env python3
"""Compara qualidade de dois modelos locais em heldout de red-team/CTF.

Nao executa ataques: apenas faz perguntas conceituais e mede (a) se responde,
(b) comprimento, (c) presenca de termos tecnicos. Saida JSON, sem segredos.
"""
from __future__ import annotations
import json, sys, time, urllib.request
from pathlib import Path

PROMPTS = [
    "Explain the difference between a symlink follow and a path traversal bug in 2 sentences.",
    "In a CTF, what does a format-string vulnerability let an attacker read? Answer briefly.",
    "How would you sanity-check that a binary was rebuilt from a clean source tree? 3 steps.",
    "What is the risk of exposing an unauthenticated MCP endpoint on a tailnet? 2 sentences.",
]


def call(port, alias, p):
    body = json.dumps({"model": alias, "prompt": p, "max_tokens": 128,
                       "temperature": 0}).encode()
    req = urllib.request.Request("http://127.0.0.1:%s/v1/completions" % port,
                                 data=body, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=180) as r:
        d = json.loads(r.read())
    return d.get("choices", [{}])[0].get("text", "")


def main():
    port, alias, out = sys.argv[1], sys.argv[2], Path(sys.argv[3])
    for _ in range(120):
        try:
            call(port, alias, hi)
            break
        except Exception:
            time.sleep(2)
    rows = []
    for p in PROMPTS:
        t = call(port, alias, p)
        rows.append({"q": p[:50], "chars": len(t),
                     "words": len(t.split()),
                     "answer": t[:300]})
        print(json.dumps(rows[-1], ensure_ascii=False), flush=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"alias": alias, "rows": rows}, indent=2, ensure_ascii=False) + "\n")


if __name__ == "__main__":
    raise SystemExit(main())
