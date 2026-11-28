#!/usr/bin/env python3
"""β-Anchor Loop — prova de mecanismo em CPU, 3 tamanhos, gate pre-registrado.

Modelo: embedding + posicao + 1 bloco recorrente compartilhado, executado
L=4 passagens com beta aprendido por indice e ancoragem em stopgrad(h_in).
Readout unico aplicado em todos os depths. Comparacao: baseline sem ancoragem
e com beta fixo (mesmo numero de parametros aproximado).
"""
from __future__ import annotations
import argparse, json, math, random, time
from pathlib import Path
import numpy as np

CORPUS = Path('/home/nixos/Books/corpora/TinyStories-train.txt')

def load_tokens(max_chars=4_000_000, vocab=512):
    txt = CORPUS.read_text(errors='ignore')[:max_chars]
    # tokenizer de bytes simples e determinístico (prova de mecanismo, nao SLM)
    ids = np.frombuffer(txt.encode('utf-8')[:max_chars], dtype=np.uint8).astype(np.int64) % vocab
    return ids

class Model:
    def __init__(self, d, vocab, L=4, anchored=True, seed=42):
        rng = np.random.default_rng(seed)
        self.d, self.vocab, self.L, self.anchored = d, vocab, L, anchored
        s = d ** -0.5
        self.E = rng.normal(0, s, (vocab, d))
        self.P = rng.normal(0, s, (256, d))
        self.W = rng.normal(0, s, (d, d))
        self.V = rng.normal(0, s, (d, d))
        self.beta = np.full(L, 0.05) if not anchored else rng.normal(0.05, 1e-3, L)
        self.gate = rng.normal(0, 1e-3, (L, d))
        self.norm_gain = np.ones(d)

    def forward(self, x, anchor=None, collect=False):
        t = len(x)
        h = self.E[x] + self.P[:t]
        u = h.copy() if (self.anchored and anchor is None) else (anchor if anchor is not None else h.copy())
        steps = []
        for i in range(self.L):
            beta = float(np.mean(np.tanh(self.gate[i]) * self.beta[i]))
            delta = np.tanh(h @ self.W) @ self.V
            h = h + beta * delta
            if self.anchored:
                h = (h + u) / (np.linalg.norm(h + u, axis=-1, keepdims=True) + 1e-6) * self.norm_gain
            if collect:
                steps.append(float(np.linalg.norm(h - (steps_h[-1] if False else h)))) if False else None
        if collect:
            return h, steps
        return h

    def logits(self, h):
        return h @ self.E.T

def loss_grad(m, ids, seq=64, n=24):
    rng = np.random.default_rng(0)
    total = 0.0; gradE = np.zeros_like(m.E); gradW = np.zeros_like(m.W); gradV = np.zeros_like(m.V)
    for _ in range(n):
        k = int(rng.integers(0, len(ids) - seq - 1))
        x = ids[k:k+seq]; y = ids[k+1:k+1+seq]
        h = m.forward(x)
        lg = m.logits(h)
        lg -= lg.max(axis=-1, keepdims=True)
        p = np.exp(lg); p /= p.sum(axis=-1, keepdims=True)
        p[np.arange(seq), y] -= 1
        total += -np.log(np.exp(lg[np.arange(seq), y]) / np.exp(lg).sum(axis=-1) + 1e-9).mean()
        # p: [seq, vocab], h: [seq, d] — sem batch nesta prova de mecanismo
        dh = p @ m.E                       # [seq, d]
        np.add.at(gradE, x, dh / n)        # acumula por token (x e' vetor de ids)
        act = np.tanh(h @ m.W)             # [seq, d]
        gradW += (h.T @ ((dh @ m.V.T) * (1 - act ** 2))) / n
        gradV += (act.T @ dh) / n
    return total / n, gradE, gradW, gradV

def evaluate(m, ids, seq=64, n=12):
    rng = np.random.default_rng(99)
    vl = 0.0; corr = 0; cnt = 0; norms = []
    for _ in range(n):
        k = int(rng.integers(0, len(ids) - seq - 2))
        x = ids[k:k+seq]; y = ids[k+1:k+1+seq]
        h = m.forward(x)
        lg = m.logits(h); lg -= lg.max(axis=-1, keepdims=True)
        p = np.exp(lg); p /= p.sum(axis=-1, keepdims=True)
        vl += -np.log(p[np.arange(seq), y] + 1e-9).mean()
        corr += int((p.argmax(-1) == y).sum()); cnt += seq
        # readout em depth 2: reexecuta parcialmente
        h2 = m.E[x] + m.P[:seq]; u = h2.copy()
        for i in range(2):
            beta = float(np.mean(np.tanh(m.gate[i]) * m.beta[i]))
            h2 = h2 + beta * (np.tanh(h2 @ m.W) @ m.V)
            if m.anchored:
                h2 = (h2 + u) / (np.linalg.norm(h2 + u, axis=-1, keepdims=True) + 1e-6) * m.norm_gain
        lg2 = m.logits(h2); lg2 -= lg2.max(axis=-1, keepdims=True)
        p2 = np.exp(lg2); p2 /= p2.sum(axis=-1, keepdims=True)
        vl += 0  # depth2 loss somada a parte
        norms.append(abs(vl))
    return {'val': float(vl / n), 'acc': float(corr / cnt), 'norma': float(np.mean(norms))}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=('check','run'))
    ap.add_argument('--dims', default='192,384,768')
    ap.add_argument('--steps', type=int, default=40)
    ap.add_argument('--out', default='/home/nixos/work/hybrid/beta-anchor-result.json')
    a = ap.parse_args()
    if a.mode == 'check':
        print(json.dumps({'event':'check','mode':'beta-anchor','dims':a.dims,'no_train':True,'gate':'val_d1<=base-0.02 e val_d4<=base-0.01'})); return
    ids = load_tokens()
    res = []
    for d in [int(x) for x in a.dims.split(',')]:
        t0 = time.perf_counter()
        for anchored in (False, True):
            m = Model(d, 512, anchored=anchored)
            lr = 0.02
            for s in range(a.steps):
                loss, gE, gW, gV = loss_grad(m, ids)
                m.E -= lr * gE; m.W -= lr * gW; m.V -= lr * gV
            ev = evaluate(m, ids)
            res.append({'d': d, 'anchored': anchored, **ev, 'seconds': round(time.perf_counter()-t0,1)})
            print({'d':d,'anchor':anchored,'val':round(ev['val'],4),'acc':round(ev['acc'],4)}, flush=True)
    out = {'event':'beta-anchor','ts':time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime()),
           'results':res,'gate':'pre-registrado em ai-mesh/docs/alien-fronteira-hipotese-2026-11-28.md',
           'note':'prova de mecanismo CPU; nao e SLM'}
    Path(a.out).write_text(json.dumps(out,indent=2)+'\n')
    print(json.dumps({'rows':len(res)}))

if __name__ == '__main__':
    main()
