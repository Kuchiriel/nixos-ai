#!/usr/bin/env python3
"""Mede decode latency localmente nos checkpoints oficiais baixados.

Replica exatamente decode_latency() do script.py (LittleBitModel.from_pretrained
+ tokenizer + 16 warmup + 128 tokens), mas no host com os pesos ja baixados.
Nao usa Kaggle, nao re-treina, nao escreve em producao.
"""
from __future__ import annotations
import argparse, json, sys, time
from pathlib import Path
import torch

sys.path.insert(0, "/home/nixos/work/littlebit2/official-v6-error-20261124/LittleBit")
from quantization.hub import LittleBitModel
from utils.datautils import load_tokenizer


def decode_one(path, warmup, tokens):
    model = LittleBitModel.from_pretrained(path, torch_dtype=torch.bfloat16, device="auto")
    tok = load_tokenizer(path)
    device = next(model.parameters()).device
    ids = tok("Fleet parity is measured evidence, not a guess.",
              return_tensors="pt").input_ids[:, :16].to(device)
    model.eval()
    with torch.inference_mode():
        model.generate(ids, max_new_tokens=warmup, do_sample=False, use_cache=True)
        if device.type == "cuda": torch.cuda.synchronize()
        t0 = time.perf_counter()
        out = model.generate(ids, max_new_tokens=tokens, do_sample=False, use_cache=True)
        if device.type == "cuda": torch.cuda.synchronize()
        elapsed = time.perf_counter() - t0
    return {"elapsed_seconds": round(elapsed, 4),
            "generated_tokens": int(out.shape[-1] - ids.shape[-1]),
            "tokens_per_second": round((out.shape[-1]-ids.shape[-1])/elapsed, 2),
            "device": str(device)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--baseline", required=True)
    ap.add_argument("--littlebit2", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    out = {"schema": 1, "production_writes": False, "decode_method": "local host replica",
           "variants": {}}
    for name, path in (("baseline", a.baseline), ("littlebit2", a.littlebit2)):
        r = decode_one(str(path), 16, 128)
        out["variants"][name] = r
        Path(path, "decode-latency.json").write_text(json.dumps(r, indent=2) + "\n")
        print(name, json.dumps(r), flush=True)
    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    Path(a.out).write_text(json.dumps(out, indent=2) + "\n")
    print("REPORT " + a.out, flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
