#!/usr/bin/env python3
"""Z4: A/B Loop 2 vs 4 com adapters LoRA r=8, mesmo compute.

Modelo base congelado; LoRA injetado em q/v de cada bloco. O numero de
blocos e' o parametro testado; o ORCAMENTO DE TREINO e' o mesmo (mesmo
numero de atualizacoes e tokens vistos). Mede val loss e tok/s.
Paper: arXiv 2610.40325 (adapters low-rank melhoram com mais loops).
"""
from __future__ import annotations
import argparse, json, math, random, sys
from pathlib import Path
import torch
from torch import nn
sys.path.insert(0, str(Path(__file__).resolve().parent))
from zero_model import TinyLM



def _patched_attn_forward(self, x):
    import math as _m
    b, t, d = x.shape
    q = (self.Wq(x) if getattr(self, "_use_call", False) else x @ self.Wq)
    v = (self.Wv(x) if getattr(self, "_use_call", False) else x @ self.Wv)
    q = q.view(b, t, self.h, self.dh).transpose(1, 2)
    k = (x @ self.Wk).view(b, t, self.h, self.dh).transpose(1, 2)
    v = v.view(b, t, self.h, self.dh).transpose(1, 2)
    att = torch.softmax(q @ k.transpose(-2, -1) / _m.sqrt(self.dh), -1)
    out = (att @ v).transpose(1, 2).contiguous().view(b, t, d)
    return out @ self.Wo


from zero_model import SelfAttention as _SA
_SA.forward = _patched_attn_forward

DATA = Path("/home/nixos/projects/build-nanogpt/input.txt")


def seed(s):
    random.seed(s); torch.manual_seed(s)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(s)


class LoRA(nn.Module):
    """LoRA sobre um tensor de pesos (o SelfAttention do zero_model guarda
    Wq/Wk/Wv como Parameter, nao como nn.Linear)."""
    def __init__(self, weight: nn.Parameter, r=8, scale=2.0):
        super().__init__()
        self.register_buffer("base", weight.detach().clone())
        self.A = nn.Parameter((torch.randn(r, weight.shape[0]) * 0.01).to(weight.device))
        self.B = nn.Parameter(torch.zeros(weight.shape[1], r, device=weight.device))
        self.scale = scale

    def forward(self, x):
        return x @ self.base + (x @ self.A.T) @ self.B.T * self.scale


def inject(model, r=8):
    for blk in model.blocks:
        q, v = LoRA(blk.att.Wq, r=r), LoRA(blk.att.Wv, r=r)
        object.__setattr__(blk.att, "Wq", q)
        object.__setattr__(blk.att, "Wv", v)
        blk.att._use_call = True
    return model


def lora_params(model):
    return [p for n, p in model.named_parameters() if p.requires_grad]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--steps", type=int, default=1000)
    ap.add_argument("--pretrain", type=int, default=1000)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    dev = a.device if torch.cuda.is_available() and a.device == "cuda" else "cpu"
    text = DATA.read_text(encoding="utf-8")
    n = int(len(text)*0.9)
    chars = sorted(set(text)); stoi = {c:i for i,c in enumerate(chars)}
    ids = [stoi[c] for c in text[:n]]; vids = [stoi[c] for c in text[n:]]
    rows = []
    for layers in (2, 4):
        seed(a.seed)
        model = TinyLM(vocab=len(chars), d=144, layers=layers, heads=4).to(dev)
        # pre-treina o base (como no paper: adapters sobre modelo treinado)
        base_opt = torch.optim.AdamW(model.parameters(), lr=3e-4)
        model.train()
        for _ in range(a.pretrain):
            st = torch.randint(0, len(ids)-128-1, (24,))
            x = torch.tensor([ids[k:k+128] for k in st.tolist()], device=dev)
            y = torch.tensor([ids[k+1:k+1+128] for k in st.tolist()], device=dev)
            loss0 = nn.functional.cross_entropy(model(x).reshape(-1,len(chars)), y.reshape(-1))
            base_opt.zero_grad(); loss0.backward(); base_opt.step()
        inject(model, r=8)
        opt = torch.optim.AdamW(lora_params(model), lr=3e-4)
        import time
        t0 = time.perf_counter(); model.train()
        for step in range(1, a.steps+1):
            st = torch.randint(0, len(ids)-128-1, (24,))
            x = torch.tensor([ids[k:k+128] for k in st.tolist()], device=dev)
            y = torch.tensor([ids[k+1:k+1+128] for k in st.tolist()], device=dev)
            loss = nn.functional.cross_entropy(model(x).reshape(-1,len(chars)), y.reshape(-1))
            opt.zero_grad(); loss.backward(); opt.step()
            if step % 250 == 0:
                print(json.dumps({"layers": layers, "step": step,
                                  "loss": round(float(loss),4)}), flush=True)
        train_s = time.perf_counter()-t0
        model.eval(); tot=0.0; cnt=0
        with torch.no_grad():
            for k in range(0,len(vids)-128,128*24):
                ch=vids[k:k+128*24]
                if len(ch)<129: break
                xs=[ch[i:i+128] for i in range(0,len(ch)-128,128)]
                if not xs: break
                x=torch.tensor(xs,device=dev)
                y=torch.tensor([ch[i+1:i+1+128] for i in range(0,len(ch)-128,128)],device=dev)
                tot+=float(nn.functional.cross_entropy(model(x).reshape(-1,len(chars)),y.reshape(-1),reduction="sum"))
                cnt+=y.numel()
        v=tot/max(cnt,1)
        seed(a.seed)
        start=torch.zeros((1,1),dtype=torch.long,device=dev)
        t1=time.perf_counter()
        with torch.no_grad():
            for _ in range(128):
                nxt=model(start)[:,-1,:].argmax(-1,keepdim=True)
                start=torch.cat([start,nxt],dim=1)
        gen=time.perf_counter()-t1
        rows.append({"loops":layers,"trainable_lora":sum(p.numel() for p in lora_params(model)),
                     "val_loss":round(v,4),"val_bpb":round(v/math.log(2),4),
                     "train_seconds":round(train_s,1),"gen_tok_s":round(128/gen,2) if gen else 0})
        print("LOOP "+json.dumps(rows[-1]),flush=True)
    out={"paper":"arXiv 2610.40325","same_compute":True,"steps":a.steps,"pretrain":a.pretrain,
         "device":dev,"seed":a.seed,"rows":rows}
    Path(a.out).parent.mkdir(parents=True,exist_ok=True)
    Path(a.out).write_text(json.dumps(out,indent=2)+"\n")
    print("REPORT "+a.out,flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
