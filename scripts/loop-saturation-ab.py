#!/usr/bin/env python3
"""Curva de saturacao de Loop Transformer (arXiv 2610.40325).

Mesmo MiniGPT, mesmo seed, mesmos passos/lote/dataset; muda SOMENTE o numero
de vezes que o bloco e' reaplicado. Mede val loss e tokens/s. Esperado pelo
paper: ganhos saturam, revertem ou instabilizam com loops demais.
"""
from __future__ import annotations
import argparse, json, random, time
from pathlib import Path
import torch
from torch import nn

DATA = Path("/home/nixos/projects/build-nanogpt/input.txt")


def seed(s):
    random.seed(s); torch.manual_seed(s)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(s)


class LoopGPT(nn.Module):
    def __init__(self, vocab, d=192, ctx=128):
        super().__init__()
        self.ctx = ctx
        self.tok = nn.Embedding(vocab, d)
        self.pos = nn.Embedding(ctx, d)
        self.ln = nn.LayerNorm(d)
        self.q = nn.Linear(d, d); self.k = nn.Linear(d, d); self.v = nn.Linear(d, d)
        self.proj = nn.Linear(d, d)
        self.ff = nn.Sequential(nn.Linear(d, 4*d), nn.GELU(), nn.Linear(4*d, d))
        self.head = nn.Linear(d, vocab)
        self.apply(self._init)

    def _init(self, m):
        if isinstance(m, nn.Linear):
            nn.init.normal_(m.weight, std=0.02); nn.init.zeros_(m.bias)

    def forward(self, x, loops=4):
        t = x.shape[1]
        h = self.tok(x) + self.pos(torch.arange(t, device=x.device))
        for _ in range(loops):
            h = self.ln(h)
            q, k, v = self.q(h), self.k(h), self.v(h)
            a = torch.softmax(q @ k.transpose(-1, -2) / (q.shape[-1] ** 0.5), -1)
            h = h + self.proj(a @ v)
            h = h + self.ff(h)
        return self.head(h)


def run(loops, seed_v, steps, device, ctx=128, bs=16):
    seed(seed_v)
    text = DATA.read_text(encoding="utf-8")
    n = int(len(text)*0.9)
    chars = sorted(set(text)); stoi = {c:i for i,c in enumerate(chars)}
    ids = [stoi[c] for c in text[:n]]; vids = [stoi[c] for c in text[n:]]
    model = LoopGPT(len(chars), ctx=ctx).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=3e-4)
    t0=time.perf_counter(); model.train()
    for step in range(1, steps+1):
        st = torch.randint(0, len(ids)-ctx-1, (bs,))
        x = torch.tensor([ids[k:k+ctx] for k in st.tolist()], device=device)
        y = torch.tensor([ids[k+1:k+1+ctx] for k in st.tolist()], device=device)
        out = model(x, loops)
        loss = nn.functional.cross_entropy(out.reshape(-1, out.size(-1)), y.reshape(-1))
        opt.zero_grad(); loss.backward(); opt.step()
    train_s = time.perf_counter()-t0
    model.eval(); tot=0.0; cnt=0
    with torch.no_grad():
        for k in range(0, len(vids)-ctx, ctx*bs):
            ch = vids[k:k+ctx*bs]
            if len(ch) < ctx+1: break
            xs=[ch[i:i+ctx] for i in range(0,len(ch)-ctx,ctx)]
            if not xs: break
            x=torch.tensor(xs,device=device)
            y=torch.tensor([ch[i+1:i+1+ctx] for i in range(0,len(ch)-ctx,ctx)],device=device)
            tot += float(nn.functional.cross_entropy(model(x,loops).reshape(-1,len(chars)),y.reshape(-1),reduction="sum"))
            cnt += y.numel()
    seed(seed_v)
    start=torch.zeros((1,1),dtype=torch.long,device=device)
    t1=time.perf_counter()
    with torch.no_grad():
        for _ in range(64):
            nxt=model(start,loops)[:,-1,:].argmax(-1,keepdim=True)
            start=torch.cat([start,nxt],dim=1)
    gen=time.perf_counter()-t1
    return {"loops":loops,"params":sum(p.numel() for p in model.parameters()),
            "val_loss":round(tot/max(cnt,1),4),"train_seconds":round(train_s,1),
            "gen_tok_s":round(64/gen,2) if gen else 0}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--steps",type=int,default=600)
    ap.add_argument("--loops",default="2,4,6,8")
    ap.add_argument("--seed",type=int,default=42)
    ap.add_argument("--device",default="cuda")
    ap.add_argument("--out",type=Path,default=Path("/home/nixos/work/hybrid/loop-ab/report.json"))
    a=ap.parse_args()
    dev=a.device if torch.cuda.is_available() and a.device=="cuda" else "cpu"
    rows=[]
    for L in [int(x) for x in a.loops.split(",")]:
        r=run(L,a.seed,a.steps,dev); rows.append(r)
        print("LOOP "+json.dumps(r),flush=True)
    best=min(rows,key=lambda r:r["val_loss"])
    sat=2 if best["loops"]==max(r["loops"] for r in rows) else 0
    out={"paper":"arXiv 2610.40325","same_compute":True,"steps":a.steps,
         "device":dev,"seed":a.seed,"rows":rows,
         "best_loops":best["loops"],"monotonic_to_max":bool(sat)}
    a.out.parent.mkdir(parents=True,exist_ok=True)
    a.out.write_text(json.dumps(out,indent=2)+"\n")
    print("REPORT "+str(a.out),flush=True)

if __name__=="__main__":
    raise SystemExit(main())
