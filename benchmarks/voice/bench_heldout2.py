#!/usr/bin/env python3
"""Held-out #2 runner (identical methodology, fresh items only)."""
import importlib.util
import os
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path("/home/nixos/projects/nixos-ai")
spec = importlib.util.spec_from_file_location(
    "duplex_voice_ref", REPO / "scripts/duplex-voice.py")
dv = importlib.util.module_from_spec(spec)
sys.argv = ["duplex-voice-ref"]
spec.loader.exec_module(dv)

sys.path.insert(0, str(Path(__file__).parent))
from heldout2 import HELDOUT2

# (13/11) JARVIS_BENCH_BASE env var: argv depois do clia-reset sempre dava
# len==1 e o bench batia na 8093 morta com 0/24 SILENCE falsos-negativos.
# Heldout2 e feito para a instancia de teste (v3) na 8093; producao = 8092.
BASE = (os.environ.get("JARVIS_BENCH_BASE")
        or (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8093"))

rows = []
t0 = time.monotonic()
correct = 0
cm = defaultdict(Counter)
lat = []
for utter, expected in HELDOUT2:
    t = time.monotonic()
    lab = dv.classify_turn(BASE, utter)
    lat.append(time.monotonic() - t)
    cm[expected][lab or "NONE"] += 1
    ok = (lab == expected)
    correct += ok
    print(f"{lab or 'NONE':8} {expected:7s} {'ok' if ok else 'MISS'}| {utter}", flush=True)

tot = len(HELDOUT2)
print()
for exp in ("RESPOND", "WAIT", "SILENCE", "BARGE"):
    n = sum(cm[exp].values())
    if not n:
        continue
    hit = cm[exp].get(exp, 0)
    print(f"{exp:8} acc {hit}/{n}  (pred {dict(cm[exp])})")
print(f"TOTAL {correct}/{tot}  mean_lat={1000*sum(lat)/len(lat):.0f} ms")
