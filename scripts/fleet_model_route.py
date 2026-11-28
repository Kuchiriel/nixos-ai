#!/usr/bin/env python3
"""fleet-model-route v2 — model assignment from AUTHORITATIVE sources.

V1 hard-coded a MAP — that created a 4th routing policy, exactly what ADR-004
(docs/architecture/ADR-004-routing-policy.md) warns against. V2 derives:
  1) allowed providers/tiers from jarvis.core.provider_registry.describe()/route()
     (the authoritative privacy/cost policy — now has real consumers);
  2) which concrete model is healthy from ai-mesh/docs/provider-health-2026-11-19.json
     (measured OK / RATE_LIMIT / PAID / DEAD);
  3) task class from the lane (thin, local classification only).

No new policy. If the registry or the measurement changes, routing changes.
Fail closed: if a chosen provider is not in route(PUBLIC), skip the switch.

Usage: --dry-run (default) | --apply | --agent NAME | --test
"""
import argparse
import base64
import json, os
import pathlib
import subprocess
import time
import urllib.error
import urllib.request

HOME = pathlib.Path.home()
REPO = HOME / "projects/nixos-ai"
ROSTER = HOME / "projects/.agents/roster.json"
ENV = HOME / ".config/opencode/server.env"
LOG = HOME / ".local/state/fleet-model-route.jsonl"
HEALTH = HOME / "projects/ai-mesh/docs/provider-health-2026-11-19.json"
OC = os.environ.get("AGENTS_OC_URL","http://127.0.0.1:4599")


def registry() -> dict:
    """Authoritative policy from the registry (nix develop for deps)."""
    cmd = ["nix", "develop", "--command", "python3", "-c",
           "import sys,json;sys.path.insert(0,'modules/ai/jarvis/src');"
           "from jarvis.core.provider_registry import describe,route;"
           "print(json.dumps({'describe':describe(),'public':route()}))"]
    r = subprocess.run(cmd, cwd=str(REPO), capture_output=True, text=True, timeout=120)
    for line in (r.stdout or "").splitlines():
        if line.startswith("{"):
            return json.loads(line)
    return {}


def measured_status(model: str) -> str | None:
    """Status of a concrete model from the full health matrix (name-insensitive)."""
    f = HOME / "projects/ai-mesh/docs/provider-health-2026-11-19.json"
    if not f.is_file():
        return None
    short = model.split("/")[-1].replace(":free", "")
    found = []
    for m in json.loads(f.read_text()).get("models", []):
        ms = m["model"].split("/")[-1].replace(":free", "")
        if ms == short:
            found.append(m.get("status"))
    # same short name can appear in two probe rows (e.g. retired 410 + live OK)
    # prefer OK, then EMPTY, then anything else — never let a stale row decide.
    for good in ("OK", "EMPTY"):
        if good in found:
            return good
    return found[0] if found else None


BAD = {"RATE_LIMIT", "DEAD", "PAID", "AUTH", "ERROR"}


def healthy_models() -> dict:
    """Measured OK models by provider, merged from ALL measured sources.

    Fragmentation found 19/11: provider-health JSON has gemma; nvidia-rate
    JSON has nemotron-nano/ultra (both HTTP 200 with 4 parallel calls).
    Merging prevents a false 'only one model is healthy' verdict.
    """
    out = {}
    # source 1: full 35-model matrix
    f1 = HOME / "projects/ai-mesh/docs/provider-health-2026-11-19.json"
    if f1.is_file():
        for m in json.loads(f1.read_text()).get("models", []):
            if m.get("status") == "OK":
                out.setdefault(m["provider"], []).append(m["model"])
    # source 2: NVIDIA rate/concurrency probe (single + 4 parallel = 200)
    f2 = HOME / "projects/ai-mesh/docs/nvidia-rate-2026-11-19.json"
    if f2.is_file():
        for row in json.loads(f2.read_text()):
            ok1 = row.get("single") == 200
            ok4 = all(s == 200 for s in row.get("four", []))
            if ok1 and ok4:
                out.setdefault("nvidia", []).append(row["model"])
    # dedup
    return {p: sorted(set(v)) for p, v in out.items()}


def preferred(provider_desc: dict, public: list, health: dict, cls: str) -> tuple[str, str] | None:
    """Registry policy (allowed providers) x measured reality (healthy models).

    Task class only picks WHICH healthy model to prefer, never a new policy:
      redteam -> lowest-refusal specialist (nemotron-ultra) if measured OK
      bench   -> fastest measured model (nano) if present
      others  -> first measured-OK model of an allowed provider
    """
    allowed = set(public or [])
    candidates = [p for p in health if p in allowed]
    providers = provider_desc.get("providers", provider_desc)
    rank = {n: (0 if info.get("tier") == "free" else 1, n) for n, info in providers.items()}
    candidates.sort(key=lambda p: rank.get(p, (2, p)))
    for name in candidates:
        models = health[name]
        if cls == "redteam":
            pref = [m for m in models if "ultra" in m] or models
        elif cls == "bench":
            pref = [m for m in models if "nano" in m] or models
        else:
            pref = models
        if pref:
            return (name, pref[0])
    return None


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


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--agent", default="")
    ap.add_argument("--test", action="store_true")
    a = ap.parse_args()

    pol = registry()
    health = healthy_models()
    if not pol:
        raise SystemExit("registry indisponivel — fail closed, nada alterado")
    print(f"policy: {len(pol.get('public', []))} providers allowed; measured-OK models: {len(health)}")

    if a.test:
        st, raw = call("/api/session", {"title": "model-route-v2-TESTE", "directory": "/tmp"}, "POST")
        sid = (json.loads(raw).get("data") or {}).get("id")
        pick = preferred(pol.get("describe", {}), pol.get("public", []), health, "coord")
        if not sid or not pick:
            print("no test session / no allowed+healthy model"); return
        st2, _ = call(f"/api/session/{sid}/model",
                      {"model": {"id": pick[1], "providerID": pick[0]}}, "POST")
        print("TEST pick", pick, "HTTP", st2)
        call(f"/api/session/{sid}", method="DELETE")
        return

    roster = json.loads(ROSTER.read_text())
    changed = 0
    for ag in roster.get("agents", []):
        if a.agent and ag.get("codename") != a.agent:
            continue
        sid = ag.get("session")
        if not sid:
            continue
        cls = task_class(ag.get("lane", ""))
        pick = preferred(pol.get("describe", {}), pol.get("public", []), health, cls)
        if not pick:
            print(f"{ag.get('codename'):10} class={cls:8} SEM CANDIDATO allow+OK — skip (fail closed)")
            continue
        want = f"{pick[0]}/{pick[1]}"
        cur = ag.get("model") or ""
        cur_status = measured_status(cur)
        if cur and cur_status not in BAD:
            # conservative: current model is OK/EMPTY/unmeasured but not BAD
            # and its provider is allowed — do not churn (ADR-004: no new policy)
            cur_provider = cur.split("/")[0]
            if cur_provider in (pol.get("public") or []) or cur_status is None:
                print(f"{ag.get('codename'):10} class={cls:8} KEEP    cur={cur[:38]:38} "
                      f"status={cur_status} (no churn)")
                continue
        status = "SAME" if cur == want else "SWITCH"
        print(f"{ag.get('codename'):10} class={cls:8} {status:6} cur={cur[:38]:38} want={want[:46]} "
              f"cur_status={cur_status}")
        if status == "SWITCH" and a.apply:
            st, raw = call(f"/api/session/{sid}/model",
                           {"model": {"id": pick[1], "providerID": pick[0]}}, "POST")
            print(f"   HTTP {st}")
            if st in (200, 204):
                ag["model"] = want
                changed += 1
                with LOG.open("a") as fh:
                    fh.write(json.dumps({"ts": time.time(), "agent": ag.get("codename"),
                                         "class": cls, "from": cur, "to": want,
                                         "source": "registry+health", "http": st},
                                        ensure_ascii=False) + "\n")
    if a.apply and changed:
        tmp = ROSTER.with_suffix(".json.tmp")
        tmp.write_text(json.dumps(roster, ensure_ascii=False, indent=2))
        tmp.replace(ROSTER)
    print(f"{'APPLIED' if a.apply else 'DRY-RUN'}: {changed} switched")


if __name__ == "__main__":
    main()
