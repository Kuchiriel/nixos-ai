#!/usr/bin/env python3
"""F33: gerar texto com o checkpoint word-level (usado pelo /lab/generate)."""
import json, sys
from pathlib import Path
import torch
import runpy
from transformers import GPT2TokenizerFast

CKPT = Path("/home/nixos/work/hybrid/checkpoints/f32-wordlevel-s42.pt")
prompt = sys.argv[1] if len(sys.argv) > 1 else "Once upon a time"
n = int(sys.argv[2]) if len(sys.argv) > 2 else 60
dev = "cuda" if torch.cuda.is_available() else "cpu"
ck = torch.load(CKPT, map_location=dev, weights_only=False)
tok = GPT2TokenizerFast.from_pretrained(ck["tokenizer"], local_files_only=True)
ScaleLM = runpy.run_path("/home/nixos/projects/nixos-ai/scripts/scale-loop-ab.py")["ScaleLM"]
m = ScaleLM(ck["vocab"], ck["d"], "ngpt_only").to(dev)
m.load_state_dict(ck["state"]); m.eval()
ids = tok.encode(prompt)[:ck["seq"]]
h = torch.tensor([ids], device=dev)
out = []
with torch.no_grad():
    for _ in range(n):
        lg = m(h, causal=True)[0, -1, :]
        pr = torch.softmax(lg.float() / 0.8, -1)
        nxt = int(torch.multinomial(pr, 1))
        out.append(nxt)
        h = torch.cat([h, torch.tensor([[nxt]], device=dev)], dim=1)
print(json.dumps({"prompt": prompt, "generated": tok.decode(out),
                  "tokens": n, "model": "f32-wordlevel-s42"}))
