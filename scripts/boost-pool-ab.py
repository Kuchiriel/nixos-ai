#!/usr/bin/env python3
"""A/B final: profundidade do pool x boost de resposta, na coleção isolada."""
import json, re, sys, time
from pathlib import Path
REPO = Path('/home/nixos/projects/nixos-ai')
sys.path.insert(0, str(REPO / 'modules/ai/jarvis/src'))
from jarvis.core import rag as R
COL = 'jarvis_test_relevance'
BASE = R.apply_legacy_boosts
FIX = [json.loads(l) for l in (REPO / 'scripts/rag-eval-queries.jsonl').read_text().splitlines()
       if l.strip() and not l.lstrip().startswith('#')]

def answer_boost(query, hits):
    out = BASE(query, hits)
    ql = query.lower()
    if not ('how many' in ql or 'how much' in ql):
        return out
    for h in out:
        c = str((h.get('payload') or {}).get('content', ''))
        words = {w for w in re.findall(r'\w+', ql) if len(w) > 4 and w not in ('many','much','does','which')}
        if any(re.search(re.escape(w) + r'[_\s-]?(?:size|length|chars?|count)\s*=\s*\d+', c, re.I)
               for w in words):
            h['score'] += 12.0
    out.sort(key=lambda h: h['score'], reverse=True)
    return out

s = R.HybridSearch()
orig = s._store.search_hybrid
res = {}
for factor in (4, 20):
    def wrapped(name, dense, sparse, **kw):
        kw['top_k'] = int(kw.get('top_k', 8) * factor / 4)
        return orig(name, dense, sparse, **kw)
    s._store.search_hybrid = wrapped
    for label, fn in (('baseline', BASE), ('answer', answer_boost)):
        R.apply_legacy_boosts = fn
        ranks, t0 = [], time.perf_counter()
        for row in FIX:
            hits = s.search(row['query'], top_k=8, use_rerank=False, diversify=False,
                            collection=COL, dense_limit=2000, sparse_limit=2000)
            paths = [str(h.path) for h in hits]
            ranks.append(next((i+1 for i,p in enumerate(paths) if row['expect'] in p), None))
        ms = (time.perf_counter()-t0)*1000/len(FIX)
        found = [r for r in ranks if r]
        res[f'pool{factor}_{label}'] = {'recall':round(len(found)/len(ranks),3),
            'mrr':round(sum(1/r for r in found)/len(ranks),3),
            'target_rank':ranks[1],'ms_per_query':round(ms,1)}
s._store.search_hybrid = orig
R.apply_legacy_boosts = BASE
print(json.dumps({'collection':COL,'results':res,'production_writes':False},
                 indent=2,ensure_ascii=False))
