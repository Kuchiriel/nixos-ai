#!/usr/bin/env python3
"""fleet-model-route — assign models BY TASK CLASS, not one default to all agents.

Why (measured 19/11): all 6 roster agents were on 2 models (4x minimax default,
2x nemotron-ultra) despite a 35-model matrix showing different latency/rate-limit
profiles. The default minimax gives 429/15s timeout at 4 parallel calls, while
gemma-4-31b-it and nemotron-nano answer 200 and don't degrade under concurrency.

Decision table (from docs/PROVIDER-HEALTH-19-11.md + nvidia-rate.json):
  coord/heartbeat  -> google/gemma-4-31b-it       (OK 1.6s, no degrade at n=4)
  bench/token      -> nvidia/nemotron-3-nano-30b  (OK 0.5s, no degrade at n=4)
  redteam/probe    -> nvidia/nvidia/nemotron-3-ultra-550b-a55b (already assigned)
  tab/dominios     -> google/gemma-4-31b-it       (local RAG is offline anyway)
  persona/chunking -> google/gemma-4-31b-it       (needs reasoning, avoid 429)

API measured: POST /api/session/{id}/model with {"model":{"id":...,"providerID":...}} -> 204.

NEVER overwrites blindly: --dry-run first, --apply only on explicit request,
and it logs every change with old->new to a local manifest (no secrets).
"""
import argparse
import base64
import json
import pathlib
import time
import urllib.error
import urllib.request

HOME = pathlib.Path.home()
ROSTER = HOME / "projects/.agents/roster.json"
ENV = HOME / ".config/opencode/server.env"
LOG = HOME / ".local/state/fleet-model-route.jsonl"
OC = "http://100.121.100.103:4599"

# class -> (providerID, id) from measured matrix
MAP = {
    "coord": ("nvidia", "google/gemma-4-31b-it"),
    "bench": ("nvidia", "nvidia/nemotron-3-nano-omni-30b-a3b-reasoning"),
    "tab": ("nvidia", "google/gemma-4-31b-it"),
    "persona": ("nvidia", "google/gemma-4-31b-it"),
    "redteam": ("nvidia", "nvidia/nemotron-3-ultra-550b-a55b"),
}


def task_class(lane: str) -> str:
    l = (lane or "").lower()
    for k in ("coord", "bench", "tab", "persona", "redteam"):
        if k in l:
            return k
    return "coord"


def auth():
    env = ENV.read_text()
    pw = [x.split("=", 1)[1].strip().strip('"') for x in env.splitlines()
          if x.startswith("OPENCODE_SERVER_PASSWORD=")][0]
    return {"Authorization": "Basic " + base64.b64encode(f"opencode:{pw}".encode()).decode(),
            "Content-Type": "application/json"}


def call(path, body=None, method=None):
    r = urllib.request.Request(OC + path, data=json.dumps(body).encode() if body else None,
                               headers=auth(), method=method)
    try:
        with urllib.request.urlopen(r, timeout=20) as x:
            return x.status, x.read().decode()[:4000]
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode()[:4000]
    except Exception as e:
        return 0, str(e)[:120]


def current(session):
    st, raw = call("/api/session/" + session)
    if st != 200:
        return None
    try:
        d = json.loads(raw)
        s = d.get("data") or d
        m = s.get("model") or {}
        return f"{m.get('providerID')}/{m.get('modelID') or m.get('id')}"
    except Exception:
        return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true", help="actually switch models")
    ap.add_argument("--agent", default="", help="limit to one codename")
    ap.add_argument("--test", action="store_true", help="switch a throwaway session only")
    a = ap.parse_args()

    roster = json.loads(ROSTER.read_text())
    if a.test:
        st, raw = call("/api/session", {"title": "model-route-TESTE", "directory": "/tmp"}, "POST")
        sid = (json.loads(raw).get("data") or {}).get("id")
        if not sid: print("no test session"); return
        st2, raw2 = call(f"/api/session/{sid}/model", {"model": {"id": "google/gemma-4-31b-it", "providerID": "nvidia"}}, "POST")
        print("TEST switch HTTP", st2, raw2[:120])
        call(f"/api/session/{sid}", method="DELETE")
        print("TEST session closed")
        return
    changed = 0
    for ag in roster.get("agents", []):
        if a.agent and ag.get("codename") != a.agent:
            continue
        sid = ag.get("session")
        if not sid:
            print(f"{ag.get('codename')}: no session — skip")
            continue
        lane = ag.get("lane", "")
        cls = task_class(lane)
        pid, mid = MAP[cls]
        want = f"{pid}/{mid}"
        # V2 session GET nao devolve campo model (medido: keys id/projectID/cost/
        # tokens/time/title/location). A fonte e' o roster + o agent session modelo.
        cur = ag.get("model") or (roster.get("models") or {}).get(ag.get("codename"))
        status = "SAME" if cur == want else "SWITCH"
        print(f"{ag.get('codename'):10} lane={lane:28} class={cls:8} "
              f"{status:6} cur={str(cur)[:44]:44} want={want[:44]}")
        if status == "SWITCH" and a.apply:
            st, raw = call(f"/api/session/{sid}/model",
                           {"model": {"id": mid, "providerID": pid}}, "POST")
            print(f"   apply HTTP {st} {raw[:60]}")
            with LOG.open("a") as fh:
                fh.write(json.dumps({"ts": time.time(), "agent": ag.get("codename"),
                                     "class": cls, "from": cur, "to": want,
                                     "http": st}, ensure_ascii=False) + "\n")
            if st in (200, 204):
                ag["model"] = want   # UI le o model do roster (medido)
                changed += 1
    if a.apply and changed:
        tmp = ROSTER.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(roster, ensure_ascii=False, indent=2))
        tmp.replace(ROSTER)   # atomic, sem sobrescrita parcial
    print(f"\n{'APPLIED' if a.apply else 'DRY-RUN'}: {changed} switched")


if __name__ == "__main__":
    main()
