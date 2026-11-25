#!/usr/bin/env python3
"""F15-debug: localizar a camada onde prefill-cached diverge do forward cheio."""
from __future__ import annotations
import argparse, json, math, random, torch
import torch.nn.functional as F
from pathlib import Path
SRC = Path("/home/nixos/projects/nixos-ai/scripts/scale-loop-ab.py")
DATA = Path("/home/nixos/projects/build-nanogpt/input.txt")

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--steps",type=int,default=200)
    ap.add_argument("--d",type=int,default=320); ap.add_argument("--device",default="cuda")
    a=ap.parse_args()
    import runpy
    ScaleLM=runpy.run_path(str(SRC))["ScaleLM"]
    random.seed(7); torch.manual_seed(7)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(7)
    text=DATA.read_text(); chars=sorted(set(text)); stoi={c:i for i,c in enumerate(chars)}
    ids=[stoi[c] for c in text[:int(len(text)*0.9)]]
    model=ScaleLM(len(chars),a.d,"loop_spec").to(a.device)
    opt=torch.optim.AdamW(model.parameters(),lr=1e-3)
    model.train()
    for s in range(1,a.steps+1):
        st=torch.randint(0,len(ids)-129,(4,))
        x=torch.tensor([ids[k:k+128] for k in st.tolist()],device=a.device)
        y=torch.tensor([ids[k+1:k+1+128] for k in st.tolist()],device=a.device)
        loss=F.cross_entropy(model(x).reshape(-1,len(chars)),y.reshape(-1))
        opt.zero_grad(); loss.backward(); opt.step()
    model.eval()
    # capturar h por bloco no forward cheio
    hs=[]
    def hook(i):
        def f(m,inp,out): hs.append((i,out.detach().clone()))
        return f
    handles=[b.register_forward_hook(hook(i)) for i,b in enumerate(model.blocks)]
    xt=torch.tensor([ids[:64]],device=a.device)
    with torch.no_grad(): model(xt)
    for h in handles: h.remove()
    print("full_h captured",len(hs),flush=True)
    # agora reconstruir passo a passo com o MESMO Attn.forward (sem cache) e comparar
    with torch.no_grad():
        h=model.tok(xt)+model.pos(torch.arange(64,device=a.device))
        for i,blk in enumerate(model.blocks):
            if i==2:
                u=h.detach().clone()
                for l in range(4):
                    h=F.normalize(h+u,dim=-1); h=blk(h)
            else: h=blk(h)
            got=[v for idx,v in hs if idx==i][-1]
            print("block",i,"maxdiff",float((h-got).abs().max()),flush=True)

if __name__=="__main__": raise SystemExit(main())
