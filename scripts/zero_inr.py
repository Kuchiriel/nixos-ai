#!/usr/bin/env python3
"""Z5: INR/SIREN gerada por hypernetwork no TinyLM (arXiv 2504.16580).

O estado latente do ultimo bloco alimenta uma hypernetwork que GERA os
pesos de uma SIREN pequena; a SIREN produz um vetor continuo que e'
adicionado ao logits como contexto extra. Compara com baseline sem INR.
Mesmo seed/compute. Nenhum peso externo.
"""
from __future__ import annotations
import argparse, json, math, random, sys, time
from pathlib import Path
import torch
from torch import nn
sys.path.insert(0, str(Path(__file__).resolve().parent))
from zero_model import TinyLM, TransformerBlock

DATA = Path("/home/nixos/projects/build-nanogpt/input.txt")


def seed(s):
    random.seed(s); torch.manual_seed(s)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(s)


class SIREN(nn.Module):
    """MLP com seno: representacao continua de funcao (Implicit Neural Repr)."""
    def __init__(self, in_dim=16, hidden=32, out_dim=16, omega=30.0):
        super().__init__()
        self.w1 = nn.Parameter(torch.randn(in_dim, hidden) * 0.1)
        self.b1 = nn.Parameter(torch.zeros(hidden))
        self.w2 = nn.Parameter(torch.randn(hidden, out_dim) * 0.1)
        self.b2 = nn.Parameter(torch.zeros(out_dim))
        self.omega = omega

    def forward(self, x, weights=None):
        if weights is None:
            w1, b1, w2, b2 = self.w1, self.b1, self.w2, self.b2
        else:
            w1, b1, w2, b2 = weights
        # x: [batch, seq, in_dim]; w1: [batch, in_dim, hidden]
        if w1.dim() == 2:  # pesos compartilhados
            h = torch.sin(self.omega * (x @ w1 + b1))
            return h @ w2 + b2
        h = torch.sin(self.omega * torch.einsum("bsi,bih->bsh", x, w1) + b1.unsqueeze(1))
        return torch.einsum("bsh,bho->bso", h, w2) + b2.unsqueeze(1)


class HyperINR(nn.Module):
    """Transformer pequeno -> pesos da SIREN (hypernetwork)."""
    def __init__(self, d=144, in_dim=16, hidden=32, out_dim=16):
        super().__init__()
        self.hidden, self.in_dim, self.out_dim = hidden, in_dim, out_dim
        self.proj = nn.Sequential(nn.Linear(d, d), nn.GELU(),
                                  nn.Linear(d, in_dim*hidden + hidden + hidden*out_dim + out_dim))

    def forward(self, h):
        w = self.proj(h.mean(dim=1))
        i, j = self.in_dim*self.hidden, self.in_dim*self.hidden+self.hidden
        k = j + self.hidden*self.out_dim
        return (w[:, :i].view(-1,self.in_dim,self.hidden),
                w[:, i:j],
                w[:, j:k].view(-1,self.hidden,self.out_dim),
                w[:, k:])


class TinyLM_INR(nn.Module):
    def __init__(self, vocab=65, d=144, layers=2, heads=4, ctx=128,
                 in_dim=16, hidden=32):
        super().__init__()
        self.base = TinyLM(vocab=vocab, d=d, layers=layers, heads=heads, ctx=ctx)
        self.hyp = HyperINR(d=d, in_dim=in_dim, hidden=hidden, out_dim=d)
        self.siren = SIREN(in_dim=in_dim, hidden=hidden, out_dim=d)
        self.gate = nn.Parameter(torch.zeros(1))
        self.ctx = ctx

    def forward(self, x):
        h = self.base.tok(x) + self.base.pos(torch.arange(x.shape[1], device=x.device))
        for blk in self.base.blocks:
            h = blk(h)
        h = self.base.ln(h)
        lat = h.mean(dim=1, keepdim=True)
        coords = torch.linspace(-1, 1, x.shape[1], device=x.device).view(1,-1,1).expand(x.shape[0],-1,self.siren.w1.shape[0])
        w = self.hyp(lat)
        seq = x.shape[1]
        w = tuple(t for t in w)
        cont = self.siren(coords, w)
        h = h + torch.tanh(self.gate) * cont
        return self.base.head(h)


def run(a, device):
    seed(a.seed)
    text = DATA.read_text(encoding="utf-8")
    n=int(len(text)*0.9)
    chars=sorted(set(text)); stoi={c:i for i,c in enumerate(chars)}
    ids=[stoi[c] for c in text[:n]]; vids=[stoi[c] for c in text[n:]]
    if a.mode == "inr":
        model=TinyLM_INR(vocab=len(chars)).to(device)
    else:
        model=TinyLM(vocab=len(chars), d=a.d_base, layers=2).to(device)
    params=sum(p.numel() for p in model.parameters())
    opt=torch.optim.AdamW(model.parameters(),lr=3e-4)
    t0=time.perf_counter(); model.train()
    for step in range(1,a.steps+1):
        st=torch.randint(0,len(ids)-a.ctx-1,(a.bs,))
        x=torch.tensor([ids[k:k+a.ctx] for k in st.tolist()],device=device)
        y=torch.tensor([ids[k+1:k+1+a.ctx] for k in st.tolist()],device=device)
        loss=nn.functional.cross_entropy(model(x).reshape(-1,len(chars)),y.reshape(-1))
        opt.zero_grad(); loss.backward(); opt.step()
        if step%250==0:
            print(json.dumps({"mode":a.mode,"step":step,"loss":round(float(loss),4)}),flush=True)
    train_s=time.perf_counter()-t0
    model.eval(); tot=0.0;cnt=0
    with torch.no_grad():
        for k in range(0,len(vids)-a.ctx,a.ctx*a.bs):
            ch=vids[k:k+a.ctx*a.bs]
            if len(ch)<a.ctx+1: break
            xs=[ch[i:i+a.ctx] for i in range(0,len(ch)-a.ctx,a.ctx)]
            if not xs: break
            x=torch.tensor(xs,device=device)
            y=torch.tensor([ch[i+1:i+1+a.ctx] for i in range(0,len(ch)-a.ctx,a.ctx)],device=device)
            tot+=float(nn.functional.cross_entropy(model(x).reshape(-1,len(chars)),y.reshape(-1),reduction="sum"))
            cnt+=y.numel()
    v=tot/max(cnt,1)
    return {"mode":a.mode,"params":params,"steps":a.steps,"val_loss":round(v,4),
            "val_bpb":round(v/math.log(2),4),"train_seconds":round(train_s,1)}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--mode",choices=["base","inr"],default="base")
    ap.add_argument("--steps",type=int,default=1000)
    ap.add_argument("--seed",type=int,default=42)
    ap.add_argument("--ctx",type=int,default=128)
    ap.add_argument("--bs",type=int,default=24)
    ap.add_argument("--d-base",type=int,default=224)
    ap.add_argument("--device",default="cuda")
    ap.add_argument("--out",required=True)
    a=ap.parse_args()
    dev=a.device if torch.cuda.is_available() and a.device=="cuda" else "cpu"
    r=run(a,dev)
    print("RESULT "+json.dumps(r),flush=True)
    Path(a.out).parent.mkdir(parents=True,exist_ok=True)
    Path(a.out).write_text(json.dumps(r,indent=2)+"\n")

if __name__=="__main__":
    raise SystemExit(main())
