#!/usr/bin/env python3
"""F92: monitor da grade de ablacao. Nao relanca nada."""
import json, subprocess, time
from pathlib import Path

BASE = Path("/home/nixos/work/hybrid")
SIZES = (320, 704, 1216)
MODES = ("beta0", "beta005", "normoff")
EXPECTED = [f"ablation-d{d}-{m}-s42.json" for d in SIZES for m in MODES]
SNAP, RES = BASE / "ablation-watch.jsonl", BASE / "ablation-watch-result.json"
UNIT = "jarvis-ablation.service"
DEADLINE = time.time() + 6.5 * 3600

def active():
    r = subprocess.run(["systemctl", "--user", "is-active", UNIT],
                       capture_output=True, text=True, timeout=10)
    return r.stdout.strip()

def done():
    out = {}
    for name in EXPECTED:
        p = BASE / name
        if p.is_file():
            try:
                d = json.loads(p.read_text())
                out[name] = {"val": d.get("val_loss"), "acc": d.get("acc"),
                             "best": d.get("best"), "seconds": d.get("seconds")}
            except Exception as e:
                out[name] = {"error": str(e)[:80]}
    return out

event, detail = "timeout", {}
while time.time() < DEADLINE:
    got = done()
    if len(got) == len(EXPECTED):
        event, detail = "all_done", {"runs": got}
        break
    if active() != "active":
        event, detail = "unit_inactive", {"completed": len(got), "runs": got}
        break
    with SNAP.open("a", encoding="utf-8") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            "event": "tick", "completed": len(got), "unit": active()}) + "\n")
    time.sleep(120)
res = {"event": event, "detail": detail,
       "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
RES.write_text(json.dumps(res, indent=2) + "\n")
print(json.dumps({"event": event, "completed": len(detail.get("runs", {}))}))
