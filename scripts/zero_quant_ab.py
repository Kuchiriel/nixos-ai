#!/usr/bin/env python3
"""Z3: A/B de quantizacao por camada no TinyLM treinado do zero.

Treina UMA vez (mesma seed), depois aplica 3 esquemas ao MESMO state_dict:
  fp32    -> baseline
  ternary -> pesos {-1,0,1} * escala por tensor (LittleBit/BitNet b1.58)
  int4    -> 16 niveis simetricos por tensor (proxy de Q4_K_M)
Mede val loss apos quantizar (sem retreinar) e tamanho efetivo em bytes.
"""
from __future__ import annotations
import argparse, io, json, math, random, sys, time
from pathlib import Path
import torch
from torch import nn
sys.path.insert(0, str(Path(__file__).resolve().parent))
from zero_model import TinyLM

DATA = Path("/home/nixos/projects/build-nanogpt/input.txt")


def seed(s):
    random.seed(s); torch.manual_seed(s)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(s)


def load_data(ctx, bs, device):
    text = DATA.read_text(encoding="utf-8")
    n = int(len(text)*0.9)
    chars = sorted(set(text)); stoi={c:i for i,c in enumerate(chars)}
    ids=[stoi[c] for c in text[:n]]; vids=[stoi[c] for c in text[n:]]
    def batch(seq):
        st=torch.randint(0,len(seq)-ctx-1,(bs,))
        x=torch.tensor([seq[k:k+ctx] for k in st.tolist()],device=device)
        y=torch.tensor([seq[k+1:k+1+ctx] for k in st.tolist()],device=device)
        return x,y
    def val():
        out=[]
        for k in range(0,len(vids)-ctx,ctx*bs):
            ch=vids[k:k+ctx*bs]
            if len(ch)<ctx+1: break
            xs=[ch[i:i+ctx] for i in range(0,len(ch)-ctx,ctx)]
            if not xs: break
            x=torch.tensor(xs,device=device)
            y=torch.tensor([ch[i+1:i+1+ctx] for i in range(0,len(ch)-ctx,ctx)],device=device)
            out.append((x,y))
        return out
    return len(chars), ids, batch, val


def quant(state, mode):
    if mode == "fp32":
        return {k: v.float().clone() for k,v in state.items()}, 32
    out={}
    if mode == "ternary":
        bits=2  # 1.58-bit logico, 2 bits de armazenamento
        for k,v in state.items():
            if v.dim() < 2:
                out[k]=v.clone(); continue
            scale=v.abs().mean().clamp(min=1e-8)
            out[k]=torch.sign(v).mul(scale)
        return out, bits
    if mode == "int4":
        bits=4
        for k,v in state.items():
            if v.dim() < 2:
                out[k]=v.clone(); continue
            scale=(v.abs().max().clamp(min=1e-8))/7.0
            out[k]=(v/scale).round().clamp(-8,7).mul(scale)
        return out, bits
    raise ValueError(mode)


def state_bytes(state, bits):
    total=0
    for v in state.values():
        n=v.numel()
        if v.dim()<2: total += n*4
        else: total += math.ceil(n*bits/8)+4  # + escala float32
    return total


def evaluate(model, val_batches, vocab):
    model.eval(); tot=0.0; cnt=0
    with torch.no_grad():
        for x,y in val_batches:
            tot += float(nn.functional.cross_entropy(
                model(x).reshape(-1,vocab), y.reshape(-1), reduction="sum"))
            cnt += y.numel()
    return tot/max(cnt,1)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--steps",type=int,default=1000)
    ap.add_argument("--device",default="cuda")
    ap.add_argument("--seed",type=int,default=42)
    ap.add_argument("--out",required=True)
    a=ap.parse_args()
    dev=a.device if torch.cuda.is_available() and a.device=="cuda" else "cpu"
    seed(a.seed)
    vocab, ids, batch, val = load_data(128,24,dev)
    model=TinyLM(vocab=vocab,d=144,layers=4).to(dev)
    opt=torch.optim.AdamW(model.parameters(),lr=3e-4)
    model.train()
    for step in range(1,a.steps+1):
        x,y=batch(ids)
        loss=nn.functional.cross_entropy(model(x).reshape(-1,vocab),y.reshape(-1))
        opt.zero_grad(); loss.backward(); opt.step()
        if step%250==0: print(json.dumps({"step":step,"loss":round(float(loss),4)}),flush=True)
    base={k: v.detach().cpu().clone() for k,v in model.state_dict().items()}
    vb=val()
    rows=[]
    for mode in ("fp32","ternary","int4"):
        st,bits=quant(base,mode)
        m=TinyLM(vocab=vocab,d=144,layers=4).to(dev)
        m.load_state_dict({k:v.to(dev) for k,v in st.items()})
        v=evaluate(m,vb,vocab)
        rows.append({"mode":mode,"bits":bits,"val_loss":round(v,4),
                     "val_bpb":round(v/math.log(2),4),
                     "effective_bytes":state_bytes(st,bits),
                     "compression_vs_fp32":round(state_bytes(base,32)/state_bytes(st,bits),2)})
        print("QUANT "+json.dumps(rows[-1]),flush=True)
    out={"paper_refs":["arXiv 2402.17764 BitNet b1.58","LittleBit-2 ICML 2026"],
         "steps":a.steps,"device":dev,"seed":a.seed,"rows":rows}
    Path(a.out).parent.mkdir(parents=True,exist_ok=True)
    Path(a.out).write_text(json.dumps(out,indent=2)+"\n")
    print("REPORT "+a.out,flush=True)

if __name__=="__main__":
    raise SystemExit(main())
