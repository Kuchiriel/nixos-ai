#!/usr/bin/env python3
"""H3 (22/11): ITQ + binarizacao nativa do Qdrant com 1000 queries.

Evolucao do itq-binary-rag-ab.py (100 queries): mede hits POR QUERY para
bootstrap pareado. Gate pre-registrado: delta recall@8 >= 0.02 e p < 0.05.
Somente colecoes jarvis_test_h3_*; leitura de code_index; nada em producao.
"""
from __future__ import annotations
import argparse, json, urllib.request
import numpy as np

Q = "http://127.0.0.1:6333"
PLAIN, ROT = "jarvis_test_h3_plain", "jarvis_test_h3_rot"
DIM = 768
N_INDEX, N_QUERY = 900, 1000

def req(method, path, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(Q + path, data=data, method=method,
                               headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return json.loads(f.read())

def get_embeddings(n):
    pts = req("POST", "/collections/code_index/points/scroll",
              {"limit": n, "with_vector": ["dense"], "with_payload": False}, 180)["result"]["points"]
    v = np.asarray([p["vector"]["dense"] for p in pts
                    if isinstance(p.get("vector"), dict) and "dense" in p["vector"]], dtype=float)
    v /= np.maximum(np.linalg.norm(v, axis=1, keepdims=True), 1e-12)
    return v

def joint_itq(z, iters=50, seed=1):
    rng = np.random.default_rng(seed)
    _, _, vt = np.linalg.svd(z, full_matrices=False)
    r = vt.T
    for _ in range(iters):
        b = np.sign(z @ r)
        u, _, vt = np.linalg.svd(b.T @ z, full_matrices=False)
        r = u @ vt
    return r

def create(name):
    try:
        req("DELETE", f"/collections/{name}")
    except Exception:
        pass
    req("PUT", f"/collections/{name}", {
        "vectors": {"size": DIM, "distance": "Cosine"},
        "quantization_config": {"binary": {"memory": "pinned"}}})

def upsert(name, vecs, ids):
    batch = []
    for v, pid in zip(vecs, ids):
        batch.append({"id": int(pid), "vector": v.tolist()})
        if len(batch) >= 200:
            req("PUT", f"/collections/{name}/points", {"points": batch}, 120)
            batch = []
    if batch:
        req("PUT", f"/collections/{name}/points", {"points": batch}, 120)

def search(name, v):
    body = {"query": v.tolist(), "limit": 8, "with_payload": False,
            "params": {"quantization": {"ignore": False, "rescore": False}}}
    res = req("POST", f"/collections/{name}/points/query", body, 60)["result"]["points"]
    return [int(p["id"]) for p in res]

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bootstrap", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=42)
    a = ap.parse_args()
    allv = get_embeddings(N_INDEX + N_QUERY + 50)
    indexed, queries = allv[:N_INDEX], allv[N_INDEX:N_INDEX + N_QUERY]
    ids = list(range(len(indexed)))
    r = joint_itq(indexed)
    ortho = float(np.linalg.norm(r.T @ r - np.eye(DIM)))
    create(PLAIN); upsert(PLAIN, indexed, ids)
    create(ROT); upsert(ROT, indexed @ r, ids)
    plain = np.zeros(len(queries), dtype=np.int8)
    rot = np.zeros(len(queries), dtype=np.int8)
    for i, qv in enumerate(queries):
        truth = ids[int(np.argmax(indexed @ qv))]
        plain[i] = truth in search(PLAIN, qv)
        rot[i] = truth in search(ROT, qv @ r)
        if (i + 1) % 200 == 0:
            print(f"progresso {i+1}/{len(queries)}", flush=True)
    delta = float(rot.mean() - plain.mean())
    rng = np.random.default_rng(a.seed)
    diffs = []
    n = len(queries)
    for _ in range(a.bootstrap):
        idx = rng.integers(0, n, n)
        diffs.append(rot[idx].mean() - plain[idx].mean())
    diffs = np.asarray(diffs)
    p = float((diffs <= 0).mean())
    lo, hi = np.percentile(diffs, [2.5, 97.5])
    out = {"schema": 1, "collections": [PLAIN, ROT], "indexed": len(indexed),
           "queries": n, "rescore": False, "orthogonality_error": round(ortho, 6),
           "recall_at_8": {"binary_plain": round(float(plain.mean()), 4),
                           "binary_itq_rot": round(float(rot.mean()), 4),
                           "delta": round(delta, 4)},
           "bootstrap": {"n": a.bootstrap, "ci95": [round(float(lo), 4), round(float(hi), 4)],
                         "p_one_sided": round(p, 4)},
           "gate": {"delta_ge_0_02": delta >= 0.02, "p_lt_0_05": p < 0.05,
                    "PASS": bool(delta >= 0.02 and p < 0.05)},
           "production_writes": False}
    print("H3_RESULT " + json.dumps(out, indent=2, ensure_ascii=False))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
