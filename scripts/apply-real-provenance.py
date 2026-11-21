#!/usr/bin/env python3
"""Apply per-file real git provenance to code_index (test-first, snapshot-safe)."""
from __future__ import annotations
import argparse, collections, json, subprocess, time, urllib.request

Q = 'http://127.0.0.1:6333'
MAP = '/home/nixos/projects/nixos-ai/scripts/provenance-map.json'
REPO = '/home/nixos/projects/nixos-ai'


def req(method, path, body=None, timeout=300):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(Q + path, data=data, method=method,
                               headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return json.loads(f.read())


def scroll(collection, n=None, with_payload=True, with_vectors=False):
    out, offset = [], None
    fields = ['dense', 'bm25'] if with_vectors else []
    while True:
        limit = min(1000, n - len(out)) if n else 1000
        if limit <= 0:
            break
        body = {'limit': limit, 'with_vector': fields, 'with_payload': with_payload}
        if offset:
            body['offset'] = offset
        res = req('POST', f'/collections/{collection}/points/scroll', body)['result']
        out.extend(res['points'])
        offset = res.get('next_page_offset')
        if not offset:
            break
    return out


def repo_root(p):
    parts = p.split('/')
    if len(parts) >= 5 and parts[1:3] == ['home', 'nixos'] and parts[3] == 'projects':
        return '/'.join(parts[:5])
    return ''


def load_map():
    return json.load(open(MAP))


def branch_for(path, mapping):
    root = repo_root(path)
    if not root or path not in mapping:
        return 'unknown'
    try:
        b = subprocess.run(['git', '-C', root, 'rev-parse', '--abbrev-ref', 'HEAD'],
                           capture_output=True, text=True, timeout=10).stdout.strip()
        return b or 'unknown'
    except Exception:
        return 'unknown'


def target_payload(p, mapping):
    commit = mapping.get(p.get('payload', {}).get('path', ''))
    return {'git_commit': commit or 'unknown',
            'branch': branch_for(p.get('payload', {}).get('path', ''), mapping)}


def prepare_test(collection, n=2000):
    try:
        req('DELETE', f'/collections/{collection}')
    except Exception:
        pass
    params = req('GET', '/collections/code_index')['result']['config']['params']
    req('PUT', f'/collections/{collection}', {
        'vectors': params['vectors'],
        'sparse_vectors': params.get('sparse_vectors', {'bm25': {'modifier': 'idf'}})})
    pts = scroll('code_index', n, with_vectors=True, with_payload=True)
    for i in range(0, len(pts), 200):
        req('PUT', f'/collections/{collection}/points', {'points': pts[i:i+200]}, 240)
    print(json.dumps({'collection': collection, 'copied': len(pts)}))


def apply(collection, dry):
    mapping = load_map()
    pts = scroll(collection, with_payload=True)
    groups = collections.defaultdict(list)
    for p in pts:
        pl = target_payload(p, mapping)
        groups[(pl['branch'], pl['git_commit'])].append(p['id'])
    if dry:
        print(json.dumps({'collection': collection, 'points': len(pts),
                          'groups': len(groups), 'dry_run': True,
                          'sample': list(groups.items())[:3]}, ensure_ascii=False))
        return
    updated = 0
    for (branch, commit), ids in groups.items():
        for i in range(0, len(ids), 5000):
            req('POST', f'/collections/{collection}/points/payload?wait=true',
                {'points': ids[i:i+5000],
                 'payload': {'branch': branch, 'git_commit': commit}}, 300)
            updated += len(ids[i:i+5000])
    print(json.dumps({'collection': collection, 'updated': updated, 'groups': len(groups)}))


def measure(collection, n=30):
    pts = scroll(collection, n, with_vectors=True, with_payload=True)
    hit = 0
    lat = []
    for p in pts:
        pl = p.get('payload') or {}
        commit = pl.get('git_commit', '')
        body = {'query': p['vector']['dense'], 'using': 'dense',
                'filter': {'must': [{'key': 'git_commit', 'match': {'value': commit}}]},
                'limit': 8, 'with_payload': False}
        t0 = time.perf_counter()
        res = req('POST', f'/collections/{collection}/points/query', body)['result']['points']
        lat.append((time.perf_counter() - t0) * 1000)
        hit += any(x['id'] == p['id'] for x in res)
    print(json.dumps({'collection': collection, 'queries': len(pts),
                      'recall_at_8': round(hit / max(len(pts), 1), 3),
                      'latency_ms': round(sum(lat) / max(len(lat), 1), 2)}))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--collection', default='jarvis_test_real_provenance')
    ap.add_argument('--limit', type=int, default=2000)
    ap.add_argument('--prepare-test', action='store_true')
    ap.add_argument('--snapshot', action='store_true')
    ap.add_argument('--apply', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--measure', action='store_true')
    a = ap.parse_args()
    if a.prepare_test:
        prepare_test(a.collection, a.limit)
    if a.snapshot:
        print(json.dumps(req('POST', f'/collections/{a.collection}/snapshots?wait=true', {}, 600)))
    if a.apply:
        apply(a.collection, a.dry_run)
    if a.measure:
        measure(a.collection, min(a.limit, 30))


if __name__ == '__main__':
    main()
