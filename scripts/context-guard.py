#!/usr/bin/env python3
"""context-guard — troca modelo/key ANTES do limite (contexto ou cota).

Sinais lidos (sem palpite):
  1) ultima mensagem assistant no DB: tokens.input + tokens.cache.read
  2) limite do modelo (catalogo local; nvidia/minimax = 1048576 medido)
  3) 429/FreeUsageLimit no log do opencode nos ultimos 30 min

Acao (so com --apply, e so em sessao IDLE):
  - key-rotate.py next --provider <provider>
  - agent-model.py --run <sid> "troca automatica, retome sem repetir"
  - publica 1 linha no bus (sem segredo)

Uso: context-guard.py [--dry-run|--apply] [--threshold 0.80]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import time
import urllib.request
from pathlib import Path

DB = "/home/nixos/.local/share/opencode/opencode.db"
LOG = Path.home() / ".local/share/opencode/log/opencode.log"
HOME = Path.home()
LIMITS = {
    "minimaxai/minimax-m3.1-flash": 1_048_576,
    "nemotron-3-ultra-550b-a55b": 1_048_576,
}
DEFAULT_LIMIT = 200_000


def active_sessions():
    env = (HOME / ".config/opencode/server.env").read_text()
    pw = [l.split("=", 1)[1].strip().strip("\"'")
          for l in env.splitlines() if l.startswith("OPENCODE_SERVER_PASSWORD=")][0]
    import base64
    h = {"Authorization": "Basic " + base64.b64encode(f"opencode:{pw}".encode()).decode()}
    try:
        d = json.load(urllib.request.urlopen(
            urllib.request.Request(os.environ.get("AGENTS_OC_URL","http://127.0.0.1:4599")+"/api/session", headers=h), timeout=15))
        return [(s.get("id"), (s.get("model") or {})) for s in (d.get("data") or [])]
    except Exception:
        return []


def idle_sessions():
    try:
        raw = urllib.request.urlopen("http://127.0.0.1:8091/api/agents", timeout=10).read()
        d = json.loads(raw)
        return {a.get("session") for a in d.get("agents", []) if a.get("status") == "idle"}
    except Exception:
        return set()


def last_tokens(sid):
    c = sqlite3.connect(f"file:{DB}?mode=ro", uri=True, timeout=10)
    try:
        r = c.execute("select data from session_message where type='assistant' "
                      "and session_id=? order by time_created desc limit 1", (sid,)).fetchone()
    finally:
        c.close()
    if not r:
        return 0
    try:
        d = json.loads(r[0]) if isinstance(r[0], str) else r[0]
        t = d.get("tokens") or {}
        return int(t.get("input") or 0) + int((t.get("cache") or {}).get("read") or 0)
    except Exception:
        return 0


def recent_429(window_s=1800):
    if not LOG.is_file():
        return 0
    cutoff = time.time() * 1000 - window_s * 1000
    n = 0
    try:
        for line in LOG.read_text(errors="replace").splitlines()[-4000:]:
            if ("429" in line or "FreeUsageLimit" in line or "rate-limit" in line) and "timestamp" in line:
                m = re.search(r"timestamp=(\d+)", line)
                if m and int(m.group(1)) >= cutoff:
                    n += 1
    except Exception:
        pass
    return n


def bus_post(msg):
    ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    body = ("**status** de `context-guard` na lane `host/frota` → todos\n\n```coord-json\n"
            + json.dumps({"kind": "status", "agent": "context-guard", "to": "",
                          "lane": "host/frota", "files": [], "intent": msg,
                          "note": msg, "pr": None, "head": "", "ts": ts},
                         ensure_ascii=False) + "\n```\n")
    p = Path("/home/nixos/tmp-patch/context-guard-bus.txt")
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body, encoding="utf-8")
    try:
        subprocess.run(["gh", "api", "repos/Kuchiriel/mt5/issues/12/comments",
                        "-F", f"body=@{p}"], capture_output=True, timeout=60)
    except Exception:
        pass


def main():
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--dry-run", action="store_true")
    g.add_argument("--apply", action="store_true")
    ap.add_argument("--threshold", type=float, default=0.80)
    a = ap.parse_args()

    idles = idle_sessions()
    erros = recent_429()
    print(f"429/FreeUsage limitados (30 min): {erros}")
    acoes = 0
    for sid, model in active_sessions():
        mid = model.get("id") or ""
        prov = model.get("providerID") or "nvidia"
        used = last_tokens(sid or "")
        lim = next((v for k, v in LIMITS.items() if k in mid), DEFAULT_LIMIT)
        pct = used / lim if lim else 0
        flag_ctx = pct >= a.threshold
        flag_quota = erros >= 2
        if not (flag_ctx or flag_quota):
            continue
        idle = sid in idles
        print(f"{str(sid)[:18]:18} {mid[:36]:36} ctx={used}/{lim} ({pct:.0%}) "
              f"429={erros} idle={idle} -> {'TROCAR' if idle else 'NAO (ocupada)'}")
        if not (idle and a.apply):
            continue
        # 1) rotaciona key do provider (pode ser no-op se so houver 1)
        subprocess.run(["python3", str(HOME / "projects/nixos-ai/scripts/key-rotate.py"),
                        "next", "--provider", prov], capture_output=True, timeout=60)
        # 2) troca o modelo da sessao com um turno curto (caminho que funciona na 2.2.6)
        msg = ("[context-guard] Contexto/cota no limite. Troquei a credencial ativa; "
               "retome a tarefa em andamento no modelo disponível, NAO repita o que ja foi feito.")
        subprocess.run(["python3", str(HOME / "projects/nixos-ai/scripts/agent-model.py"),
                        "--run", sid, msg, "--max-tries", "1"],
                       capture_output=True, timeout=420)
        bus_post(f"context-guard trocou key/modelo de {str(sid)[:18]} "
                 f"(ctx {pct:.0%}, 429={erros}); retomada sem repetir trabalho")
        acoes += 1
    print(f"acoes: {acoes}" + (" (dry-run)" if a.dry_run or not a.apply else ""))


if __name__ == "__main__":
    main()
