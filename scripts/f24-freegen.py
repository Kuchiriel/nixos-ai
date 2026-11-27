#!/usr/bin/env python3
"""F24: eficiencia de tokens em GERACAO LIVRE (>=256 tokens, sem teacher forcing).

Compara:
  - plain: forward_cached com cache per-loop (exato, exacto)
  - last:  forward_cached com cache last-loop (Dory, KV 4x menor)
Mesmo checkpoint, mesmo prompt, causal, Adafactor.
Mede: acuracia token a token (contra o texto real), ECE, entropia, VRAM, tok/s.
"""
from __future__ import annotations
import argparse, json, math, random, time, torch
import torch.nn.functional as F
from pathlib import Path

SRC = Path("/home/nixos/projects/nixos-ai/scripts/scale-loop-ab.py")
DATA = Path("/home/nixos/projects/build-nanogpt/input.txt")


def ece(conf, corr, bins=10):
    out = 0.0
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        idx = [j for j, c in enumerate(conf) if lo <= c < hi]
        if not idx: continue
        out += len(idx) / len(conf) * abs(sum(corr[j] for j in idx) / len(idx)
                                         - sum(conf[j] for j in idx) / len(idx))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--depth", type=int, default=1216)
    ap.add_argument("--steps", type=int, default=2400)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--prompts", type=int, default=50)
    ap.add_argument("--gen-tokens", type=int, default=256)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    import runpy
    ScaleLM = runpy.run_path(str(SRC))["ScaleLM"]
    random.seed(a.seed); torch.manual_seed(a.seed)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(a.seed)
    text = DATA.read_text(encoding="utf-8")
    n = int(len(text) * 0.9)
    chars = sorted(set(text)); stoi = {c: i for i, c in enumerate(chars)}
    ids = [stoi[c] for c in text[:n]]; vids = [stoi[c] for c in text[n:]]
    model = ScaleLM(len(chars), a.depth, "loop_spec").to(a.device)
    opt = torch.optim.Adafactor(model.parameters(), lr=3e-4,
                                beta2_decay=-0.8, eps=(None, 0.001))
    model.train()
    for step in range(1, a.steps + 1):
        st = torch.randint(0, len(ids) - 128 - 1, (8,))
        x = torch.tensor([ids[k:k + 128] for k in st.tolist()], device=a.device)
        y = torch.tensor([ids[k + 1:k + 1 + 128] for k in st.tolist()], device=a.device)
        with torch.autocast(device_type=a.device, dtype=torch.bfloat16):
            loss = F.cross_entropy(model(x, causal=True).reshape(-1, len(chars)).float(), y.reshape(-1))
        opt.zero_grad(); loss.backward(); opt.step()
        if step % 600 == 0:
            print(json.dumps({"step": step, "loss": round(float(loss), 4)}), flush=True)
    model.eval()
    rng = random.Random(1234)
    starts = [rng.randint(0, len(vids) - a.gen_tokens - 64 - 2)
              for _ in range(a.prompts)]
    rows = []
    with torch.no_grad():
        for mode in ("full", "per_loop", "last"):
            confs, corrs, ents = [], [], []
            peak = 0; t0 = time.perf_counter()
            for k in starts:
                if a.device == "cuda": torch.cuda.reset_peak_memory_stats()
                ctx = vids[k:k + 64]
                target = vids[k + 64:k + 64 + a.gen_tokens]
                if mode == "full":
                    # forward causal com o histórico inteiro (sem cache incremental)
                    h = torch.tensor([ctx], device=a.device)
                    gen = []
                    for t in range(a.gen_tokens):
                        p = torch.softmax(model(h, causal=True)[0, -1, :].float(), -1)
                        pred = int(p.argmax())
                        gen.append(pred)
                        confs.append(float(p.max()))
                        ents.append(float(-(p * p.log()).sum()))
                        corrs.append(int(pred == target[t]))
                        h = torch.cat([h, torch.tensor([[pred]], device=a.device)], dim=1)
                else:
                    state = {"caches": {}, "u": None}
                    preds = []
                    for pos, tok in enumerate(ctx):
                        out = model.forward_cached(torch.tensor([[tok]], device=a.device),
                                                   pos, state, mode)
                    p = torch.softmax(out[0, 0, :].float(), -1)
                    pred = int(p.argmax())
                    confs.append(float(p.max())); ents.append(float(-(p * p.log()).sum()))
                    corrs.append(int(pred == target[0]))
                    preds.append(pred)
                    for t in range(1, a.gen_tokens):
                        out = model.forward_cached(torch.tensor([[preds[-1]]], device=a.device),
                                                   64 + t - 1, state, mode)
                        p = torch.softmax(out[0, 0, :].float(), -1)
                        pred = int(p.argmax())
                        confs.append(float(p.max())); ents.append(float(-(p * p.log()).sum()))
                        corrs.append(int(pred == target[t]))
                        preds.append(pred)
                if a.device == "cuda":
                    peak = max(peak, torch.cuda.max_memory_allocated())
            dt = time.perf_counter() - t0
            rows.append({"mode": mode, "tokens": a.gen_tokens, "steps": a.steps,
                         "acc": round(sum(corrs) / len(corrs), 4),
                         "ece": round(ece(confs, corrs), 4),
                         "entropy_mean": round(sum(ents) / len(ents), 4),
                         "peak_vram_bytes": peak, "seconds": round(dt, 1),
                         "tok_per_s": round(a.prompts * a.gen_tokens / dt, 1),
                         "raw_conf": [round(c, 5) for c in confs],
                         "raw_corr": [int(c) for c in corrs]})
    r = {"seed": a.seed, "depth": a.depth, "prompts": a.prompts,
         "teacher_forcing": False, "rows": rows}
    Path(a.out).write_text(json.dumps(r, indent=2) + "\n")
    print("RESULT " + json.dumps({k: v for k, v in r.items() if k != "rows"}), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
