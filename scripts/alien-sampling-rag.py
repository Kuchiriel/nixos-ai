#!/usr/bin/env python3
"""alien-sampling com RAG REAL (HybridSearch) — combinacoes entre lacunas.

Cada hipotese traz os trechos recuperados (path/arxiv/title/snippet) e um
gate a PRE-REGISTRAR. Nao e' evidencia, e' candidato a experimento.
"""
import argparse, itertools, json, time
from pathlib import Path

QUERIES = {
    "compressao": "lossless compression wikipedia arithmetic coding",
    "kv_contexto": "KV cache long context memory attention",
    "quantizacao": "ternary quantization QAT low bit",
    "multimodal": "multimodal vision language audio encoder",
    "loop_depth": "elastic depth loop transformer shared weights",
    "agente": "agent harness tool use memory",
}
TEMPLATES = [
    ("{a} + {b}", "O mecanismo de {A} pode substituir o gargalo de {B} com o mesmo orcamento?"),
    ("{a} -> {b}", "A tecnica de {A} aplicada dentro do pipeline de {B} melhora a metrica compartilhada?"),
    ("{a} x {b}", "Combinar {A} e {B} da um ponto de operacao melhor que cada um isolado?"),
]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--collection", default="jarvis_test_frontier_2026_11")
    ap.add_argument("--top", type=int, default=4)
    a = ap.parse_args()
    from jarvis.core.rag import HybridSearch
    hs = HybridSearch()
    groups = {}
    for tag, q in QUERIES.items():
        hits = hs.search(q, top_k=3, collection=a.collection, use_rerank=False)
        items = []
        for h in hits:
            p = h.payload or {}
            items.append({"tag": tag, "query": q, "path": h.path,
                          "arxiv": p.get("arxiv_id"), "title": p.get("title"),
                          "score": round(float(h.score), 3),
                          "snippet": str(p.get("content", ""))[:260]})
        groups[tag] = items
    TECH = ("arithmetic coding", "kv cache", "entropy", "attention",
            "quantization", "speculative", "retrieval", "compression",
            "multimodal", "elastic", "loop", "sparse", "tokenizer")
    def terms(ev):
        low = (ev["snippet"] + " " + str(ev["title"])).lower()
        return [t for t in TECH if t in low]
    pairs = list(itertools.combinations(QUERIES.items(), 2))
    hyps = []
    for round_no in range(3):
        for (ta, _qa), (tb, _qb) in pairs:
            xs, ys = groups[ta], groups[tb]
            if round_no >= len(xs) or round_no >= len(ys):
                continue
            x, y = xs[round_no], ys[round_no]
            if x["path"] == y["path"]:
                continue
            tx, ty = terms(x), terms(y)
            name, tmpl = TEMPLATES[min(round_no, len(TEMPLATES)-1)]
            hyps.append({
                "id": f"{ta}-{tb}-{round_no}",
                "pair": [ta, tb],
                "template": name,
                "hypothesis": tmpl.format(A=", ".join(tx[:2]) or ta,
                                          B=", ".join(ty[:2]) or tb),
                "shared_terms": sorted(set(tx) & set(ty)),
                "evidence": [x, y],
                "status": "candidate",
                "gate": "PRE-REGISTRAR metrica, baseline, limite e custo ANTES de qualquer experimento",
            })
            if len(hyps) >= a.top:
                break
        if len(hyps) >= a.top:
            break
    out = {"event": "alien_rag", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "collection": a.collection,
           "queries": QUERIES,
           "papers_recuperados": sum(len(v) for v in groups.values()),
           "hypotheses": hyps,
           "note": "candidatos de RAG, nao evidencia; nao reescrever hipoteses antigas"}
    Path(a.out).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"recuperados": out["papers_recuperados"], "hipoteses": len(hyps), "out": a.out}))

if __name__ == "__main__":
    main()
