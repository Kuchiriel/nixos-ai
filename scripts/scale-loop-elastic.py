#!/usr/bin/env python3
"""ScaleLM elastic (preparado, sem treino) — F130.

2 prelude + 1 bloco recorrente compartilhado + 2 coda; beta aprendido por
token/canal; condicionamento por indice do loop (init zero). Mixed-deep e'
responsabilidade do trainer (F131), nao desta classe.
"""
import argparse, json, math, subprocess

def build_model(vocab, d, heads=None):
    """Instancia o modelo. Chamado apenas na frente de treino, NAO no --check."""
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    import runpy
    Attn = runpy.run_path("/home/nixos/projects/nixos-ai/scripts/scale-loop-ab.py")["Attn"]
    if heads is None:
        heads = 8
        while d % heads:
            heads += 1

    class Recurrent(nn.Module):
        def __init__(self, d, heads):
            super().__init__()
            self.ln1, self.ln2 = nn.LayerNorm(d), nn.LayerNorm(d)
            self.att = Attn(d, heads, False)
            self.ff = nn.Sequential(nn.Linear(d, 4*d), nn.GELU(), nn.Linear(4*d, d))
            self.Wb = nn.Parameter(torch.zeros(d, d))
            self.bb = nn.Parameter(torch.zeros(d))
            self.gamma = nn.Parameter(torch.zeros(1))  # softplus(0) ~= 0.693

        def forward(self, x, causal=False):
            h = x + self.att(self.ln1(x), causal=causal)
            f = self.ff(self.ln2(h))
            beta = torch.sigmoid(h @ self.Wb + self.bb) * F.softplus(self.gamma)
            return x + beta * f

    class ElasticLM(nn.Module):
        def __init__(self, vocab, d, heads):
            super().__init__()
            self.d = d
            self.tok = nn.Embedding(vocab, d)
            self.pos = nn.Embedding(512, d)
            self.pre = nn.ModuleList([AttnBlock(d, heads) for _ in range(2)])
            self.rec = Recurrent(d, heads)
            self.coda = nn.ModuleList([AttnBlock(d, heads) for _ in range(2)])
            self.loop_cond = nn.Embedding(32, d)
            nn.init.zeros_(self.loop_cond.weight)  # init zero, nao perturba checkpoint
            self.ln = nn.LayerNorm(d)
            self.head = nn.Linear(d, vocab)

        def forward(self, x, k=4, causal=False, return_trace=False):
            t = x.shape[1]
            h = self.tok(x) + self.pos(torch.arange(t, device=x.device))
            for blk in self.pre:
                h = blk(h, causal=causal)
            traces = []
            for i in range(k):
                h = self.rec(h + self.loop_cond(torch.tensor(i, device=x.device)), causal=causal)
                if return_trace:
                    traces.append(self.head(self.ln(h)).detach())
            for blk in self.coda:
                h = blk(h, causal=causal)
            out = self.head(self.ln(h))
            return (out, traces) if return_trace else out

    class AttnBlock(nn.Module):
        def __init__(self, d, heads):
            super().__init__()
            self.ln1, self.ln2 = nn.LayerNorm(d), nn.LayerNorm(d)
            self.att = Attn(d, heads, False)
            self.ff = nn.Sequential(nn.Linear(d, 4*d), nn.GELU(), nn.Linear(4*d, d))
        def forward(self, x, causal=False):
            h = x + self.att(self.ln1(x), causal=causal)
            return h + self.ff(self.ln2(h))

    return ElasticLM(vocab, d, heads)

def guard():
    nv = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                        capture_output=True, text=True, timeout=15).stdout.strip().splitlines()
    free = int(nv[0]) if nv else 0
    apps = subprocess.run(["nvidia-smi", "--query-compute-apps=pid", "--format=csv,noheader"],
                          capture_output=True, text=True, timeout=15).stdout.strip().splitlines()
    return free, len([x for x in apps if x.strip()])

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("mode", choices=("check",))
    ap.add_argument("--d", type=int, default=1216)
    ap.add_argument("--vocab", type=int, default=10000)
    a = ap.parse_args()
    free, busy = guard()
    print(json.dumps({"event": "check", "no_train": True,
                      "architecture": "2 prelude + 1 recorrente (k loops) + 2 coda",
                      "beta": "sigmoid(h@Wb+b)*softplus(gamma); Wb,b=0; gamma=0",
                      "loop_cond": "embedding por indice, init zero",
                      "d": a.d, "vocab": a.vocab,
                      "guard_free_mib": free, "guard_other_cuda_jobs": busy,
                      "gate_F91": "intacto — nao renegociado"}))

if __name__ == "__main__":
    main()
