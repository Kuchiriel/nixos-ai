#!/usr/bin/env python3
"""A/B: payload index para git_commit/branch em coleção isolada.

Mede recall@8 e latência de busca com filtro antes/depois de criar os indexes.
NUNCA toca `code_index` nem outras coleções de produção: usa somente
`jarvis_test_gitprovenance`. Vetores são sintéticos determinísticos — o teste
valida comportamento do índice/filtro, não qualidade semântica de embeddings.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
import time
from pathlib import Path

REPO = Path("/home/nixos/projects/nixos-ai")
sys.path.insert(0, str(REPO / "modules/ai/jarvis/src"))
from jarvis.core.knowledge_schema import (  # noqa: E402
    EMBED_DIM, _create_payload_index, build_payload,
)
from jarvis.providers.vector_store import QdrantStore, stable_id  # noqa: E402

COLLECTION = "jarvis_test_gitprovenance"
N = 12

def dense(text: str) -> list[float]:
    out = []
    for i in range(EMBED_DIM):
        h = hashlib.sha256(f"{text}:{i}".encode()).digest()
        out.append((h[0] - 127.5) / 127.5)
    norm = sum(x * x for x in out) ** 0.5
    return [x / norm for x in out]

def sparse(text: str) -> dict:
    idx, vals = [], []
    for tok in set(re.findall(r"[a-z0-9]{4,}", text.lower())):
        h = hashlib.blake2b(tok.encode(), digest_size=8).digest()
        idx.append(int.from_bytes(h[:4], "big") % 50000)
        vals.append(1.0 + (h[4] % 7) / 10)
    return {"indices": idx, "values": vals}

def fixture(n=N):
    rows = []
    for i in range(n):
        commit = hashlib.sha256(f"commit-{i}".encode()).hexdigest()[:12]
        branch = f"feature/prova-{i % 4}"
        text = f"documento sintetico {i} sobre filtro de proveniencia {commit} {branch}"
        rows.append({"i": i, "commit": commit, "branch": branch, "text": text})
    return rows

def upsert(store, rows):
    points = []
    for r in rows:
        payload = build_payload(
            {"path": f"jarvis_test/prova-{r['i']}.md", "content": r["text"],
             "ext": "md", "chunk_index": 0},
            knowledge_domain="test", source_type="test", source_id=f"doc:{r['commit']}",
            canonical_path=f"jarvis_test/prova-{r['i']}.md",
            git_commit=r["commit"], branch=r["branch"], authority="test", status="current",
        )
        points.append({"id": stable_id("doc", r["commit"], "0"),
                       "vector": {"dense": dense(r["text"]), "bm25": sparse(r["text"])},
                       "payload": payload})
    store.upsert(COLLECTION, points)

def measure(store, rows, label):
    hits, lat = 0, []
    for r in rows:
        want = stable_id("doc", r["commit"], "0")
        filt = {"must": [{"key": "git_commit", "match": {"value": r["commit"]}}]}
        t0 = time.perf_counter()
        res = store.search_hybrid(COLLECTION, dense(r["text"]), sparse(r["text"]),
                                  top_k=8, filter=filt)
        lat.append((time.perf_counter() - t0) * 1000)
        if any(str(x.get("id")) == str(want) for x in res):
            hits += 1
    return {"phase": label, "recall_at_8": round(hits / len(rows), 3),
            "latency_ms_mean": round(sum(lat) / len(lat), 2),
            "latency_ms_max": round(max(lat), 2)}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--write-report", default="")
    ap.add_argument("--n", type=int, default=N)
    a = ap.parse_args()
    store = QdrantStore()
    store.ensure_collection(COLLECTION, dim=EMBED_DIM)
    rows = fixture(a.n)
    upsert(store, rows)
    # garantir que o índice não exista antes da fase A
    try:
        store._request("DELETE", f"/collections/{COLLECTION}/index?field_name=git_commit")
        store._request("DELETE", f"/collections/{COLLECTION}/index?field_name=branch")
    except Exception:
        pass
    before = measure(store, rows, "sem_index")
    _create_payload_index(store, COLLECTION, "git_commit", "keyword")
    _create_payload_index(store, COLLECTION, "branch", "keyword")
    time.sleep(1)
    after = measure(store, rows, "com_index")
    result = {"collection": COLLECTION, "samples": len(rows), "before": before, "after": after,
              "rule": "somente jarvis_test_*; code_index intacto"}
    out = json.dumps(result, indent=2, ensure_ascii=False)
    print(out)
    if a.write_report:
        Path(a.write_report).write_text(out + "\n")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
