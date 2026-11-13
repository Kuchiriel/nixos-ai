#!/usr/bin/env python3
"""Held-out com o fallback de prompt (A estrito -> B com <think>).

Mede o v6-LoRA pelo CAMINHO QUE SERIA PRODUCAO se o harness (classify_turn)
trocasse o prompt: tenta A como hoje; se a resposta nao casa nenhum label,
tenta B (assistant + <think>\\n). v1 (microturn-4b) resolve no A e nunca paga
o B; v6 resolve no B. Acertos por classe + latencia. NAO TROCA PRODUCAO.
"""
import importlib.util
import json
import sys
import time
import urllib.request
from collections import Counter, defaultdict
from pathlib import Path

REPO = Path("/home/nixos/projects/nixos-ai")
BASE = sys.argv[2] if len(sys.argv) > 2 else "http://127.0.0.1:8093"
WHICH = sys.argv[1]  # heldout1 | heldout2
spec = importlib.util.spec_from_file_location(
    "dv_ref", REPO / "scripts/duplex-voice.py")
dv = importlib.util.module_from_spec(spec)
sys.argv = ["dv_ref"]
spec.loader.exec_module(dv)

import sys as _s
_s.path.insert(0, str(REPO / "benchmarks" / "voice"))

labels = list(dv.CLASS_LABELS)
items = None
if WHICH == "heldout1":
    from heldout import HELDOUT
    items = HELDOUT
else:
    from heldout2 import HELDOUT2
    items = HELDOUT2

SYS = dv.CLASS_SYS

def lora(scale):
    req = urllib.request.Request(
        BASE + "/lora-adapters",
        data=json.dumps([{"id": 0, "scale": scale}]).encode(),
        headers={"Content-Type": "application/json"})
    urllib.request.urlopen(req, timeout=5).read()

def complete(prompt):
    body = {"prompt": prompt, "n_predict": 6, "temperature": 0,
            "stop": ["<|im_end|>"], "cache_prompt": True}
    req = urllib.request.Request(
        BASE + "/completion",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=30) as r:
        j = json.loads(r.read())
    return (j.get("content") or "").strip().upper()

def classify_ab(utt):
    pA = (f"<|im_start|>system\n{SYS}<|im_end|>\n"
          f"<|im_start|>user\n{utt}<|im_end|>\n"
          f"<|im_start|>assistant\n")
    out = complete(pA)
    for lab in labels:
        if out.startswith(lab):
            return lab, "A"
    pB = pA + "<think>\n"
    out = complete(pB)
    for lab in labels:
        if out.startswith(lab):
            return lab, "B"
    return None, "NONE"

lora(1.0)
cm = defaultdict(Counter)
lat = []
path_count = Counter()
correct = 0
for utt, expected in items:
    t = time.monotonic()
    lab, path = classify_ab(utt)
    lat.append((time.monotonic() - t) * 1000)
    path_count[path] += 1
    cm[expected][lab or "NONE"] += 1
    ok = (lab == expected)
    correct += ok
    print(f"{lab or 'NONE':8}{path:4} {expected:7s} {'ok' if ok else 'MISS'}| {utt}",
          flush=True)
print()
for exp in ("RESPOND", "WAIT", "SILENCE", "BARGE"):
    n = sum(cm[exp].values())
    if n:
        print(f"{exp:8} acc {cm[exp].get(exp, 0)}/{n}  pred={dict(cm[exp])}")
print(f"TOTAL {correct}/{len(items)}  mean_lat={sum(lat)/len(lat):.0f} ms  "
      f"pathA={path_count['A']} pathB={path_count['B']}")
lora(0.0)
