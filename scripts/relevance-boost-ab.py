#!/usr/bin/env python3
"""A/B de boost léxico conteúdo-aware em coleção isolada.

Nada de produção é escrito. Copia pontos reais de code_index para
jarvis_test_relevance, compara o boost atual com um candidato que também
premia palavras da query presentes no CONTEÚDO (não só no filename/path).
"""
from __future__ import annotations
import json, os, re, sys, urllib.request
from pathlib import Path
import numpy as np

HOME = Path('/home/nixos')
REPO = HOME / 'projects/nixos-ai'
sys.path.insert(0, str(REPO / 'modules/ai/jarvis/src'))
from jarvis.core import rag as ragmod  # noqa: E402

Q = 'http://127.0.0.1:6333'
COL = 'jarvis_test_relevance'
N_COPY = 2000
FIXTURE = REPO / 'scripts/rag-eval-queries.jsonl'
BASE = ragmod.apply_legacy_boosts


def req(method, path, body=None, timeout=120):
    data = json.dumps(body).encode() if body is not None else None
    r = urllib.request.Request(Q + path, data=data, method=method,
                               headers={'Content-Type': 'application/json'})
    with urllib.request.urlopen(r, timeout=timeout) as f:
        return json.loads(f.read())

def setup():
    try:
        req('DELETE', f'/collections/{COL}')
    except Exception:
        pass
    req('PUT', f'/collections/{COL}', {
        'vectors': {'dense': {'size': ragmod.EMBED_DIM if hasattr(ragmod, 'EMBED_DIM') else 768,
                              'distance': 'Cosine'}},
        'sparse_vectors': {'bm25': {'modifier': 'idf'}}})
    fixture = [json.loads(l) for l in FIXTURE.read_text().splitlines()
               if l.strip() and not l.lstrip().startswith('#')]
    pts, seen = [], set()
    def add(points):
        for pt in points:
            if pt['id'] not in seen:
                seen.add(pt['id']); pts.append(pt)
    # 1) todos os alvos conhecidos da fixture
    for row in fixture:
        base = os.path.basename(row['expect'])
        r = req('POST', '/collections/code_index/points/scroll',
                {'limit': 12, 'with_vector': ['dense', 'bm25'], 'with_payload': True,
                 'filter': {'must': [{'key': 'path', 'match': {'text': base}}]}})
        add(r['result']['points'])
    # 2) distractores reais da query problemática (somente leitura em produção)
    search = ragmod.HybridSearch()
    target_q = fixture[1]['query']
    for hitset in (
        search.search(target_q, top_k=40, use_rerank=False, diversify=False,
                      collection='code_index'),
    ):
        ids = [str(h.payload.get('document_id') or h.path) for h in hitset]
    #    recuperar por path via scroll (ids internos nao sao expostos em HybridHit)
    for h in search.search(target_q, top_k=40, use_rerank=False, diversify=False,
                           collection='code_index'):
        path = str(h.payload.get('path', ''))
        if not path:
            continue
        r = req('POST', '/collections/code_index/points/scroll',
                {'limit': 4, 'with_vector': ['dense', 'bm25'], 'with_payload': True,
                 'filter': {'must': [{'key': 'path', 'match': {'value': path}}]}})
        add(r['result']['points'])
    # 3) amostra ampla para nao transformar o teste em trivial
    offset = None
    while len(pts) < N_COPY:
        body = {'limit': 500, 'with_vector': ['dense', 'bm25'], 'with_payload': True}
        if offset:
            body['offset'] = offset
        res = req('POST', '/collections/code_index/points/scroll', body)['result']
        add(res['points'])
        offset = res.get('next_page_offset')
        if not offset:
            break
    for i in range(0, len(pts), 200):
        req('PUT', f'/collections/{COL}/points', {'points': pts[i:i+200]}, 180)
    return len(pts)

def candidate(query, hits):
    scored = BASE(query, hits)
    words = {w for w in re.findall(r'\w+', query.lower()) if len(w) > 3}
    out = []
    for h in scored:
        h = dict(h)
        content = str((h.get('payload') or {}).get('content', '')).lower()
        bonus = min(6.0, 1.5 * sum(1 for w in words if w in content))
        h['score'] += bonus
        out.append(h)
    out.sort(key=lambda x: x['score'], reverse=True)
    return out

def main():
    n = setup()
    rows = [json.loads(l) for l in FIXTURE.read_text().splitlines()
            if l.strip() and not l.lstrip().startswith('#')]
    search = ragmod.HybridSearch()
    results = {}
    for label, fn in (('baseline', BASE), ('content_bonus', candidate)):
        ragmod.apply_legacy_boosts = fn
        ranks = []
        for row in rows:
            hits = search.search(row['query'], top_k=8, use_rerank=False,
                                 diversify=False, collection=COL)
            paths = [str(h.path) for h in hits]
            ranks.append(next((i + 1 for i, p in enumerate(paths) if row['expect'] in p), None))
        found = [r for r in ranks if r]
        results[label] = {'recall': round(len(found) / len(ranks), 3),
                          'mrr': round(sum(1 / r for r in found) / len(ranks), 3),
                          'ranks': ranks}
    ragmod.apply_legacy_boosts = BASE
    target = rows[1]
    out = {'collection': COL, 'points': n, 'queries': len(rows),
           'target_query': target['query'], 'target_expect': target['expect'],
           'results': results, 'production_writes': False}
    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0

if __name__ == '__main__':
    raise SystemExit(main())
