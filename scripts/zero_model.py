#!/usr/bin/env python3
"""zero_model.py — construir um Transformer do zero, um componente por vez.

Sem pesos externos, sem frameworks de alto nivel. Cada estagio tem um
teste de forma/gradiente que roda antes de seguir para o proximo.
Uso: python3 zero_model.py --stage {perceptron,attention,transformer}
"""
from __future__ import annotations
import argparse, json, math
import torch
from torch import nn


class Perceptron(nn.Module):
    """y = gelu(x W + b) — menor bloco que ainda aprende algo."""
    def __init__(self, d_in=8, d_out=4):
        super().__init__()
        self.W = nn.Parameter(torch.randn(d_in, d_out) * 0.1)
        self.b = nn.Parameter(torch.zeros(d_out))

    def forward(self, x):
        return torch.nn.functional.gelu(x @ self.W + self.b)


class SelfAttention(nn.Module):
    """QKV + softmax escalado, escrito a mao (sem nn.MultiheadAttention)."""
    def __init__(self, d=16, heads=4):
        super().__init__()
        assert d % heads == 0
        self.d, self.h, self.dh = d, heads, d // heads
        self.Wq = nn.Parameter(torch.randn(d, d) * 0.02)
        self.Wk = nn.Parameter(torch.randn(d, d) * 0.02)
        self.Wv = nn.Parameter(torch.randn(d, d) * 0.02)
        self.Wo = nn.Parameter(torch.randn(d, d) * 0.02)

    def forward(self, x):
        b, t, d = x.shape
        q = (x @ self.Wq).view(b, t, self.h, self.dh).transpose(1, 2)
        k = (x @ self.Wk).view(b, t, self.h, self.dh).transpose(1, 2)
        v = (x @ self.Wv).view(b, t, self.h, self.dh).transpose(1, 2)
        att = torch.softmax(q @ k.transpose(-2, -1) / math.sqrt(self.dh), -1)
        out = (att @ v).transpose(1, 2).contiguous().view(b, t, d)
        return out @ self.Wo


class TransformerBlock(nn.Module):
    """Pre-LN: LN -> atenção -> residual -> LN -> FFN -> residual."""
    def __init__(self, d=16, heads=4):
        super().__init__()
        self.ln1 = nn.LayerNorm(d)
        self.att = SelfAttention(d, heads)
        self.ln2 = nn.LayerNorm(d)
        self.ff = nn.Sequential(nn.Linear(d, 4*d), nn.GELU(), nn.Linear(4*d, d))

    def forward(self, x):
        x = x + self.att(self.ln1(x))
        x = x + self.ff(self.ln2(x))
        return x


class TinyLM(nn.Module):
    """Embedding + posição + N blocos + head — treinável do zero."""
    def __init__(self, vocab=65, d=64, layers=2, heads=4, ctx=128):
        super().__init__()
        self.ctx = ctx
        self.tok = nn.Embedding(vocab, d)
        self.pos = nn.Embedding(ctx, d)
        self.blocks = nn.ModuleList([TransformerBlock(d, heads) for _ in range(layers)])
        self.ln = nn.LayerNorm(d)
        self.head = nn.Linear(d, vocab)

    def forward(self, x):
        t = x.shape[1]
        h = self.tok(x) + self.pos(torch.arange(t, device=x.device))
        for blk in self.blocks:
            h = blk(h)
        return self.head(self.ln(h))


def check(stage):
    torch.manual_seed(42)
    if stage == "perceptron":
        m = Perceptron()
        x = torch.randn(4, 8)
        y = m(x)
        y.sum().backward()
        assert y.shape == (4, 4), y.shape
        assert m.W.grad is not None and m.W.grad.abs().sum() > 0
        return {"stage": stage, "shape": list(y.shape),
                "grad_norm": round(float(m.W.grad.norm()), 4),
                "params": sum(p.numel() for p in m.parameters())}
    if stage == "attention":
        m = SelfAttention()
        x = torch.randn(2, 7, 16)
        y = m(x)
        y.sum().backward()
        assert y.shape == x.shape
        assert m.Wq.grad is not None
        return {"stage": stage, "shape": list(y.shape),
                "grad_norm": round(float(m.Wq.grad.norm()), 4),
                "params": sum(p.numel() for p in m.parameters())}
    m = TinyLM(vocab=65, d=64, layers=2, heads=4)
    x = torch.randint(0, 65, (2, 32))
    y = m(x)
    loss = nn.functional.cross_entropy(y.reshape(-1, 65), x.reshape(-1))
    loss.backward()
    assert y.shape == (2, 32, 65)
    return {"stage": stage, "shape": list(y.shape),
            "loss": round(float(loss), 4),
            "params": sum(p.numel() for p in m.parameters())}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--stage", default="perceptron",
                    choices=["perceptron", "attention", "transformer"])
    a = ap.parse_args()
    print(json.dumps(check(a.stage), ensure_ascii=False))


if __name__ == "__main__":
    raise SystemExit(main())
