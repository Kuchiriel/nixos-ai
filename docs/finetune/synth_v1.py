"""Synthesizer v1: diverse preference pairs, deterministic truth (zero fabrication).
Axes: counting (random N/word/truth; rejected = prompt-number + off-by-k),
JSON-format (records -> JSON; rejected = python-repr variants), code-write
(random codes; rejected = truncated/guessed variants). Target: 400 pairs.
"""
import json
import random

rng = random.Random(20260921)
pairs = []


def add(prompt, chosen, rejected, family):
    pairs.append({"prompt": prompt, "chosen": chosen, "rejected": rejected,
                  "family": family, "provenance": "synthetic-v1"})


WORDS = ["WARN", "ERR", "FAIL", "INFO", "DEBUG"]
for i in range(150):
    w = rng.choice(WORDS)
    n = rng.randint(10, 60)
    every = rng.choice([2, 3, 4, 5])
    truth = sum(1 for k in range(1, n + 1) if k % every == 0)
    p = (f"Read data.txt with {n} lines, count lines containing {w} "
         f"(every {every}th line). Write ONLY that number to out.txt using write_file.")
    add(p, str(truth), str(rng.choice([n, every, truth + rng.choice([-2, -1, 1, 2])])), "count-synth")

KEYS = ["auth", "token", "key", "mode", "level"]
for i in range(100):
    k = rng.choice(KEYS)
    v = "".join(rng.choice("abcdefghijkmnopqrstuvwxyz23456789") for _ in range(rng.randint(3, 8)))
    if rng.random() < 0.3:
        v = str(rng.randint(10, 9999))
    p = (f'Write ONLY the compact JSON {{"{k}": "<value>"}} where <value> is {v!r} '
         f"as the entire content of out.json using write_file.")
    good = json.dumps({k: v})
    bad_style = rng.choice([
        str({k: v}).replace('"', "'"),
        "{'" + k + "': '" + str(v) + "'}",
        json.dumps({k: v})[:-1],
    ])
    add(p, good, bad_style, "json-synth")

CODES = ["QX", "ZT", "MK", "RV"]
for i in range(100):
    code = f"{rng.choice(CODES)}-{rng.randint(10, 99)}"
    p = (f"The vault code is {code}. Write ONLY that code as the entire content "
         f"of out.txt using write_file.")
    bad = rng.choice([code.lower(), code.replace("-", ""), str(rng.randint(10, 99))])
    add(p, code, bad, "code-synth")

# instruction-following: exact-echo of tricky-but-fair strings (ASCII ws only)
for i in range(50):
    s = "".join(rng.choice(["a", "b ", "c  ", "d ", "1", "2 "]) for _ in range(rng.randint(2, 5))).rstrip(" ") + ""
    s = s.strip()
    if not s:
        continue
    p = (f"Write EXACTLY this text as the entire content of out.txt using write_file: [{s}]")
    add(p, s, s + " " if rng.random() < 0.5 else s.rstrip(), "echo-synth")

json.dump(pairs, open("docs/finetune/synth-v1.jsonl", "w"))
from collections import Counter
print("synth pairs:", len(pairs), dict(Counter(p["family"] for p in pairs)))
