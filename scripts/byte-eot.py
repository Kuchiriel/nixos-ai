#!/usr/bin/env python3
"""Preparacao byte+EOT (257 simbolos) — F102. SEM treino, SEM GPU.

--check : so guarda/estado, nao executa
--build : tokeniza corpus para bytes + EOT e grava npy/stats (sem treinar)
"""
import argparse, json, sys, time
from pathlib import Path

B = Path("/home/nixos/work/hybrid")
TOKDIR = B / "gpt2-local"
EOT = 256

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("check", "build"))
    ap.add_argument("--src", default="/home/nixos/Books/corpora/TinyStories-train.txt")
    ap.add_argument("--limit", type=int, default=20_000_000)
    ap.add_argument("--out", default=str(B / "byte-eot-ids.npy"))
    a = ap.parse_args()
    if a.mode == "check":
        print(json.dumps({"event": "check", "vocab": 257, "eot": EOT,
                          "source": a.src, "no_train": True}))
        return
    import numpy as np
    from transformers import GPT2TokenizerFast
    tok = GPT2TokenizerFast.from_pretrained(str(TOKDIR), local_files_only=True)
    text = Path(a.src).read_text(errors="ignore")[:a.limit]
    ids = tok.encode(text)
    from array import array
    chunks, total = [], 0
    for i in range(0, len(ids), 2000):
        out = array("I")
        for tid in ids[i:i+2000]:
            out.extend(tok.decode([tid]).encode("utf-8"))
            out.append(EOT)
        arr = np.frombuffer(out, dtype=np.uint32).astype(np.int32)
        chunks.append(arr); total += len(arr)
    result = np.concatenate(chunks)
    np.save(a.out, result)
    stats = {"n": int(total), "vocab": 257, "eot_id": EOT,
             "eot_count": int((result == EOT).sum()),
             "source": a.src, "tokenizer": str(TOKDIR),
             "note": "EOT apos cada token GPT-2; 1/6 de dados e logits 1/5 sao do paper 2609.12303, NAO medidos aqui"}
    Path(str(a.out).replace(".npy", "-stats.json")).write_text(
        json.dumps(stats, indent=2) + "\n")
    print("RESULT " + json.dumps(stats))

if __name__ == "__main__":
    main()
