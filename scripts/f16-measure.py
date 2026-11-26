#!/usr/bin/env python3
"""F16: cache valido em 150M — VRAM/tokens/s/acuracia por modo, mesmo checkpoint."""
from __future__ import annotations
import argparse, json, random, time, torch
import torch.nn.functional as F
from pathlib import Path
SRC = Path("/home/nixos/projects/nixos-ai/scripts/scale-loop-ab.py")
DATA = Path("/home/nixos/projects/build-nanogpt/input.txt")

def ece(conf, corr, bins=10):
    out=0.0
    for i in range(bins):
        lo,hi=i/bins,(i+1)/bins
        idx=[j for j,c in enumerate(conf) if lo<=c<hi]
        if not idx: continue
        out += len(idx)/len(conf)*abs(sum(corr[j] for j in idx)/len(idx)-sum(conf[j] for j in idx)/len(idx))
    return out

def main():
    ap=argparse.ArgumentParser(); ap.add_argument("--seed",type=int,default=43)
    ap.add_argument("--steps",type=int,default=2400); ap.add_argument("--prompts",type=int,default=100)
    ap.add_argument("--device",default="cuda"); ap.add_argument("--out",required=True)
    a=ap.parse_args()
    import runpy
    ScaleLM=runpy.run_path(str(SRC))["ScaleLM"]
    random.seed(a.seed); torch.manual_seed(a.seed)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(a.seed)
    text=DATA.read_text(); chars=sorted(set(text)); stoi={c:i for i,c in enumerate(chars)}
    ids=[stoi[c] for c in text[:int(len(text)*0.9)]]; vids=[stoi[c] for c in text[int(len(text)*0.9):]]
    m=ScaleLM(len(chars),1216,"loop_spec").to(a.device)
    opt=torch.optim.Adafactor(m.parameters(),lr=3e-4,beta2_decay=-0.8,eps=(None,0.001))
    m.train()
    for s in range(1,a.steps+1):
        st=torch.randint(0,len(ids)-129,(8,))
        x=torch.tensor([ids[k:k+128] for k in st.tolist()],device=a.device)
        y=torch.tensor([ids[k+1:k+1+128] for k in st.tolist()],device=a.device)
        with torch.autocast(device_type=a.device,dtype=torch.bfloat16):
            loss=F.cross_entropy(m(x).reshape(-1,len(chars)).float(),y.reshape(-1))
        opt.zero_grad(); loss.backward(); opt.step()
        if s%600==0: print(json.dumps({"step":s,"loss":round(float(loss),4)}),flush=True)
    m.eval()
    rng=random.Random(1234); starts=[rng.randint(0,len(vids)-80) for _ in range(a.prompts)]
    rows=[]
    with torch.no_grad():
        for mode in ("full","per_loop","last"):
            confs,corrs=[],[]; peak=0; t0=time.perf_counter()
            for k in starts:
                if a.device=="cuda": torch.cuda.reset_peak_memory_stats()
                ctx=vids[k:k+64]; tgt=vids[k+64]
                if mode=="full":
                    p=torch.softmax(m(torch.tensor([ctx],device=a.device),causal=True)[0,-1,:].float(),-1)
                else:
                    st={"caches":{},"u":None}
                    for pos,tok in enumerate(ctx):
                        out=m.forward_cached(torch.tensor([[tok]],device=a.device),pos,st,mode)
                    p=torch.softmax(out[0,0,:].float(),-1)
                confs.append(float(p.max())); corrs.append(int(int(p.argmax())==tgt))
                if a.device=="cuda": peak=max(peak,torch.cuda.max_memory_allocated())
            dt=time.perf_counter()-t0
            rows.append({"mode":mode,"acc":round(sum(corrs)/len(corrs),4),
                         "ece":round(ece(confs,corrs),4),"peak_vram_bytes":peak,
                         "seconds":round(dt,1),"prompts_per_s":round(a.prompts/dt,2)})
    r={"seed":a.seed,"prompts":a.prompts,"rows":rows}
    Path(a.out).write_text(json.dumps(r,indent=2)+"\n")
    print("RESULT "+json.dumps(r),flush=True)

if __name__=="__main__": raise SystemExit(main())
