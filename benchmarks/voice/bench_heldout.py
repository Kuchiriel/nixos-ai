#!/usr/bin/env python3
"""Held-out PT-BR eval para o gate LoRA (semantica v2: SILENCE inclui fala
completa nao-dirigida). Reusa o classificador real do duplex (classify_turn)."""
import importlib.util
import json
import sys
import time
from pathlib import Path

REPO = Path("/home/nixos/projects/nixos-ai")
spec = importlib.util.spec_from_file_location(
    "duplex_voice_ref", REPO / "scripts/duplex-voice.py")
dv = importlib.util.module_from_spec(spec)
_argv = sys.argv[:]
spec.loader.exec_module(dv)
sys.argv = _argv

import sys
import os
sys.path.insert(0, str(Path(__file__).parent))
from heldout import HELDOUT

# (13/11) argv foi resetado acima: BASE nunca viu a URL passada e caia no
# default 8092 em silencio. JARVIS_BENCH_BASE ganha; argv e fallback; default
# so se nada vier.
BASE = (os.environ.get("JARVIS_BENCH_BASE")
        or (sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:8092"))

rows = []
t0 = time.monotonic()
correct = 0
from collections import Counter, defaultdict
cm = defaultdict(Counter)
lat = []
for utter, expected in HELDOUT:
    t = time.monotonic()
    lab = dv.classify_turn(BASE, utter)
    lat.append(time.monotonic() - t)
    cm[expected][lab or "NONE"] += 1
    ok = (lab == expected)
    correct += ok
    print(f"{lab or 'NONE':8} {expected:7s} {'ok' if ok else 'MISS'}| {utter}", flush=True)

tot = len(HELDOUT)
print()
for exp in ("RESPOND", "WAIT", "SILENCE", "BARGE"):
    n = sum(cm[exp].values())
    hit = cm[exp].get(exp, 0)
    print(f"{exp:8} acc {hit}/{n}  (pred {dict(cm[exp])})")
print(f"TOTAL {correct}/{tot}  mean_lat={1000*sum(lat)/len(lat):.0f} ms")
