#!/usr/bin/env python3
"""A/B realista de payload index em colecao isolada jarvis_test_*.

- >10k pontos (default 12000)
- filtro de BAIXA seletividade: branch com ~1/4 da colecao (~3000 matches)
- mede recall@8 e latencia antes/depois de criar indexes keyword
- NUNCA toca colecoes de producao; usa so jarvis_test_index_ab_real
"""
from __future__ import annotations
import argparse, hashlib, json, re, sys, time
from pathlib import Path

REPO = Path('/home/nixos/projects/nixos-ai')
sys.path.insert(0, str(REPO / 'modules/ai/jarvis/src'))
from jarvis.core.knowledge_schema import (  # noqa: E402
    EMBED_DIM, _create_payload_index, build_payload,
)
from jarvis.providers.vector_store import QdrantStore, stable_id  # noqa: E402

COLLECTION = 'jarvis_test_index_ab_real'
BRANCHES = 4
QUERIES = 40

def dense(text: str) -> list[float]:
    out = []
    for i in range(EMBED_DIM):
        h = hashlib.sha256(f'{text}:{i}'.encode()).digest()
        out.append((h[0] - 127.5) / 127.5)
    norm = sum(x * x for x in out) ** 0.5
    return [x / norm for x in out]

def sparse(text: str) -> dict:
    # Qdrant exige indices UNICOS: tokens diferentes podem colidir no modulo.
    seen = {}
    for tok in set(re.findall(r'[a-z0-9]{4,}', text.lower())):
        h = hashlib.blake2b(tok.encode(), digest_size=8).digest()
        idx = int.from_bytes(h[:4], 'big') % 50000
        val = 1.0 + (h[4] % 7) / 10
        seen[idx] = max(seen.get(idx, 0.0), val)
    return {'indices': sorted(seen), 'values': [seen[k] for k in sorted(seen)]}

def rows_for(n: int) -> list[dict]:
    out = []
    for i in range(n):
        commit = hashlib.sha256(f'commit-{i}'.encode()).hexdigest()[:12]
        branch = f'area/{i % BRANCHES}'
        text = f'documento {i} sobre area {branch} commit {commit} termo comum frota'
        out.append({'i': i, 'commit': commit, 'branch': branch, 'text': text})
    return out

def upsert(store, rows):
    batch = []
    for r in rows:
        payload = build_payload(
            {'path': f'jarvis_test/area-{r["i"]}.md', 'content': r['text'],
             'ext': 'md', 'chunk_index': 0},
            knowledge_domain='test', source_type='test', source_id=f'doc:{r["commit"]}',
            canonical_path=f'jarvis_test/area-{r["i"]}.md',
            git_commit=r['commit'], branch=r['branch'], authority='test', status='current')
        batch.append({'id': stable_id('doc', r['commit'], '0'),
                      'vector': {'dense': dense(r['text']), 'bm25': sparse(r['text'])},
                      'payload': payload})
        if len(batch) >= 500:
            store.upsert(COLLECTION, batch)
            batch = []
    if batch:
        store.upsert(COLLECTION, batch)

def measure(store, rows, sample, label):
    hits, lat = 0, []
    for r in sample:
        want = stable_id('doc', r['commit'], '0')
        filt = {'must': [{'key': 'branch', 'match': {'value': r['branch']}}]}
        t0 = time.perf_counter()
        res = store.search_hybrid(COLLECTION, dense(r['text']), sparse(r['text']),
                                  top_k=8, filter=filt)
        lat.append((time.perf_counter() - t0) * 1000)
        if any(str(x.get('id')) == str(want) for x in res):
            hits += 1
    return {'phase': label, 'queries': len(sample),
            'recall_at_8': round(hits / len(sample), 3),
            'latency_ms_mean': round(sum(lat) / len(lat), 2),
            'latency_ms_p95': round(sorted(lat)[int(len(lat) * .95) - 1], 2),
            'latency_ms_max': round(max(lat), 2)}

def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--n', type=int, default=12000)
    ap.add_argument('--queries', type=int, default=QUERIES)
    ap.add_argument('--write-report', default='')
    a = ap.parse_args()
    store = QdrantStore()
    store.ensure_collection(COLLECTION, dim=EMBED_DIM)
    rows = rows_for(a.n)
    upsert(store, rows)
    # amostra deterministica e espalhada
    step = max(1, len(rows) // a.queries)
    sample = rows[::step][:a.queries]
    for field in ('branch', 'git_commit'):
        try:
            store._request('DELETE', f'/collections/{COLLECTION}/index?field_name={field}')
        except Exception:
            pass
    time.sleep(1)
    before = measure(store, rows, sample, 'sem_index')
    for field in ('branch', 'git_commit'):
        _create_payload_index(store, COLLECTION, field, 'keyword')
    time.sleep(2)
    after = measure(store, rows, sample, 'com_index')
    info = store.info(COLLECTION).get('result', {})
    result = {'collection': COLLECTION, 'points': info.get('points_count'),
              'filter_selectivity': f'1/{BRANCHES} (~{a.n // BRANCHES} matches)',
              'samples': a.queries, 'before': before, 'after': after,
              'code_index_points': 275724, 'production_writes': False}
    out = json.dumps(result, indent=2, ensure_ascii=False)
    print(out)
    if a.write_report:
        Path(a.write_report).write_text(out + '\n')
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
