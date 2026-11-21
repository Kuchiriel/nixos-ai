#!/usr/bin/env python3
"""A/B: rotação Joint-ITQ antes da binarização nativa do Qdrant.

Somente coleções jarvis_test_*. Nada de produção é escrito.
Ground truth: vizinho mais próximo em espaço denso original entre os pontos
indexados. Compara recall@8 com binarização (rescore=false) para vetores
originais vs rotacionados, mais baseline denso.
"""
from __future__ import annotations
import argparse, json, sys, urllib.request
import numpy as np

Q = 'http://127.0.0.1:6333'
PLAIN, ROT = 'jarvis_test_itq_plain', 'jarvis_test_itq_rot'
DIM = 768
N_INDEX, N_QUERY = 900, 100

def req(method, path, body=None, timeout=90):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(Q + path, data=data, method=method,
                               headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return json.loads(f.read())

def get_embeddings(n=600):
    body = {'limit': n, 'with_vector': ['dense'], 'with_payload': False}
    pts = req('POST', '/collections/code_index/points/scroll', body, 120)['result']['points']
    v = np.asarray([p['vector']['dense'] for p in pts if isinstance(p.get('vector'), dict)
                    and 'dense' in p['vector']], dtype=float)
    v /= np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)
    return v

def joint_itq(z, iters=50, seed=1):
    rng = np.random.default_rng(seed)
    q, _ = np.linalg.qr(rng.normal(size=(z.shape[1], z.shape[1])))
    r = q
    for _ in range(iters):
        b = np.sign(z @ r)
        u, _, vt = np.linalg.svd(b.T @ z, full_matrices=False)
        r = u @ vt
    return r

def create(name):
    try:
        req('DELETE', f'/collections/{name}')
    except Exception:
        pass
    req('PUT', f'/collections/{name}', {
        'vectors': {'size': DIM, 'distance': 'Cosine'},
        'quantization_config': {'binary': {'memory': 'pinned'}}})

def upsert(name, vecs, ids):
    batch = []
    for i, (v, pid) in enumerate(zip(vecs, ids)):
        batch.append({'id': int(pid), 'vector': v.tolist()})
        if len(batch) >= 200:
            req('PUT', f'/collections/{name}/points', {'points': batch}, 120)
            batch = []
    if batch:
        req('PUT', f'/collections/{name}/points', {'points': batch}, 120)

RESCORE = False

def search(name, v, ignore):
    body = {'query': v.tolist(), 'limit': 8, 'with_payload': False,
            'params': {'quantization': {'ignore': ignore, 'rescore': RESCORE, 'oversampling': 2.0 if RESCORE else 1.0}}}
    res = req('POST', f'/collections/{name}/points/query', body, 60)['result']['points']
    return [int(p['id']) for p in res]

def main():
    global RESCORE
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--rescore', action='store_true')
    a = ap.parse_args()
    RESCORE = a.rescore
    allv = get_embeddings(1100)
    indexed, queries = allv[:N_INDEX], allv[N_INDEX:N_INDEX + N_QUERY]
    ids = list(range(len(indexed)))
    r = joint_itq(indexed)
    # verify rotation preserves distances (orthogonal)
    ortho_err = float(np.linalg.norm(r.T @ r - np.eye(DIM)))
    create(PLAIN); upsert(PLAIN, indexed, ids)
    create(ROT); upsert(ROT, indexed @ r, ids)
    dense_hits = bin_hits = rot_hits = 0
    for qv in queries:
        sims = indexed @ qv
        truth = ids[int(np.argmax(sims))]
        dense_hits += truth in search(PLAIN, qv, True)
        bin_hits += truth in search(PLAIN, qv, False)
        rot_hits += truth in search(ROT, qv @ r, False)
    out = {'collections': [PLAIN, ROT], 'indexed': len(indexed), 'queries': len(queries),
           'orthogonality_error': round(ortho_err, 6),
           'recall_at_8': {'dense': round(dense_hits / len(queries), 3),
                           'binary_plain': round(bin_hits / len(queries), 3),
                           'binary_itq_rot': round(rot_hits / len(queries), 3)},
           'rescore': RESCORE, 'production_writes': False}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
