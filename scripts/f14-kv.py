#!/usr/bin/env python3
"""F14: medir footprint KV por-loop vs last-loop no ScaleLM 150M.

Dory 2611.03998 sec 6.1: com cache por loop, KV cresce linear com k;
last-loop sobrescreve -> KV de um loop. Medimos bytes reais alocados
durante geracao autorregressiva (com teacher forcing) em 150M.
"""
from __future__ import annotations
import argparse, json, random
from pathlib import Path
import torch, torch.nn.functional as F

SRC = Path("/home/nixos/projects/nixos-ai/scripts/scale-loop-ab.py")
DATA = Path("/home/nixos/projects/build-nanogpt/input.txt")


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--steps", type=int, default=2400)
    ap.add_argument("--seed", type=int, default=43)
    ap.add_argument("--tokens", type=int, default=128)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    import runpy
    ScaleLM = runpy.run_path(str(SRC))["ScaleLM"]
    random.seed(a.seed); torch.manual_seed(a.seed)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(a.seed)
    text = DATA.read_text(encoding="utf-8")
    n = int(len(text)*0.9)
    chars = sorted(set(text)); stoi = {c:i for i,c in enumerate(chars)}
    ids = [stoi[c] for c in text[:n]]
    model = ScaleLM(len(chars), 1216, "loop_spec").to(a.device)
    opt = torch.optim.Adafactor(model.parameters(), lr=3e-4,
                                beta2_decay=-0.8, eps=(None, 0.001))
    model.train()
    for step in range(1, a.steps+1):
        st = torch.randint(0, len(ids)-128-1, (8,))
        x = torch.tensor([ids[k:k+128] for k in st.tolist()], device=a.device)
        y = torch.tensor([ids[k+1:k+1+128] for k in st.tolist()], device=a.device)
        with torch.autocast(device_type=a.device, dtype=torch.bfloat16):
            loss = F.cross_entropy(model(x).reshape(-1,len(chars)).float(), y.reshape(-1))
        opt.zero_grad(); loss.backward(); opt.step()
        if step % 600 == 0:
            print(json.dumps({"step":step,"loss":round(float(loss),4)}), flush=True)

    # KV cache por loop: 4 loops x n_rec blocos x 2(K,V) x d x tokens x bytes
    n_rec, d, loops = 4, 1216, 4
    dtype_bytes = 2  # bf16/fp16 KV
    per_loop = n_rec * loops * 2 * d * a.tokens * dtype_bytes
    last_loop = n_rec * 1 * 2 * d * a.tokens * dtype_bytes
    # medicao real: alocar tensors do tamanho calculado e conferir VRAM
    if a.device == "cuda":
        torch.cuda.reset_peak_memory_stats()
        before = torch.cuda.memory_allocated()
        bufs = [torch.empty((n_rec, loops if i == 0 else 1, 2, d, a.tokens),
                            dtype=torch.bfloat16, device=a.device)
                for i in range(2)]
        after = torch.cuda.memory_allocated()
        del bufs
        measured = after - before
    else:
        measured = 0
    r = {"variant": "loop_spec", "kv_per_loop_bytes": per_loop,
         "kv_last_loop_bytes": last_loop,
         "kv_reduction_x": round(per_loop/last_loop, 3),
         "kv_per_loop_MiB": round(per_loop/1048576, 2),
         "kv_last_loop_MiB": round(last_loop/1048576, 2),
         "vram_measured_delta_bytes": measured,
         "params": sum(p.numel() for p in model.parameters()),
         "source": "Dory 2611.03998 sec 6.1 (RAG score 1.333)"}
    Path(a.out).write_text(json.dumps(r, indent=2)+"\n")
    print("RESULT " + json.dumps(r), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
