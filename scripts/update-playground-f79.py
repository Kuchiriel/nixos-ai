#!/usr/bin/env python3
"""Atualiza arch-facts.json e o timelapse 2D com o resultado do F79 (20k).

Guard: se f79-20k-s42.json NAO existir, nao altera nenhum arquivo.
Nao inventa valores; tudo vem do checkpoint e do JSON medidos.
"""
import json, re, shutil, subprocess, time
from pathlib import Path
import torch

B = Path("/home/nixos/work/hybrid")
J = B / "f79-20k-s42.json"
CK = B / "checkpoints/f79-20k-s42.pt"
FACTS = B / "arch-facts.json"
HTML = Path("/home/nixos/projects/nixos-ai/tools/lab-timeline/index.html")
RESULT = B / "f79-playground-update.json"

NOTES = {
 "F10 · 10M": "word-level, scheduled sampling", "F35 · 50M": "50M word-level",
 "F36 · 50M/30k": "overfit em 30k", "F37 · 150M lr": "taxa de aprendizado isolada",
 "F38 · 50M early": "early stopping 4k", "F39 · 150M lr1e-4": "lr 1e-4 em 150M",
 "F41 · 50M big": "50M com d maior", "F42 · 50M full": "baseline 50M full",
 "F45 · 300M QAT": "QAT ternario", "F46 · 300M QAT/40k": "QAT 40k passos",
 "F43 · 150M full": "baseline 150M", "F44 · 300M full": "escala maior",
 "F47 · 150M early": "early stopping", "F49 · 150M/40k": "curva 40k",
 "F50 · 150M/60k": "perto do gate 1.5", "F52 · 150M/68k": "gate 1.5 cruzado",
 "F53 · SimpleStories": "curadoria vence volume", "F66 · curto": "encurtar piorou",
 "F71 · dedup8": "dedup ingenua piorou", "F75 · curado 210M": "escala curada apoiada",
 "F79 · 20k curado": "H3: 20k passos no corpus curado",
}

def finish(event, detail=""):
    RESULT.write_text(json.dumps({"event": event, "detail": detail,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, indent=2) + "\n")
    print(json.dumps({"event": event, "detail": detail}))

if not J.is_file() or not CK.is_file():
    finish("guard", "JSON/checkpoint do F79 ausentes — nenhum arquivo alterado")
    raise SystemExit(0)

d = json.loads(J.read_text())
c = torch.load(CK, map_location="cpu", weights_only=False)
st = c["state"]
dd = int(c["d"]); heads = 8
while dd % heads: heads += 1
blocks = len({k.split(".")[1] for k in st if k.startswith("blocks.")})
label = "F79 · 20k curado"
entry = {"label": label, "d": dd, "vocab": int(c["vocab"]),
         "heads": heads, "blocks": blocks,
         "params": round(sum(v.numel() for v in st.values()) / 1e6, 1),
         "val": d.get("val_loss"), "acc": d.get("acc"),
         "steps": int(d.get("steps", 0)), "corpus": "SimpleStories 210M",
         "note": NOTES[label], "curve": d.get("curve", [])}

facts = json.loads(FACTS.read_text()) if FACTS.is_file() else {"models": []}
facts["models"] = [m for m in facts["models"] if m.get("label") != label] + [entry]
facts["models"].sort(key=lambda m: int("".join(ch for ch in m["label"] if ch.isdigit()) or 0))

backup = Path("/tmp") / f"lab-index.bak-f79-{int(time.time())}"
shutil.copy2(HTML, backup)
arch = [{k: m.get(k) for k in ("label", "d", "vocab", "params", "val", "acc", "steps", "corpus", "note")}
        for m in facts["models"]]
js = "const ARCH=" + json.dumps(arch, ensure_ascii=False) + ";"
s = HTML.read_text(encoding="utf-8")
s2, n = re.subn(r"const ARCH=\[.*?\];", js, s, count=1, flags=re.S)
if n != 1:
    shutil.copy2(backup, HTML)
    finish("erro", "padrao const ARCH nao encontrado; HTML restaurado")
    raise SystemExit(2)
HTML.write_text(s2, encoding="utf-8")

for i, blk in enumerate(re.findall(r"<script>(.*?)</script>", s2, re.S)):
    t = Path("/tmp") / f"f79-js-{i}.js"
    t.write_text(blk, encoding="utf-8")
    r = subprocess.run(["node", "--check", str(t)], capture_output=True, text=True)
    if r.returncode != 0:
        shutil.copy2(backup, HTML)
        finish("erro", f"node --check falhou no bloco {i}; HTML restaurado")
        raise SystemExit(3)

FACTS.write_text(json.dumps(facts, indent=2) + "\n", encoding="utf-8")
html = subprocess.run(["curl", "-s", "-m", "20", "http://127.0.0.1:8091/lab"],
                      capture_output=True, text=True).stdout
finish("atualizado", {"backup": str(backup), "val": entry["val"],
                      "acc": entry["acc"], "params_M": entry["params"],
                      "http_200": "F79" in html, "models": len(arch)})
