#!/usr/bin/env python3
"""Migrate code_index provenance (branch/git_commit) with test-first workflow.

Modes:
  --prepare-test   copy N points from code_index into an isolated jarvis_test_* collection
  --snapshot       create a Qdrant snapshot of the target collection
  --migrate        set branch/git_commit on all points of the target collection
  --indexes        create keyword payload indexes for both fields
  --measure        sample recall@8 and latency with a branch filter
"""
from __future__ import annotations
import argparse, json, subprocess, time, urllib.error, urllib.request

Q = 'http://127.0.0.1:6333'
REPO = '/home/nixos/projects/nixos-ai'


def req(method, path, body=None, timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(Q + path, data=data, method=method,
                               headers={'Content-Type': 'application/json'})
    try:
        with urllib.request.urlopen(r, timeout=timeout) as f:
            return json.loads(f.read())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors='ignore')[:300]
        raise RuntimeError(f'HTTP {e.code} em {method} {path}: {detail}') from e


def provenance():
    branch = subprocess.run(['git', '-C', REPO, 'rev-parse', '--abbrev-ref', 'HEAD'],
                            capture_output=True, text=True, timeout=20).stdout.strip()
    commit = subprocess.run(['git', '-C', REPO, 'rev-parse', 'HEAD'],
                            capture_output=True, text=True, timeout=20).stdout.strip()
    return {'branch': branch or 'unknown', 'git_commit': commit or 'unknown'}


def scroll_all(collection, limit=None, with_vectors=False, with_payload=False):
    out, offset = [], None
    fields = ['dense', 'bm25'] if with_vectors else []
    while True:
        body = {'limit': min(500, limit - len(out)) if limit else 500,
                'with_vector': fields, 'with_payload': with_payload}
        if offset:
            body['offset'] = offset
        res = req('POST', f'/collections/{collection}/points/scroll', body)['result']
        out.extend(res['points'])
        offset = res.get('next_page_offset')
        if not offset or (limit and len(out) >= limit):
            break
    return out[:limit] if limit else out


def prepare_test(collection, n):
    try:
        req('DELETE', f'/collections/{collection}')
    except Exception:
        pass
    info = req('GET', '/collections/code_index')['result']
    params = info['config']['params']
    req('PUT', f'/collections/{collection}', {
        'vectors': params['vectors'],
        'sparse_vectors': params.get('sparse_vectors', {'bm25': {'modifier': 'idf'}})})
    pts = scroll_all('code_index', n, with_vectors=True, with_payload=True)
    for i in range(0, len(pts), 200):
        req('PUT', f'/collections/{collection}/points', {'points': pts[i:i+200]}, 240)
    print(json.dumps({'collection': collection, 'copied': len(pts)}))


def migrate(collection, dry):
    prov = provenance()
    ids = [p['id'] for p in scroll_all(collection, with_vectors=False)]
    if dry:
        print(json.dumps({'collection': collection, 'points': len(ids),
                          'payload': prov, 'dry_run': True}))
        return
    for i in range(0, len(ids), 5000):
        req('POST', f'/collections/{collection}/points/payload',
            {'points': ids[i:i+5000], 'payload': prov}, 240)
    print(json.dumps({'collection': collection, 'updated': len(ids), 'payload': prov}))


def indexes(collection):
    for field in ('branch', 'git_commit'):
        req('PUT', f'/collections/{collection}/index',
            {'field_name': field, 'field_schema': 'keyword'}, 240)
    info = req('GET', f'/collections/{collection}')['result']
    print(json.dumps({'collection': collection,
                      'payload_schema': list(info.get('payload_schema', {}).keys())}))


def measure(collection, n=30):
    pts = scroll_all(collection, n, with_vectors=True, with_payload=True)
    branch = provenance()['branch']
    lat, hit = [], 0
    for p in pts:
        body = {'query': p['vector']['dense'], 'using': 'dense', 'filter': {'must': [
                    {'key': 'branch', 'match': {'value': branch}}]},
                'limit': 8, 'with_payload': False}
        t0 = time.perf_counter()
        res = req('POST', f'/collections/{collection}/points/query', body)['result']['points']
        lat.append((time.perf_counter() - t0) * 1000)
        hit += any(x['id'] == p['id'] for x in res)
    print(json.dumps({'collection': collection, 'queries': len(lat),
                      'recall_at_8': round(hit / max(len(lat), 1), 3),
                      'latency_ms_mean': round(sum(lat) / max(len(lat), 1), 2)}))


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--collection', default='jarvis_test_migrate_provenance')
    ap.add_argument('--limit', type=int, default=1000)
    ap.add_argument('--prepare-test', action='store_true')
    ap.add_argument('--snapshot', action='store_true')
    ap.add_argument('--migrate', action='store_true')
    ap.add_argument('--indexes', action='store_true')
    ap.add_argument('--measure', action='store_true')
    ap.add_argument('--dry-run', action='store_true')
    a = ap.parse_args()
    if a.prepare_test:
        prepare_test(a.collection, a.limit)
    if a.snapshot:
        print(json.dumps(req('POST', f'/collections/{a.collection}/snapshots?wait=true', {}, 600)))
    if a.migrate:
        migrate(a.collection, a.dry_run)
    if a.indexes:
        indexes(a.collection)
    if a.measure:
        measure(a.collection, min(a.limit, 30))


if __name__ == '__main__':
    main()
