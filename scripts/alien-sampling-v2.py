#!/usr/bin/env python3
"""alien-sampling v2 dinâmico — idea atoms com proveniência do RAG.

Substitui as 6 queries fixas por: seeds amplas -> atoms dinâmicos ->
pares por coerência -> proxy de disponibilidade -> hipóteses com gate.
"""
import argparse, itertools, json, re, time
from pathlib import Path

# Seeds dinamicos: temas NOVOS descobertos no RAG/papers (nao os 6 fixos
# que saturaram em 4 execucoes). Cada seed puxa trechos com proveniencia.
SEEDS = ("elastic latent recurrence loop index conditioning",
         "per-token halting KL convergence fixed point",
         "lossless speculative decoding draft verify",
         "byte EOT tokenizer data efficiency",
         "curated educational corpus filtering threshold",
         "residual normalization massive activations stages")
COLLS = ("code_index", "books", "jarvis_test_frontier_2026_11")
TECH = ("residual", "normalization", "attention", "mlp", "loop", "recurrent",
        "depth", "kv", "cache", "context", "compression", "entropy", "arithmetic",
        "quantization", "ternary", "tokenizer", "byte", "multimodal", "vision",
        "prelude", "coda", "scaling", "exponent", "harness", "memory", "latency")

PHRASES = ("elastic latent recurrence", "per-token halting", "fixed point",
           "lossless speculative", "multi-token", "byte-level", "educational corpus",
           "residual normalization", "massive activations", "scaling exponent",
           "loop index", "KV cache")

def atoms(text):
    low = text.lower()
    out = [t for t in TECH if re.search(r"\b" + re.escape(t) + r"\w*", low)]
    out += [ph for ph in PHRASES if ph in low]
    return sorted(set(out))

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args()
    from jarvis.core.rag import HybridSearch
    hs = HybridSearch()
    pool, seen = [], set()
    for seed in SEEDS:
        for coll in COLLS:
            for h in hs.search(seed, top_k=3, collection=coll, use_rerank=False):
                if h.path in seen: continue
                seen.add(h.path)
                p = h.payload or {}
                txt = str(p.get("content", ""))[:1200]
                pool.append({"seed": seed, "collection": coll, "path": h.path,
                             "arxiv": p.get("arxiv_id"), "title": str(p.get("title") or "")[:120],
                             "atoms": atoms(txt + " " + str(p.get("title") or "")),
                             "snippet": txt[:200]})
    pairs, used = [], set()
    for x, y in itertools.combinations(pool, 2):
        shared = sorted(set(x["atoms"]) & set(y["atoms"]))
        if len(shared) < 2: continue
        key = frozenset(shared)
        if key in used: continue
        used.add(key)
        pairs.append({"shared": shared, "coherence": len(shared), "ev": [x, y]})
    pairs.sort(key=lambda z: -z["coherence"])
    out = []
    for c in pairs:
        if len(out) >= a.top: break
        aa = c["shared"][:2]
        # Proxy antigo usava len(top_k=3) por colecao e saturava em 9.
        # Agora: paths unicos + soma dos scores de rerank (BM25/RRF) em top_k=20.
        hits = []
        for coll in COLLS:
            for h in hs.search(f"{aa[0]} {aa[1]}", top_k=20, collection=coll,
                               use_rerank=False):
                hits.append((h.path, float(h.score)))
        avail_paths = len({path for path, _ in hits})
        avail_score = round(sum(sc for _, sc in hits), 3)
        score = round(c["coherence"] / max(1, avail_paths), 3)
        x, y = c["ev"]
        out.append({"id": f"dyn-{'_'.join(aa)}-{len(out)}", "atoms": c["shared"],
                    "coherence": c["coherence"], "availability_paths": avail_paths,
                    "availability_score_sum": avail_score,
                    "alien_score": score,
                    "hypothesis": f"Combinar '{aa[0]}' de {x['title'] or x['collection']} com '{aa[1]}' de {y['title'] or y['collection']} — ganho mensuravel com orçamento igual?",
                    "sources": [{"collection": z["collection"], "path": z["path"],
                                 "arxiv": z["arxiv"], "snippet": z["snippet"]} for z in [x, y]],
                    "promotion_gate": "PRE-REGISTRAR metrica/baseline/limite/custo antes de promover; alien_score so ordena candidatos",
                    "status": "candidate"})
    res = {"event": "alien_dynamic", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "seeds": list(SEEDS), "pool": len(pool), "hypotheses": out,
           "novos": [h["id"] for h in out if not h["id"].startswith(("kv_", "codigo_", "compressao_"))],
           "note": "idea atoms dinamicos com proveniencia; nao e' evidencia"}
    Path(a.out).write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"pool": len(pool), "hipoteses": len(out), "out": a.out}))

if __name__ == "__main__":
    main()
