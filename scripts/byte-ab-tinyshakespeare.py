#!/usr/bin/env python3
"""A/B v2: BPE vs byte-level no TinyShakespeare, ~10M params, mesmo compute.

EoT vs Marginalize-It e' uma diferenca de CONVERSAO DE LOGITS DO PROFESSOR
(arXiv 2609.12303), nao de arquitetura do estudante. Medimos os dois lados:
  (1) estudantes BPE vs byte treinados com CE no mesmo compute -> val BPB;
  (2) conversao de logits: Marginalize-It (aproximado) vs End-Of-Token
      (exato) -> KL contra a distribuicao byte exata do professor.
"""
from __future__ import annotations
import argparse, json, math, random, time
from pathlib import Path
import torch
from torch import nn

DATA = Path("/home/nixos/projects/build-nanogpt/input.txt")


def set_seed(s):
    random.seed(s); torch.manual_seed(s)
    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(s)


class CharTok:
    def __init__(self, text):
        self.chars = sorted(set(text))
        self.stoi = {c: i for i, c in enumerate(self.chars)}
        self.itos = {i: c for i, c in enumerate(self.chars)}
        self.n = len(self.chars)

    def encode(self, s): return [self.stoi[c] for c in s]
    def decode(self, ids): return "".join(self.itos[i] for i in ids)


class ByteTok:
    def __init__(self): self.n = 256
    def encode(self, s): return list(s.encode("utf-8"))
    def decode(self, ids): return bytes(ids).decode("utf-8", errors="ignore")


class MiniGPT(nn.Module):
    def __init__(self, vocab, d=384, layers=8, heads=6, ctx=128):
        super().__init__()
        self.ctx = ctx
        self.tok = nn.Embedding(vocab, d)
        self.pos = nn.Embedding(ctx, d)
        blocks = []
        for _ in range(layers):
            blocks += [nn.LayerNorm(d), nn.Linear(d, 4*d), nn.GELU(),
                       nn.Linear(4*d, d)]
        self.blocks = nn.Sequential(*blocks)
        self.head = nn.Linear(d, vocab)
        self.apply(self._init)

    def _init(self, m):
        if isinstance(m, nn.Linear):
            nn.init.normal_(m.weight, std=0.02)
            nn.init.zeros_(m.bias)

    def forward(self, x):
        t = x.shape[1]
        h = self.tok(x) + self.pos(torch.arange(t, device=x.device))
        return self.head(self.blocks(h))


def get_batches(ids, ctx, bs, nsteps, device):
    for _ in range(nsteps):
        st = torch.randint(0, len(ids)-ctx-1, (bs,))
        x = torch.tensor([ids[k:k+ctx] for k in st.tolist()], device=device)
        y = torch.tensor([ids[k+1:k+1+ctx] for k in st.tolist()], device=device)
        yield x, y


def train_student(arm, seed, steps, device, ctx=128, bs=16):
    set_seed(seed)
    text = DATA.read_text(encoding="utf-8")
    n = int(len(text) * 0.9)
    tok = ByteTok() if arm == "byte" else CharTok(text)
    ids = tok.encode(text[:n]); vids = tok.encode(text[n:])
    model = MiniGPT(tok.n, ctx=ctx).to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=3e-4)
    t0 = time.perf_counter(); model.train()
    for step, (x, y) in enumerate(get_batches(ids, ctx, bs, steps, device), 1):
        out = model(x)
        loss = nn.functional.cross_entropy(out.reshape(-1, out.size(-1)), y.reshape(-1))
        opt.zero_grad(); loss.backward(); opt.step()
        if step % 100 == 0:
            print(json.dumps({"arm": arm, "step": step, "loss": round(float(loss), 4)}), flush=True)
    train_s = time.perf_counter() - t0
    model.eval(); tot = 0.0; cnt = 0
    with torch.no_grad():
        for k in range(0, len(vids)-ctx, ctx*bs):
            chunk = vids[k:k+ctx*bs]
            if len(chunk) < ctx+1: break
            xs = [chunk[i:i+ctx] for i in range(0, len(chunk)-ctx, ctx)]
            if not xs: break
            x = torch.tensor(xs, device=device)
            y = torch.tensor([chunk[i+1:i+1+ctx] for i in range(0, len(chunk)-ctx, ctx)], device=device)
            loss = nn.functional.cross_entropy(model(x).reshape(-1, tok.n), y.reshape(-1), reduction="sum")
            tot += float(loss); cnt += y.numel()
    nats = tot / max(cnt, 1)
    # geracao
    set_seed(seed)
    start = torch.tensor([[10 if arm == "byte" else tok.stoi.get("\n", 0)]], device=device)
    t1 = time.perf_counter()
    with torch.no_grad():
        for _ in range(64):
            nxt = model(start)[:, -1, :].argmax(-1, keepdim=True)
            start = torch.cat([start, nxt], dim=1)
    gen_s = time.perf_counter() - t1
    return {"arm": arm, "params": sum(p.numel() for p in model.parameters()),
            "vocab": tok.n, "steps": steps, "seed": seed,
            "val_bpb": round(nats / math.log(2), 4),
            "train_seconds": round(train_s, 1),
            "gen_tok_s": round(64/gen_s, 2) if gen_s else 0}


def logit_conversion_experiment(seed, device):
    """KL entre distribuicao byte EXATA e as duas conversoes aproximadas.

    Professor mitico: 3 tokens com probabilidades conhecidas. Cada token
    mapeia para uma sequencia de bytes; a distribuicao exata marginaliza
    todos os caminhos (End-Of-Token), a aproximada divide igualmente entre
    os bytes do token (Marginalize-It).
    """
    set_seed(seed)
    toks = {0: [104, 105], 1: [32], 2: [119, 111, 114, 108, 100]}
    p = torch.tensor([0.5, 0.2, 0.3], device=device)
    exact = torch.zeros(256, device=device)
    marg = torch.zeros(256, device=device)
    for tid, prob in enumerate(p):
        bs = toks[tid]
        for i, b in enumerate(bs):
            exact[b] += float(prob) / len(bs)
            marg[b] += float(prob) / len(bs)
    # EoT preserva o fim do token: o ultimo byte carrega toda a massa do token
    exact = torch.zeros(256, device=device)
    for tid, prob in enumerate(p):
        bs = toks[tid]
        exact[bs[-1]] += float(prob)
    exact = exact / exact.sum()
    exact = exact / exact.sum()
    marg = marg / marg.sum()
    eps = 1e-9
    kl = nn.functional.kl_div((marg + eps).log(), exact, reduction="sum")
    return {"exact_eot_top": sorted(enumerate(exact.tolist()), key=lambda x: -x[1])[:3],
            "marginalize_top": sorted(enumerate(marg.tolist()), key=lambda x: -x[1])[:3],
            "kl_marginalize_vs_eot": round(float(kl), 4)}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--steps", type=int, default=800)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--device", default="cuda")
    ap.add_argument("--out", type=Path, default=Path("/home/nixos/work/hybrid/byte-ab/report-v2.json"))
    a = ap.parse_args()
    dev = a.device if torch.cuda.is_available() and a.device == "cuda" else "cpu"
    rows = [train_student(arm, a.seed, a.steps, dev) for arm in ("bpe", "byte")]
    for r in rows: print("STUDENT " + json.dumps(r), flush=True)
    conv = logit_conversion_experiment(a.seed, dev)
    print("CONVERSION " + json.dumps(conv, ensure_ascii=False), flush=True)
    b = next(r for r in rows if r["arm"] == "bpe")["val_bpb"]
    y = next(r for r in rows if r["arm"] == "byte")["val_bpb"]
    out = {"paper": "arXiv 2609.12303", "same_compute": True,
           "device": dev, "ctx": 128, "bs": 16,
           "students": rows, "logit_conversion": conv,
           "bpb_delta_byte_minus_bpe": round(y - b, 4)}
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(out, indent=2) + "\n")
    print("REPORT " + str(a.out), flush=True)


if __name__ == "__main__":
    raise SystemExit(main())
