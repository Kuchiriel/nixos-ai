#!/usr/bin/env python3
"""Probe do primitivo LittleBit-2 (Joint-ITQ) no nosso stack.

Não reproduz PPL do paper (isso exige QAT com GPU e dias de treino). Testa
apenas a parte transferível: o ganho de geometria ao alinhar fatores latentes
com o hipercubo binário antes de binarizar.

Fontes: sintético com espectro power-law (γ=0.4, regime operacional segundo o
paper) e embeddings reais de code_index (scroll somente leitura).

Métricas: λ = 1 - (mean|z| / rms(z))^2 (paper eq. 3.3) e erro de
reconstrução com escala ótima por linha após sign().
"""
from __future__ import annotations
import argparse, json, math, sys, urllib.request
import numpy as np

QDRANT = 'http://127.0.0.1:6333'


def distortion(z: np.ndarray) -> float:
    """λ médio: 1 - (L1/L2)^2 por vetor (paper: menor é melhor)."""
    a = np.abs(z)
    l1 = a.mean(axis=1)
    l2 = np.sqrt((a ** 2).mean(axis=1))
    return float(np.mean(1.0 - (l1 / np.maximum(l2, 1e-12)) ** 2))


def reconstruct_error(z: np.ndarray) -> float:
    """Erro relativo de W ≈ sign(Z) * escala ótima por linha."""
    b = np.sign(z)
    scale = np.sum(z * b, axis=1, keepdims=True) / np.maximum(np.sum(b * b, axis=1, keepdims=True), 1e-12)
    err = np.linalg.norm(z - b * scale) / max(np.linalg.norm(z), 1e-12)
    return float(err)


def random_rotation(d: int, seed: int) -> np.ndarray:
    rng = np.random.default_rng(seed)
    q, _ = np.linalg.qr(rng.normal(size=(d, d)))
    return q


def joint_itq(z: np.ndarray, iters: int = 50, seed: int = 0) -> np.ndarray:
    """Alterna B=sign(ZR) e R=argmin ||B - ZR|| via SVD (paper §3.4)."""
    rng = np.random.default_rng(seed)
    q, _ = np.linalg.qr(rng.normal(size=(z.shape[1], z.shape[1])))
    r = q
    for _ in range(iters):
        b = np.sign(z @ r)
        u, _, vt = np.linalg.svd(b.T @ z, full_matrices=False)
        r = u @ vt
    return z @ r


def synthetic(rows: int = 256, cols: int = 256, rank: int = 32, gamma: float = 0.4) -> np.ndarray:
    rng = np.random.default_rng(42)
    k = np.arange(1, min(rows, cols) + 1, dtype=float)
    s = k ** (-gamma)
    u, _ = np.linalg.qr(rng.normal(size=(rows, rows))[:rows, :min(rows, cols)])
    v, _ = np.linalg.qr(rng.normal(size=(cols, cols))[:cols, :min(rows, cols)])
    w = (u * s) @ v.T
    uw, sw, vw = np.linalg.svd(w, full_matrices=False)
    return uw[:, :rank] * np.sqrt(sw[:rank]), vw[:rank].T * np.sqrt(sw[:rank])


def qdrant_embeddings(limit: int = 600) -> np.ndarray:
    body = json.dumps({'limit': limit, 'with_vector': ['dense'], 'with_payload': False,
                       'filter': {'must_not': [{'key': 'path', 'match': {'any': []}}]}}).encode()
    req = urllib.request.Request(QDRANT + '/collections/code_index/points/scroll',
                                 data=body, headers={'Content-Type': 'application/json'})
    raw = urllib.request.urlopen(req, timeout=60).read()
    pts = json.loads(raw)['result']['points']
    vecs = [p['vector']['dense'] for p in pts if isinstance(p.get('vector'), dict) and 'dense' in p['vector']]
    if len(vecs) < 8:
        raise RuntimeError('poucos vetores retornados')
    return np.asarray(vecs, dtype=float)


def report(name: str, z: np.ndarray, seed: int) -> dict:
    out = {'dataset': name, 'shape': list(z.shape)}
    for label, arr in (
        ('svd_raw', z),
        ('random_rot', z @ random_rotation(z.shape[1], seed)),
        ('joint_itq', joint_itq(z, seed=seed)),
    ):
        out[label] = {'lambda': round(distortion(arr), 4),
                      'reconstruction_error': round(reconstruct_error(arr), 4)}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--qdrant-limit', type=int, default=600)
    ap.add_argument('--write-report', default='')
    a = ap.parse_args()
    u, v = synthetic()
    z = np.concatenate([u, v], axis=0)  # paper: Z = [Û; V̂]
    rows = [report('synthetic_powerlaw_gamma0.4_rank32', z, 0)]
    try:
        emb = qdrant_embeddings(a.qdrant_limit)
        rows.append(report('qdrant_code_index_embeddings', emb, 1))
    except Exception as e:
        rows.append({'dataset': 'qdrant_code_index_embeddings', 'error': type(e).__name__ + ': ' + str(e)[:120]})
    result = {'note': 'teste do primitivo de geometria, sem QAT/PPL',
              'formula_lambda': '1 - (mean|z| / rms(z))^2 (menor e melhor)',
              'datasets': rows}
    out = json.dumps(result, indent=2, ensure_ascii=False)
    print(out)
    if a.write_report:
        with open(a.write_report, 'w') as fh:
            fh.write(out + '\n')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
