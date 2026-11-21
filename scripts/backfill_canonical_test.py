#!/usr/bin/env python3
"""Validate canonical-field backfill in an isolated jarvis_test_* collection."""
from __future__ import annotations
import hashlib, json, os, time, urllib.request
from datetime import datetime, timezone
from pathlib import Path

Q = 'http://127.0.0.1:6333'
SRC = 'code_index'
DST = 'jarvis_test_canonical_backfill'
FIELDS = ['source_type', 'source_id', 'repo', 'status', 'authority',
          'source_modified_at', 'canonical_path', 'filename']


def req(method, path, body=None, timeout=180):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(Q + path, data=data, method=method,
                               headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return json.loads(f.read())


def scroll(collection, n, with_vectors=True):
    out, offset = [], None
    fields = ['dense', 'bm25'] if with_vectors else []
    while len(out) < n:
        body = {'limit': min(500, n - len(out)), 'with_vector': fields, 'with_payload': True}
        if offset:
            body['offset'] = offset
        res = req('POST', f'/collections/{collection}/points/scroll', body)['result']
        out.extend(res['points'])
        offset = res.get('next_page_offset')
        if not offset:
            break
    return out


def augment(p):
    pl = dict(p.get('payload') or {})
    path = str(pl.get('path', ''))
    if not path:
        return None
    ext = Path(path).suffix.lower().lstrip('.') or 'text'
    code_exts = {'py', 'nix', 'sh', 'js', 'ts', 'rs', 'cpp', 'c', 'go', 'lua', 'java'}
    repo = ''
    parts = path.split('/')
    if len(parts) > 4 and parts[1:3] == ['home', 'nixos'] and parts[3] == 'projects':
        repo = parts[4]
    pl.update({
        'canonical_path': path,
        'filename': os.path.basename(path),
        'source_type': 'code' if ext in code_exts else 'doc',
        'source_id': 'doc:' + hashlib.sha256(path.encode()).hexdigest()[:16],
        'repo': repo or 'unknown',
        'status': 'current',
        'authority': 'source',
    })
    if os.path.exists(path):
        pl['source_modified_at'] = datetime.fromtimestamp(
            os.path.getmtime(path), timezone.utc).isoformat(timespec='seconds')
    return {**p, 'payload': pl}


def coverage(pts):
    return {f: sum(1 for p in pts if (p.get('payload') or {}).get(f) not in (None, '', 0))
            for f in FIELDS}


def recall(pts, key):
    hit = 0
    for p in pts:
        pl = p.get('payload') or {}
        val = pl.get(key)
        if not val:
            continue
        body = {'query': p['vector']['dense'], 'using': 'dense',
                'filter': {'must': [{'key': key, 'match': {'value': val}}]},
                'limit': 8, 'with_payload': False}
        res = req('POST', f'/collections/{DST}/points/query', body)['result']['points']
        hit += any(x['id'] == p['id'] for x in res)
    return round(hit / max(len(pts), 1), 3)


def main():
    n = 2000
    pts = scroll(SRC, n)
    try:
        req('DELETE', f'/collections/{DST}')
    except Exception:
        pass
    params = req('GET', f'/collections/{SRC}')['result']['config']['params']
    req('PUT', f'/collections/{DST}', {'vectors': params['vectors'],
        'sparse_vectors': params.get('sparse_vectors', {'bm25': {'modifier': 'idf'}})})
    for field, schema in (('source_type', 'keyword'), ('source_id', 'keyword'),
                          ('repo', 'keyword'), ('status', 'keyword'),
                          ('authority', 'keyword'), ('source_modified_at', 'datetime')):
        req('PUT', f'/collections/{DST}/index?wait=true',
            {'field_name': field, 'field_schema': schema}, 240)
    for i in range(0, len(pts), 200):
        req('PUT', f'/collections/{DST}/points', {'points': pts[i:i+200]}, 240)
    before = coverage(pts)
    rb, before_source = recall(pts[:30], 'source_type'), recall(pts[:30], 'repo')
    aug = [augment(p) for p in pts]
    aug = [p for p in aug if p]
    for i in range(0, len(aug), 200):
        req('PUT', f'/collections/{DST}/points', {'points': aug[i:i+200]}, 240)
    after = coverage(aug)
    ra, after_source = recall(aug[:30], 'source_type'), recall(aug[:30], 'repo')
    print(json.dumps({'collection': DST, 'points': len(pts),
                      'coverage_before': before, 'coverage_after': after,
                      'recall_source_type': {'before': rb, 'after': ra},
                      'recall_repo': {'before': before_source, 'after': after_source},
                      'production_writes': False}, indent=2, ensure_ascii=False))


if __name__ == '__main__':
    main()
