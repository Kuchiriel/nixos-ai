#!/usr/bin/env python3
"""F32:wordlevel — 10M word-level em TinyStories com scheduled sampling.

Tokenizador GPT-Neo/GPT-2 local, top-10k ids por frequencia.
Scheduled sampling: com probabilidade p (decai 1->0), substitui parte do
contexto por tokens gerados pelo proprio modelo (greedy), quebrando o
exposure bias medido em F26. Mede val loss/perplexidade e acc.
"""
from __future__ import annotations
import argparse, json, math, random, time
from collections import Counter
from pathlib import Path
import torch
import torch.nn.functional as F
from transformers import GPT2TokenizerFast

SRC = Path("/home/nixos/projects/nixos-ai/scripts/scale-loop-ab.py")
CORPUS = Path("/home/nixos/Books/corpora/TinyStories-valid.txt")
TOKDIR = Path("/home/nixos/work/hybrid/gpt2-local")


def build_tokens(topk=10000, limit=20_000_000):
    tok = GPT2TokenizerFast.from_pretrained(str(TOKDIR), local_files_only=True)
    text = CORPUS.read_text(errors="ignore")[:limit]
    ids = tok.encode(text)
    cnt = Counter(ids)
    common = [w for w, _ in cnt.most_common(topk)]
    remap = {w: i for i, w in enumerate(common)}
    seq = [remap.get(w, 0) for w in ids]
    return seq, len(remap)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--steps", type=int, default=2400)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--d", type=int, default=320)
    ap.add_argument("--seq", type=int, default=256)
    ap.add_argument("--batch", type=int, default=8)
    ap.add_argument("--no-ss", action="store_true")
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--ckpt", default="")
    ap.add_argument("--out", required=True)
    a = ap.parse_args()
    import runpy
    ScaleLM = runpy.run_path(str(SRC))["ScaleLM"]
    random.seed(a.seed); torch.manual_seed(a.seed)
    if torch.cuda.is_available(): torch.cuda.manual_seed_all(a.seed)
    seq, vocab = build_tokens()
    n = int(len(seq) * 0.95)
    train, val = seq[:n], seq[n:]
    print(json.dumps({"tokens": len(seq), "vocab": vocab,
                      "train": len(train), "val": len(val)}), flush=True)
    model = ScaleLM(vocab, a.d, "ngpt_only").to(a.device)
    # pos do ScaleLM atual e' 512; seq 256 cabe
    opt = torch.optim.Adagrad(model.parameters(), lr=0.01) if False else \
          torch.optim.AdamW(model.parameters(), lr=3e-4, fused=(a.device=="cuda"))
    t0 = time.perf_counter()
    model.train()
    for step in range(1, a.steps + 1):
        st = torch.randint(0, len(train) - a.seq - 1, (a.batch,))
        x = torch.tensor([train[k:k+a.seq] for k in st.tolist()], device=a.device)
        y = torch.tensor([train[k+1:k+1+a.seq] for k in st.tolist()], device=a.device)
        # scheduled sampling: p decai de 1.0 -> 0.0 ao longo do treino
        p = 1.0 - step / a.steps
        if (not a.no_ss) and random.random() < p and step % 4 == 0:
            with torch.no_grad():
                # gerar 32 tokens greedy a partir do prefixo e substituir
                pref = x[:, :32]
                for _ in range(32):
                    lg = model(pref, causal=True)[:, -1, :]
                    nxt = lg.argmax(-1, keepdim=True)
                    pref = torch.cat([pref, nxt], dim=1)
                # usar os tokens GERADOS (pref[:,32:]), nao o prefixo original
                x = torch.cat([x[:, :32], pref[:, 32:], x[:, 64:]], dim=1)
        with torch.autocast(device_type=a.device, dtype=torch.bfloat16) if a.device=="cuda" else torch.autocast(enabled=False):
            lg = model(x, causal=True).reshape(-1, vocab).float()
            loss = F.cross_entropy(lg, y.reshape(-1))
        opt.zero_grad(); loss.backward(); opt.step()
        if step % 400 == 0:
            print(json.dumps({"step": step, "loss": round(float(loss),4),
                              "p": round(p,3)}), flush=True)
    model.eval(); vl = 0.0; vn = 0; corr = 0
    with torch.no_grad():
        for k in range(0, min(200000, len(val)-a.seq-1), a.seq*a.batch):
            xs = [val[k+j:k+j+a.seq] for j in range(0, a.seq*a.batch, a.seq)]
            xs = [z for z in xs if len(z) == a.seq]
            if len(xs) < 2: break
            x = torch.tensor(xs, device=a.device)
            y = torch.tensor([val[k+j+1:k+j+1+a.seq] for j in range(0, a.seq*len(xs), a.seq)], device=a.device)
            lg = model(x, causal=True)
            vl += float(F.cross_entropy(lg.reshape(-1,vocab).float(), y.reshape(-1), reduction="sum"))
            corr += int((lg.argmax(-1) == y).sum())
            vn += y.numel()
    val_loss = vl/max(vn,1)
    r = {"seed": a.seed, "steps": a.steps, "vocab": vocab, "tokens": len(seq),
         "d": a.d, "scheduled_sampling": not a.no_ss,
         "val_loss": round(val_loss,4), "perplexity": round(math.exp(min(val_loss,20)),3),
         "acc": round(corr/max(vn,1),4), "seconds": round(time.perf_counter()-t0,1)}
    if a.ckpt:
        torch.save({"state": model.state_dict(), "vocab": vocab, "d": a.d,
                    "seq": a.seq, "seed": a.seed, "tokenizer": str(TOKDIR)},
                   a.ckpt)
        r["checkpoint"] = a.ckpt
    Path(a.out).write_text(json.dumps(r,indent=2)+"\n")
    print("RESULT "+json.dumps(r), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
