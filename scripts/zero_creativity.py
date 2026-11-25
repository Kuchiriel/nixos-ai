#!/usr/bin/env python3
"""Z6: diversidade forçada (Nova/iNLG simplificado) no TinyLM do zero.

Mesmo modelo treinado, dois decoders:
  baseline -> greedy (argmax)
  forced   -> temperature + top-p + penalidade de repeticao + semente de
              dominio diferente por amostra (Nova-like seed variety)
Mede distinct-1/2, self-BLEU-4 e taxa de resposta nao-vazia em 12 amostras.
"""
from __future__ import annotations
import argparse, json, math, random, sys
from pathlib import Path
import torch
from torch import nn
sys.path.insert(0, str(Path(__file__).resolve().parent))
from zero_model import TinyLM

DATA = Path("/home/nixos/projects/build-nanogpt/input.txt")


def seed(s):
    random.seed(s); torch.manual_seed(s)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(s)


def ngrams(tokens, n):
    return set(tuple(tokens[i:i+n]) for i in range(len(tokens)-n+1))


def self_bleu(seqs, n=4):
    if len(seqs) < 2: return 0.0
    scores=[]
    for i,a in enumerate(seqs):
        sa=ngrams(a,n)
        if not sa: continue
        for j,b in enumerate(seqs):
            if i==j: continue
            sb=ngrams(b,n)
            scores.append(len(sa & sb)/max(len(sa),1))
    return sum(scores)/len(scores) if scores else 0.0


def sample(model, ids, device, vocab, mode, rng, max_new=96):
    model.eval()
    start = torch.randint(0, vocab, (1,1), device=device) if mode == "forced" else torch.zeros((1,1),dtype=torch.long,device=device)
    out = start[0].tolist()
    with torch.no_grad():
        for _ in range(max_new):
            logits = model(start)[:, -1, :] / (0.9 if mode == "forced" else 0.0001)
            if mode == "forced":
                # nucleus top-p 0.9
                s = torch.sort(logits[0], descending=True).values
                cum = torch.cumsum(torch.softmax(s, -1), -1)
                n_keep = int((cum > 0.9).nonzero()[0].item()) + 1
                kth = s[min(n_keep-1, s.numel()-1)]
                logits = logits.masked_fill(logits < kth, -1e9)
                # penalidade de repeticao simples
                for t in set(out[-24:]):
                    logits[0, t] -= 0.35
            probs = torch.softmax(logits, -1)
            nxt = torch.multinomial(probs, 1) if mode == "forced" else probs.argmax(-1, keepdim=True)
            out.append(int(nxt.item()))
            start = torch.cat([start, nxt], dim=1)
    return out


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--steps",type=int,default=1000)
    ap.add_argument("--device",default="cuda")
    ap.add_argument("--seed",type=int,default=42)
    ap.add_argument("--samples",type=int,default=12)
    ap.add_argument("--out",required=True)
    a=ap.parse_args()
    dev=a.device if torch.cuda.is_available() and a.device=="cuda" else "cpu"
    seed(a.seed)
    text=DATA.read_text(encoding="utf-8")
    chars=sorted(set(text)); stoi={c:i for i,c in enumerate(chars)}
    ids=[stoi[c] for c in text]
    model=TinyLM(vocab=len(chars), d=144, layers=2).to(dev)
    opt=torch.optim.AdamW(model.parameters(),lr=3e-4)
    model.train()
    for step in range(1,a.steps+1):
        st=torch.randint(0,len(ids)-128-1,(24,))
        x=torch.tensor([ids[k:k+128] for k in st.tolist()],device=dev)
        y=torch.tensor([ids[k+1:k+1+128] for k in st.tolist()],device=dev)
        loss=nn.functional.cross_entropy(model(x).reshape(-1,len(chars)),y.reshape(-1))
        opt.zero_grad(); loss.backward(); opt.step()
    rows=[]
    for mode in ("baseline","forced"):
        rng=random.Random(a.seed)
        seqs=[sample(model,ids,dev,len(chars),mode,rng) for _ in range(a.samples)]
        d1=sum(len(ngrams(s,1)) for s in seqs)/len(seqs)
        d2=sum(len(ngrams(s,2)) for s in seqs)/len(seqs)
        rows.append({"mode":mode,"distinct1":round(d1,2),"distinct2":round(d2,2),
                     "self_bleu4":round(self_bleu(seqs),4),
                     "mean_len":round(sum(len(s) for s in seqs)/len(seqs),1)})
        print("GEN "+json.dumps(rows[-1]),flush=True)
    out={"paper_refs":["Nova / Lacuna","iNLG","Diversity-Constrained Generation"],
         "steps":a.steps,"samples":a.samples,"device":dev,"rows":rows}
    Path(a.out).parent.mkdir(parents=True,exist_ok=True)
    Path(a.out).write_text(json.dumps(out,indent=2)+"\n")
    print("REPORT "+a.out,flush=True)

if __name__=="__main__":
    raise SystemExit(main())
