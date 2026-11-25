#!/usr/bin/env python3
"""Z2: treinar TinyLM (~1M params) em TinyShakespeare, 2000 passos.

Mede perda final, tokens processados/s de treino e tokens/s de geracao.
mesmo seed/dataset/ passos em CPU e GPU. Nenhum peso externo.
"""
from __future__ import annotations
import argparse, json, random, time
from pathlib import Path
import torch
from torch import nn
import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))
from zero_model import TinyLM

DATA = Path("/home/nixos/projects/build-nanogpt/input.txt")


def seed(s):
    random.seed(s); torch.manual_seed(s)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(s)


def run(device, steps, d, layers, ctx, bs, seed_v, out):
    seed(seed_v)
    text = DATA.read_text(encoding="utf-8")
    n = int(len(text)*0.9)
    chars = sorted(set(text)); stoi = {c:i for i,c in enumerate(chars)}
    ids = [stoi[c] for c in text[:n]]; vids = [stoi[c] for c in text[n:]]
    model = TinyLM(vocab=len(chars), d=d, layers=layers, ctx=ctx).to(device)
    params = sum(p.numel() for p in model.parameters())
    opt = torch.optim.AdamW(model.parameters(), lr=3e-4)
    t0 = time.perf_counter(); model.train(); seen = 0
    for step in range(1, steps+1):
        st = torch.randint(0, len(ids)-ctx-1, (bs,))
        x = torch.tensor([ids[k:k+ctx] for k in st.tolist()], device=device)
        y = torch.tensor([ids[k+1:k+1+ctx] for k in st.tolist()], device=device)
        out_ = model(x)
        loss = nn.functional.cross_entropy(out_.reshape(-1, out_.size(-1)), y.reshape(-1))
        opt.zero_grad(); loss.backward(); opt.step()
        seen += x.numel()
        if step % 250 == 0:
            print(json.dumps({"device": device, "step": step,
                              "loss": round(float(loss), 4)}), flush=True)
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
            tot += float(nn.functional.cross_entropy(model(x).reshape(-1,len(chars)), y.reshape(-1), reduction="sum"))
            cnt += y.numel()
    val = tot/max(cnt,1)
    seed(seed_v)
    start=torch.zeros((1,1),dtype=torch.long,device=device)
    t1=time.perf_counter()
    with torch.no_grad():
        for _ in range(128):
            nxt=model(start)[:,-1,:].argmax(-1,keepdim=True)
            start=torch.cat([start,nxt],dim=1)
    gen=time.perf_counter()-t1
    Path(out).parent.mkdir(parents=True,exist_ok=True)
    r={"device":device,"params":params,"steps":steps,"d":d,"layers":layers,
       "ctx":ctx,"bs":bs,"seed":seed_v,"train_loss":round(float(loss),4),
       "val_loss":round(val,4),"val_bpb":round(val/0.693147,4),
       "train_seconds":round(train_s,1),"train_tok_s":round(seen/train_s,1),
       "gen_tok_s":round(128/gen,2) if gen else 0}
    Path(out).write_text(json.dumps(r,indent=2)+"\n")
    print("RESULT "+json.dumps(r),flush=True)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--device",default="cuda")
    ap.add_argument("--steps",type=int,default=2000)
    ap.add_argument("--d",type=int,default=144)
    ap.add_argument("--layers",type=int,default=4)
    ap.add_argument("--ctx",type=int,default=128)
    ap.add_argument("--bs",type=int,default=24)
    ap.add_argument("--seed",type=int,default=42)
    ap.add_argument("--out",required=True)
    a=ap.parse_args()
    dev=a.device if torch.cuda.is_available() and a.device=="cuda" else "cpu"
    run(dev,a.steps,a.d,a.layers,a.ctx,a.bs,a.seed,a.out)

if __name__=="__main__":
    raise SystemExit(main())
