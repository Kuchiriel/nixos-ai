#!/usr/bin/env python3
"""Gerador do playground /lab — checkpoint word-level (F32/F35)."""
from pathlib import Path
from collections import Counter
import json, sys
import torch, runpy
from transformers import GPT2TokenizerFast

CKPT = Path("/home/nixos/work/hybrid/checkpoints/f43-150m-full-s42.pt")
prompt = sys.argv[1] if len(sys.argv) > 1 else "Once upon a time"
n = int(sys.argv[2]) if len(sys.argv) > 2 else 60
dev = "cuda" if torch.cuda.is_available() else "cpu"
ck = torch.load(CKPT, map_location=dev, weights_only=False)
tok = GPT2TokenizerFast.from_pretrained(ck["tokenizer"], local_files_only=True)

# remap EXATO do corpus de treino, salvo junto com o checkpoint
cpath = str(ck.get("corpus", "")) + " " + CKPT.name
if "full" in cpath:
    import json as _json
    st = _json.load(open("/home/nixos/Books/corpora/tinystories-full-ids-stats.json"))
    remap = {int(k): int(v) for k, v in st["remap"].items()}
elif "200mb" in cpath or "ids.pt" in cpath:
    cd = torch.load("/home/nixos/Books/corpora/tinystories-200mb-ids.pt",
                    map_location="cpu", weights_only=False)
    remap = cd["remap"]
else:
    CORPUS = Path("/home/nixos/Books/corpora/TinyStories-valid.txt")
    raw = tok.encode(CORPUS.read_text(errors="ignore")[:20_000_000])
    common = [w for w, _ in Counter(raw).most_common(ck["vocab"])]
    remap = {w: i for i, w in enumerate(common)}
rev = {i: w for w, i in remap.items()}

ScaleLM = runpy.run_path("/home/nixos/projects/nixos-ai/scripts/scale-loop-ab.py")["ScaleLM"]
m = ScaleLM(ck["vocab"], ck["d"], "ngpt_only").to(dev)
m.load_state_dict(ck["state"]); m.eval()
ids = [remap.get(w, 0) for w in tok.encode(prompt)[:ck["seq"]]]
h = torch.tensor([ids], device=dev)
out = []
with torch.no_grad():
    for _ in range(n):
        lg = m(h, causal=True)[0, -1, :]
        pr = torch.softmax(lg.float() / 0.8, -1)
        nxt = int(torch.multinomial(pr, 1))
        out.append(nxt)
        h = torch.cat([h, torch.tensor([[nxt]], device=dev)], dim=1)
print(json.dumps({"prompt": prompt, "generated": tok.decode([rev.get(i, 0) for i in out]),
                  "tokens": n, "model": "f43-150m-full-s42"}))
