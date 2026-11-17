#!/usr/bin/env python3
"""key-rotate — troca a credencial ATIVA de um provider no OpenCode (sem expor valor).

Por que existe (17/11): o dono vai usar varias keys para contornar cota/tier
limit. A frota precisa de UM mecanismo unico, agnóstico e chamavel por API,
para trocar a key ativa SEM escrever segredo em repo/bus/log/clipboard.

Fonte de verdade: tabela `credential` do opencode.db (integration_id, active).
Nenhuma funcao deste arquivo imprime `value` (a chave fica só no DB do host).

Uso:
  key-rotate.py list                       # ids/labels/active, SEM valores
  key-rotate.py next --provider nvidia     # rotaciona round-robin
  key-rotate.py status --provider nvidia
  key-rotate.py verify --provider nvidia   # HTTP curto no endpoint do provider

A rotação grava no bus (issue #12) apenas o label e o provider — nunca a key.
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sqlite3
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

DB = os.environ.get(
    "OPENCODE_DB", "/home/nixos/.local/share/opencode/opencode.db")
BUS_REPO = "Kuchiriel/mt5"
BUS_ISSUE = 12


def con(write: bool = False):
    if not write:
        return sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    return sqlite3.connect(DB, timeout=10)


def rows(provider: str):
    c = con()
    try:
        return list(c.execute(
            "select id,label,active,time_created,time_updated "
            "from credential where integration_id=? order by time_created",
            (provider,)))
    finally:
        c.close()


def active_row(provider: str):
    for r in rows(provider):
        if r[2]:
            return r
    return None


def cmd_list(a) -> int:
    for p in ([a.provider] if a.provider else sorted(
            {r[0] for r in con().execute(
                "select distinct integration_id from credential")})):
        rs = rows(p)
        print(f"=== {p} ({len(rs)} credenciais)")
        for i, r in enumerate(rs, 1):
            print(f"  {i}. {r[0][:28]}  label={r[1]!r}  active={r[2]}  "
                  f"criada={dt.datetime.fromtimestamp(r[3]/1000).isoformat(timespec='seconds')}")
    return 0


def cmd_status(a) -> int:
    r = active_row(a.provider)
    print(json.dumps({"provider": a.provider,
                      "active_id": r[0] if r else None,
                      "label": r[1] if r else None}, ensure_ascii=False))
    return 0


def bus_post(text: str) -> None:
    ts = dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds")
    body = (
        f"**status** de `key-rotate` na lane `host/frota` → todos\n\n"
        "```coord-json\n"
        + json.dumps({"kind": "status", "agent": "key-rotate", "to": "",
                      "lane": "host/frota", "files": [], "intent": text,
                      "note": text, "pr": None, "head": "", "ts": ts},
                     ensure_ascii=False)
        + "\n```\n"
    )
    tmp = Path("/home/nixos/tmp-patch/key-rotate-bus.txt")
    tmp.parent.mkdir(parents=True, exist_ok=True)
    tmp.write_text(body, encoding="utf-8")
    try:
        subprocess.run(["gh", "api", f"repos/{BUS_REPO}/issues/{BUS_ISSUE}/comments",
                        "-F", f"body=@{tmp}"], capture_output=True, timeout=60)
    except Exception:
        pass


def cmd_next(a) -> int:
    rs = rows(a.provider)
    if len(rs) < 2:
        print(f"key-rotate: {a.provider} tem {len(rs)} credencial(is) — nada a rotacionar",
              file=sys.stderr)
        return 1
    cur = active_row(a.provider)
    ids = [r[0] for r in rs]
    pos = ids.index(cur[0]) if cur else -1
    nxt = rs[(pos + 1) % len(rs)]
    if a.dry_run:
        print(f"dry-run: {cur[1] if cur else '(nenhuma)'} -> {nxt[1]} ({nxt[0][:20]})")
        return 0
    c = con(write=True)
    try:
        now = int(time.time() * 1000)
        c.execute("update credential set active=0,time_updated=? where integration_id=?",
                  (now, a.provider))
        c.execute("update credential set active=1,time_updated=? where id=?",
                  (now, nxt[0]))
        c.commit()
    finally:
        c.close()
    msg = (f"credencial rotacionada: provider={a.provider} "
           f"de={cur[1] if cur else 'nenhuma'} para={nxt[1]} "
           f"(id={nxt[0][:16]}); valor NUNCA sai do DB do host")
    print(msg)
    if not a.no_bus:
        bus_post(msg)
    return 0


def cmd_verify(a) -> int:
    r = active_row(a.provider)
    if not r:
        print("sem credencial ativa", file=sys.stderr)
        return 1
    c = con()
    try:
        val = c.execute("select value from credential where id=?", (r[0],)).fetchone()[0]
    finally:
        c.close()
    key = ""
    try:
        key = json.loads(val).get("key", "")
    except Exception:
        pass
    if not key:
        print("credencial ativa sem campo key", file=sys.stderr)
        return 1
    url = {
        "nvidia": "https://integrate.api.nvidia.com/v1/models",
        "groq": "https://api.groq.com/openai/v1/models",
        "openrouter": "https://openrouter.ai/api/v1/models",
    }.get(a.provider, "")
    if not url:
        print(f"verify: sem endpoint conhecido para {a.provider}; checagem local OK", )
        return 0
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"})
    t0 = time.time()
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            print(f"verify {a.provider}: HTTP {resp.status} em {time.time()-t0:.2f}s "
                  f"(label={r[1]})")
            return 0
    except Exception as exc:
        print(f"verify {a.provider}: FALHOU em {time.time()-t0:.2f}s "
              f"({type(exc).__name__}) label={r[1]}")
        return 2


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("cmd", choices=["list", "next", "status", "verify"])
    p.add_argument("--provider", default="nvidia")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--no-bus", action="store_true")
    a = p.parse_args()
    return {"list": cmd_list, "next": cmd_next,
            "status": cmd_status, "verify": cmd_verify}[a.cmd](a)


if __name__ == "__main__":
    sys.exit(main())
