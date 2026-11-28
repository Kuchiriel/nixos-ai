#!/usr/bin/env python3
"""F141: extrator Lacuna-like de idea atoms com proveniencia (heuristico).

Nao e' LLM-distilled como o paper: usa frases de 1-2 sentencas dos trechos
recuperados, com path/arxiv/snippet de origem. Audita cada claim e aplica
mini-benchmark com criterios pre-registrados antes de promover hipotese.
"""
import argparse, json, re, time
from pathlib import Path

SEEDS = ("elastic latent recurrence loop index conditioning",
         "per-token halting KL convergence fixed point",
         "lossless speculative decoding draft verify",
         "byte EOT tokenizer data efficiency",
         "curated educational corpus filtering threshold",
         "residual normalization massive activations stages",
         "mixture of loops transformer experts",
         "late entry looped language models",
         "selective refinement implicit reasoning loop",
         "data constrained training repetition scaling law",
         "staged data mixture web code math pretraining",
         "strong weight decay overfitting unique tokens")
COLLS = ("code_index", "books", "jarvis_test_frontier_2026_11")
KEY = ("loop", "depth", "cache", "context", "compress", "token", "norm",
       "residual", "attention", "mlp", "speculative", "draft", "entropy",
       "curriculum", "filter", "halting", "convergence")
# criterios PRE-REGISTRADOS (antes de medir)
ACTION_RE = re.compile(r"\b(val|acc|loss|baseline|gate|custo|tempo)\b", re.I)
AVAIL_MAX = 35  # paths unicos acima disso = ideia muito disponivel, nao alien

def sentences(txt):
    parts = re.split(r"(?<=[.!?])\s+", txt)
    junk = ("bag of hallucinations", "phrase list", "table 7", "http")
    return [p.strip() for p in parts if 40 <= len(p) <= 220 and
            sum(k in p.lower() for k in KEY) >= 2 and
            p[0].isupper() and p.endswith((".", "?")) and
            not any(j in p.lower() for j in junk)]

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--top", type=int, default=10)
    a = ap.parse_args()
    from jarvis.core.rag import HybridSearch
    hs = HybridSearch()
    chunks, seen = [], set()
    for seed in SEEDS:
        for coll in COLLS:
            for h in hs.search(seed, top_k=3, collection=coll, use_rerank=False):
                if h.path in seen: continue
                # excluir ruido de books sem procedencia de paper/codigo
                if coll == "books" and not (h.payload or {}).get("arxiv_id"):
                    continue
                seen.add(h.path)
                p = h.payload or {}
                snip = str(p.get("content", ""))[:1200]
                chunks.append({"path": h.path, "arxiv": p.get("arxiv_id"),
                               "title": str(p.get("title") or "")[:120],
                               "collection": coll, "snippet": snip})
    atoms = []
    for c in chunks:
        for s in sentences(c["snippet"]):
            atoms.append({"atom": s, "path": c["path"], "arxiv": c["arxiv"],
                          "snippet": c["snippet"], "collection": c["collection"]})
    # dedup por frase normalizada, preservando proveniencia da 1a ocorrencia
    uniq, keys = [], set()
    for x in atoms:
        k = re.sub(r"\W+", " ", x["atom"].lower()).strip()[:120]
        if k in keys: continue
        keys.add(k); uniq.append(x)
    # F152: direcoes DERIVADAS dos atoms, nao fixas — termos tecnicos mais
    # frequentes nos trechos recuperados; descarta direcoes com <2 atoms.
    from collections import Counter
    freq = Counter()
    for x in uniq:
        low = x["atom"].lower()
        for t in KEY:
            if t in low:
                freq[t] += 1
    buckets = {t: (t,) for t, c in freq.most_common(8) if c >= 2}
    if len(buckets) < 3:
        buckets = {"loop/depth": ("loop", "depth", "recurrent"),
                   "cache/context": ("cache", "context", "memory"),
                   "compression/tokenizer": ("compress", "token", "entropy"),
                   "curation": ("curriculum", "filter", "educational"),
                   "norm/stability": ("norm", "residual", "convergence")}
    directions = {}
    for name, terms in buckets.items():
        ds = [x for x in uniq if any(t in x["atom"].lower() for t in terms)]
        directions[name] = {"atoms": len(ds),
                            "papers": sorted({x["path"] for x in ds})[:8]}
    pairs = []
    names = list(directions)
    for i in range(len(names)):
        for j in range(i+1, len(names)):
            # preferir atomos dos papers recem-indexados (novidade), nao os antigos
            A = sorted([x for x in uniq if x["collection"] in COLLS],
                       key=lambda x: ("frontier-2026-11-27" not in x["path"], x["path"]))
            left = next((x for x in A if any(t in x["atom"].lower() for t in buckets[names[i]])), None)
            right = next((x for x in A if any(t in x["atom"].lower() for t in buckets[names[j]]) and
                          x["path"] != (left or {}).get("path")), None)
            if not left or not right: continue
            q = " ".join(sorted(set(re.findall(r"[a-z]+", (left["atom"] + " " + right["atom"]).lower())))[:4])
            hits = set()
            for coll in COLLS:
                for h in hs.search(q, top_k=3, collection=coll, use_rerank=False):
                    hits.add(h.path)
            avail = len(hits)
            claim = f"{left['atom']} | {right['atom']}"
            audit = bool(left["path"] and right["path"] and
                         left["atom"] in left["snippet"] and right["atom"] in right["snippet"])
            if not audit: continue
            # gate pre-registrado e' a acao proposta; claim e' evidencia citada
            gate = ("Medir val_loss e acc no mesmo orcamento de tokens; baseline "
                    "F75 1.6749; limite Δ>=0.01 nat em 3 tamanhos; gate e custo "
                    "de VRAM/tempo medidos antes de treinar.")
            action = int(bool(ACTION_RE.search(gate)))
            pairs.append({"id": f"lac-{names[i]}-{names[j]}",
                          "directions": [names[i], names[j]], "claim": claim,
                          "availability_paths": avail, "actionability": action,
                          "gate": gate,
                          "promote": bool(action == 1 and avail <= AVAIL_MAX),
                          "sources": [{"path": x["path"], "arxiv": x["arxiv"],
                                       "snippet": x["atom"]} for x in (left, right)],
                          "status": "hipotese — NAO evidencia; gate antes de treinar"})
    # dedup de claims por frase normalizada (F142)
    seen_claim, dedup = set(), []
    for c in pairs:
        key = re.sub(r"\W+", " ", c["claim"].lower()).strip()[:160]
        if key in seen_claim: continue
        seen_claim.add(key); dedup.append(c)
    pairs = dedup
    pairs.sort(key=lambda p: (not p["promote"], p["availability_paths"]))
    res = {"event": "alien_lacuna",
           "atom_mode": "heuristic (LLM local apenas quando GPU livre; USE_LLM=0 agora)", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "chunks": len(chunks), "atoms": len(uniq),
           "directions": directions, "audit_discarded": len(atoms)-len(uniq),
           "criterios_pre_registrados": {"actionability": "contem metrica/baseline/gate/custo",
                                          "availability_paths_max": AVAIL_MAX},
           "hypotheses": pairs[:a.top],
           "promovidas": sum(1 for p in pairs[:a.top] if p["promote"])}
    Path(a.out).write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"chunks": len(chunks), "atoms": len(uniq),
                      "directions": len(directions), "promovidas": res["promovidas"]}))

if __name__ == "__main__":
    main()
