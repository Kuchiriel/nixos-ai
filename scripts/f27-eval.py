#!/usr/bin/env python3
"""F12: unificar protocolos — ECE/entropia POR POSICAO nos primeiros 16 tokens.

Mesmo prompt de 64 chars do F10/F11, 300 prompts, 150M Adafactor.
Para cada posicao t (0..15): p(top1), entropia, acerto com teacher-forcing.
Compara com F8/F9 (geracao livre a partir de 1 token) e responde se a
entropia baixa do ngpt era efeito de contexto curto.
"""
from __future__ import annotations
import argparse, json, random
from pathlib import Path
import torch
import torch.nn.functional as F

SRC = Path("/home/nixos/projects/nixos-ai/scripts/scale-loop-ab.py")
DATA = Path("/home/nixos/projects/build-nanogpt/input.txt")


def ece(conf, corr, bins=10):
    out = 0.0
    for i in range(bins):
        lo, hi = i / bins, (i + 1) / bins
        idx = [j for j, c in enumerate(conf) if lo <= c < hi]
        if not idx: continue
        ac = sum(corr[j] for j in idx) / len(idx)
        av = sum(conf[j] for j in idx) / len(idx)
        out += len(idx) / len(conf) * abs(ac - av)
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--variant", choices=["plain", "ngpt_only", "loop_spec", "loop_spec_tern"], required=True)
    ap.add_argument("--seed", type=int, default=43)
    ap.add_argument("--steps", type=int, default=2400)
    ap.add_argument("--prompts", type=int, default=300)
    ap.add_argument("--d", type=int, default=1216)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    import runpy
    ScaleLM = runpy.run_path(str(SRC))["ScaleLM"]
    random.seed(a.seed); torch.manual_seed(a.seed)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(a.seed)
    text = DATA.read_text(encoding="utf-8")
    n = int(len(text)*0.9)
    chars = sorted(set(text)); stoi = {c:i for i,c in enumerate(chars)}
    ids = [stoi[c] for c in text[:n]]; vids = [stoi[c] for c in text[n:]]
    model = ScaleLM(len(chars), a.d, a.variant).to(a.device)
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
            print(json.dumps({"variant":a.variant,"seed":a.seed,"step":step,
                              "loss":round(float(loss),4)}), flush=True)
    model.eval()
    rng = random.Random(1234)
    starts = [rng.randint(0, len(vids)-160) for _ in range(a.prompts)]
    per_pos = {t: {"conf": [], "ent": [], "corr": []} for t in range(16)}
    with torch.no_grad():
        for k in starts:
            ctx = vids[k:k+64]; target = vids[k+64:k+80]
            h = torch.tensor([ctx], device=a.device)
            for t in range(16):
                p = torch.softmax(model(h)[:, -1, :].float(), -1)
                conf = float(p.max()); ent = float(-(p*p.log()).sum())
                pred = int(p.argmax())
                per_pos[t]["conf"].append(conf)
                per_pos[t]["ent"].append(ent)
                per_pos[t]["corr"].append(int(pred == target[t]))
                h = torch.cat([h, torch.tensor([[target[t]]], device=a.device)], dim=1)
    rows = []
    for t in range(16):
        d = per_pos[t]
        rows.append({"pos": t,
                     "conf": round(sum(d["conf"])/len(d["conf"]),4),
                     "ent": round(sum(d["ent"])/len(d["ent"]),4),
                     "acc": round(sum(d["corr"])/len(d["corr"]),4),
                     "ece": round(ece(d["conf"],d["corr"]),4)})
    # val loss no mesmo split (media dos tokens alvo)
    model.eval(); vl = 0.0; vn = 0
    with torch.no_grad():
        for k in starts[:20]:
            ctx = vids[k:k+64]; tgt = vids[k+64:k+80]
            x = torch.tensor([ctx], device=a.device)
            lg = model(x, causal=True)[0, -16:, :].float()
            vl += float(F.cross_entropy(lg.reshape(-1, lg.size(-1)),
                                        torch.tensor(tgt, device=a.device).reshape(-1),
                                        reduction="sum"))
            vn += len(tgt)
    r = {"variant": a.variant, "seed": a.seed, "prompts": a.prompts,
         "val_loss": round(vl / max(vn, 1), 4),
         "depth": a.d,
         "checkpoint_kb": round(sum(p.numel()*p.element_size() for p in model.parameters()
                                    if p.dtype.is_floating_point) / 1024, 1),
         "ece_all": round(ece([v for row in rows for v in per_pos[row["pos"]]["conf"]],
                              [v for row in rows for v in per_pos[row["pos"]]["corr"]]),4),
         "ent_all": round(sum(x["ent"] for x in rows)/len(rows),4),
         "acc_all": round(sum(x["acc"] for x in rows)/len(rows),4),
         "per_position": rows}
    Path(a.out).write_text(json.dumps(r, indent=2)+"\n")
    print("RESULT " + json.dumps({k:v for k,v in r.items() if k!="per_position"}), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
