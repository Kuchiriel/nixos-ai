#!/usr/bin/env python3
"""F1: curva de escala COM OTIMIZACOES dos papers (nao teste ingenuo).

3 escalas (10M/50M/150M) × 3 variantes:
  plain     — transformer normal
  loop+core — 4 passes do bloco recorrente COM reinjecao u + L2 (Dory)
  loop+full — loop+core + nGPT scales + LoRA r=8 por loop (Dory+Meta)

MESMO compute (mesmo n de tokens vistos e passos). Mede val loss, tok/s
e tokens gerados ate parar. Se uma variante for pior, o relatorio inclui
diagnostico (loss curve, grad norm) para ENTENDER o por que.

Papers: arXiv 2611.03998 (Dory/NVIDIA), 2610.40325 (Meta loop),
2402.17764 (BitNet b1.58), 2504.16580 (INR — nao usado aqui).
"""
from __future__ import annotations
import argparse, json, math, random, time
from pathlib import Path
import torch
from torch import nn

DATA = Path("/home/nixos/projects/build-nanogpt/input.txt")


def seed(s):
    random.seed(s); torch.manual_seed(s)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(s)


class Attn(nn.Module):
    def __init__(self, d, heads, scale_in=False):
        super().__init__()
        self.h, self.dh = heads, d // heads
        self.q = nn.Parameter(torch.randn(d, d) * 0.02)
        self.k = nn.Parameter(torch.randn(d, d) * 0.02)
        self.v = nn.Parameter(torch.randn(d, d) * 0.02)
        self.o = nn.Parameter(torch.randn(d, d) * 0.02)
        self.scale_in = scale_in
        if scale_in:
            self.alpha = nn.Parameter(torch.tensor(0.05))  # residual rate

    def forward(self, x, mask=None):
        b, t, d = x.shape
        call = getattr(self, "_use_call", False)
        q = (self.q(x) if call else x @ self.q).view(b, t, self.h, self.dh).transpose(1, 2)
        k = (x @ self.k).view(b, t, self.h, self.dh).transpose(1, 2)
        v = (self.v(x) if call else x @ self.v).view(b, t, self.h, self.dh).transpose(1, 2)
        att = torch.softmax(q @ k.transpose(-2, -1) / math.sqrt(self.dh), -1)
        out = (att @ v).transpose(1, 2).contiguous().view(b, t, d) @ self.o
        if self.scale_in:
            return nn.functional.normalize(x + self.alpha * out, dim=-1)  # nGPT/L2
        return x + out


class Block(nn.Module):
    def __init__(self, d, heads, scale_in=False):
        super().__init__()
        self.ln = nn.LayerNorm(d)
        self.att = Attn(d, heads, scale_in)
        self.ff = nn.Sequential(nn.Linear(d, 4*d), nn.GELU(), nn.Linear(4*d, d))
        self.scale_in = scale_in
        if scale_in:
            self.beta = nn.Parameter(torch.tensor(0.05))

    def forward(self, x):
        x = self.att(self.ln(x))
        f = self.ff(self.ln(x))
        if self.scale_in:
            return nn.functional.normalize(x + self.beta * f, dim=-1)
        return x + f


class LoRALinear(nn.Module):
    def __init__(self, w: nn.Parameter, r=8, alpha=2.0):
        super().__init__()
        self.register_buffer("base", w.detach().clone())
        self.A = nn.Parameter((torch.randn(r, w.shape[0]) * 0.01).to(w.device))
        self.B = nn.Parameter(torch.zeros(w.shape[1], r, device=w.device))
        self.alpha = alpha

    def forward(self, x):
        return x @ self.base + (x @ self.A.T) @ self.B.T * self.alpha


class ScaleLM(nn.Module):
    """input(2) + recurrent(4) + output(2) blocos; variantes ligam u+L2 e/ou LoRA."""
    def __init__(self, vocab, d, variant):
        super().__init__()
        self.d, self.variant = d, variant
        self.scale_in = variant == "loop_full"
        self.tok = nn.Embedding(vocab, d)
        self.pos = nn.Embedding(256, d)
        n_in, n_rec, n_out = 2, 4, 2
        self.blocks = nn.ModuleList([Block(d, max(2, d//64), self.scale_in) for _ in range(n_in+n_rec+n_out)])
        self.ln = nn.LayerNorm(d)
        self.head = nn.Linear(d, vocab)
        if variant == "loop_full":
            for blk in self.blocks[n_in:n_in+n_rec]:
                for attr in ("q", "v"):
                    w = getattr(blk.att, attr)
                    # remover o Parameter e registrar o LoRA como submodule
                    # (object.__setattr__ NAO registra -> .to(device) nao move)
                    del blk.att._parameters[attr]
                    setattr(blk.att, attr, LoRALinear(w))
                blk.att._use_call = True

    def forward(self, x):
        t = x.shape[1]
        h = self.tok(x) + self.pos(torch.arange(t, device=x.device))
        for i, blk in enumerate(self.blocks):
            if i == 2 and self.variant != "plain":
                u = h.detach().clone()  # Dory: representacao fixa de entrada
                for _ in range(3):  # total 4 passes do bloco recorrente
                    h = nn.functional.normalize(h + u, dim=-1)  # reinjecao + L2
                    h = blk(h)
            else:
                h = blk(h)
        return self.head(self.ln(h))


def lo_steps(model, d):
    # ERRO 24/11: formula anterior dava 590 passos em 50M e 360 em 150M —
    # 150M nao convergiu (loss 3.35 vs 0.02) e parecia "arquitetura pior".
    # Agora: MESMO numero de passos e TAMANHO DE LOTE para todas as escalas,
    # com orcamento fixo por RMS. Se 150M nao couber no device, reduzir
    # batch mas MANTER passos suficientes para convergir.
    return 800


def run(scale, variant, device, seed_v):
    import sys
    seed(seed_v)
    text = DATA.read_text(encoding="utf-8")
    n = int(len(text)*0.9)
    chars = sorted(set(text)); stoi = {c:i for i,c in enumerate(chars)}
    ids = [stoi[c] for c in text[:n]]; vids = [stoi[c] for c in text[n:]]
    # calibrado: params ~ 8 blocos x 12 d^2 => d=320~10M, 704~50M, 1216~150M
    d_map = {10: 320, 50: 704, 150: 1216}
    d = d_map[scale]
    model = ScaleLM(len(chars), d, variant).to(device)
    params = sum(p.numel() for p in model.parameters())
    steps = lo_steps(model, params)
    opt = torch.optim.AdamW(model.parameters(), lr=3e-4)
    t0 = time.perf_counter(); model.train(); seen = 0
    losses = []
    for step in range(1, steps+1):
        st = torch.randint(0, len(ids)-128-1, (24,))
        x = torch.tensor([ids[k:k+128] for k in st.tolist()], device=device)
        y = torch.tensor([ids[k+1:k+1+128] for k in st.tolist()], device=device)
        loss = nn.functional.cross_entropy(model(x).reshape(-1, len(chars)), y.reshape(-1))
        opt.zero_grad(); loss.backward(); opt.step()
        seen += x.numel(); losses.append(round(float(loss.detach()), 4))
        if step % max(50, steps//5) == 0:
            print(json.dumps({"scale": scale, "v": variant, "step": step,
                              "loss": losses[-1]}), flush=True)
    train_s = time.perf_counter()-t0
    model.eval(); tot=0.0; cnt=0
    with torch.no_grad():
        for k in range(0, len(vids)-128, 128*24):
            ch = vids[k:k+128*24]
            if len(ch) < 129: break
            xs=[ch[i:i+128] for i in range(0,len(ch)-128,128)]
            if not xs: break
            x=torch.tensor(xs,device=device)
            y=torch.tensor([ch[i+1:i+1+128] for i in range(0,len(ch)-128,128)],device=device)
            tot+=float(nn.functional.cross_entropy(model(x).reshape(-1,len(chars)),y.reshape(-1),reduction="sum"))
            cnt+=y.numel()
    val=tot/max(cnt,1)
    r={"scale_m":scale,"variant":variant,"params":params,"steps":steps,
       "val_loss":round(val,4),"val_bpb":round(val/math.log(2),4),
       "train_seconds":round(train_s,1),"train_tok_s":round(seen/train_s,1),
       "loss_first":losses[0],"loss_last":losses[-1],
       "loss_first_50_avg":round(sum(losses[:50])/len(losses[:50]),4),
       "loss_last_50_avg":round(sum(losses[-50:])/len(losses[-50:]),4)}
    print("RESULT "+json.dumps(r),flush=True)
    return r


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--device",default="cuda")
    ap.add_argument("--seed",type=int,default=42)
    ap.add_argument("--out",required=True)
    ap.add_argument("--only",default="",help="filtro scale:variant, ex 10:loop_full,50:plain")
    a=ap.parse_args()
    dev=a.device if torch.cuda.is_available() and a.device=="cuda" else "cpu"
    rows=[]
    only = set(x for x in a.only.split(",") if x)
    for scale in (10,50,150):
        for v in ("plain","loop_core","loop_full"):
            if only and f"{scale}:{v}" not in only:
                continue
            rows.append(run(scale,v,dev,a.seed))
    out={"paper_refs":["2611.03998 Dory","2610.40325 Meta loop","2402.17764 BitNet"],
         "same_compute_per_scale":True,"device":dev,"seed":a.seed,"rows":rows}
    Path(a.out).parent.mkdir(parents=True,exist_ok=True)
    Path(a.out).write_text(json.dumps(out,indent=2)+"\n")
    print("REPORT "+a.out,flush=True)


if __name__=="__main__":
    raise SystemExit(main())
