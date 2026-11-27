#!/usr/bin/env python3
"""alien-sampling v2 — idea atoms + coerencia + proxy de disponibilidade.

Diferenca da v1: nao devolve template vazio. Extrai atoms com proveniencia
dos trechos do RAG, pontua coerencia (atoms compartilhados) e disponibilidade
(quantos trechos o RAG devolve para a combinacao dos atoms — pouco = alien).
Nao e' o modelo treinado do Alien Science; e' um proxy barato e auditavel.
"""
import argparse, itertools, json, re, time
from pathlib import Path

QUERIES = {
    "codigo_llm": "ScaleLM 8 blocos loop recorrente beta normalizacao F79",
    "compressao": "lossless compression arithmetic coding tufazip",
    "kv_contexto": "KV cache compression long context memory",
    "quantizacao": "ternary quantization QAT low bit",
    "multimodal": "multimodal vision language local hardware",
    "transcricoes": "looped transformer recurrent depth Raschka KV cache compression",
}
ATOMS = ("loop", "recurrent", "depth", "kv", "cache", "compression", "entropy",
         "arithmetic", "quantization", "ternary", "multimodal", "vision",
         "normalization", "residual", "attention", "harness", "browser",
         "memory", "scaling", "token", "weight", "data", "latency", "retrieval")
COLLS = ("code_index", "books", "jarvis_test_frontier_2026_11")

def atoms(text):
    low = text.lower()
    return sorted(a for a in ATOMS if re.search(r"\b" + re.escape(a) + r"\w*", low))

def gate_template(atoms):
    base = "PRE-REGISTRAR metrica/baseline/limite/custo antes de experimentar"
    if any(t in atoms for t in ("kv", "cache", "memory")):
        return "KV bytes/token vs baseline medido d1216/8heads; limite -30% com Delta val<=0,05"
    if any(t in atoms for t in ("compression", "entropy", "arithmetic")):
        return "bits/byte em enwik8 1MB vs xz 2,31 / zstd 2,3857 + tempo de encode/decode no host"
    if any(t in atoms for t in ("scaling", "depth", "loop", "recurrent")):
        return "curva com 3 tamanhos (10M/50M/150M) e mesmo tokens vistos; sinal consistente em 3/3"
    return base

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--top", type=int, default=8)
    a = ap.parse_args()
    from jarvis.core.rag import HybridSearch
    hs = HybridSearch()
    groups = {}
    for tag, q in QUERIES.items():
        items, seen = [], set()
        for coll in COLLS:
            for h in hs.search(q, top_k=3, collection=coll, use_rerank=False):
                if h.path in seen: continue
                seen.add(h.path)
                p = h.payload or {}
                txt = str(p.get("content", ""))[:1500]
                items.append({"tag": tag, "collection": coll, "path": h.path,
                              "arxiv": p.get("arxiv_id"), "title": p.get("title"),
                              "atoms": atoms(txt + " " + str(p.get("title") or "")),
                              "snippet": txt[:220]})
        groups[tag] = items
    cands = []
    for (ta, _), (tb, _) in itertools.combinations(QUERIES.items(), 2):
        for x in groups[ta][:2]:
            for y in groups[tb][:2]:
                shared = sorted(set(x["atoms"]) & set(y["atoms"]))
                if len(shared) < 1: continue
                cands.append({"pair": [ta, tb], "evidence": [x, y],
                              "shared_atoms": shared,
                              "coherence": len(shared) + (1 if x["collection"] != y["collection"] else 0)})
    cands.sort(key=lambda c: -c["coherence"])
    out, seen_atoms = [], set()
    for c in cands:
        if len(out) >= a.top: break
        shared_all = c["shared_atoms"]
        key = frozenset(shared_all)
        if key in seen_atoms: continue
        seen_atoms.add(key)
        aa = (shared_all + [shared_all[0]])[:2]
        availability = sum(len(hs.search(f"{aa[0]} {aa[1]}", top_k=3,
                            collection=coll, use_rerank=False)) for coll in COLLS)
        x, y = c["evidence"]
        out.append({"id": f"{c['pair'][0]}-{c['pair'][1]}-{len(out)}",
                    "pair": c["pair"], "atoms": shared_all,
                    "coherence": c["coherence"], "availability_hits": availability,
                    "alien_score": round(c["coherence"] / max(1, availability), 3),
                    "hypothesis": f"Combinar '{aa[0]}' de {x['title'] or c['pair'][0]} com '{aa[1]}' de {y['title'] or c['pair'][1]} — medir ganho com o mesmo orcamento.",
                    "sources": [{"collection": z["collection"], "path": z["path"],
                                 "arxiv": z["arxiv"], "snippet": z["snippet"]} for z in [x, y]],
                    "status": "candidate",
                    "gate": gate_template(shared_all)})
    res = {"event": "alien_v2", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "collections": list(COLLS), "trechos": sum(len(v) for v in groups.values()),
           "hipoteses": out,
           "note": "proxy de coerencia/disponibilidade, nao modelo treinado; nao reescrever hipoteses antigas"}
    Path(a.out).write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"trechos": res["trechos"], "hipoteses": len(out), "out": a.out}))

if __name__ == "__main__":
    main()
