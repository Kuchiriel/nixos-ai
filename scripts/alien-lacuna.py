#!/usr/bin/env python3
"""alien-lacuna.py — amostrador heurístico inspirado em Lacuna/Alien Sampling.

Base conceitual (paper indexado no RAG do host):
- Artiles et al., "The Alien Space of Science: Sampling Coherent but Cognitively
  Unavailable Research Directions" (arXiv:2603.01092, NeurIPS 2026).
  Ideia: decompor em "idea atoms", pontuar coerência e disponibilidade, e
  priorizar combinações coerentes porém pouco disponíveis (alien space).

Esta implementação é HEURÍSTICA (não treina modelos de coerência/disponibilidade).
Usa RAG do host para recuperar trechos com proveniência, extrai atoms, forma pares,
estima proxies e gera hipóteses com gate pré-registrado. Hipótese != evidência.
"""
from __future__ import annotations
import argparse, json, re, time
from collections import Counter
from pathlib import Path

SEEDS = (
    "elastic latent recurrence loop index conditioning",
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
    "strong weight decay overfitting unique tokens",
)
COLLS = ("code_index", "books", "jarvis_test_frontier_2026_11")
KEY = ("loop", "depth", "cache", "context", "compress", "token", "norm",
       "residual", "attention", "mlp", "speculative", "draft", "entropy",
       "curriculum", "filter", "halting", "convergence", "scaling", "mixture")
ACTION_RE = re.compile(r"\b(val|acc|loss|baseline|gate|custo|tempo|bytes|latency|throughput)\b", re.I)
JUNK = ("bag of hallucinations", "phrase list", "table 7", "http", "copyright", "license")
PAPER_REF = {
    "title": "The Alien Space of Science: Sampling Coherent but Cognitively Unavailable Research Directions",
    "arxiv": "2603.01092",
    "venue": "NeurIPS 2026",
}

def sentences(txt: str):
    parts = re.split(r"(?<=[.!?])\s+", txt or "")
    out = []
    for p in parts:
        p = p.strip()
        if not (40 <= len(p) <= 260): continue
        if not p[0].isupper() or not p.endswith((".", "?")): continue
        low = p.lower()
        if any(j in low for j in JUNK): continue
        if sum(k in low for k in KEY) < 2: continue
        out.append(p)
    return out

def norm(s: str) -> str:
    return re.sub(r"\W+", " ", (s or "").lower()).strip()

def coherence_proxy(a: str, b: str) -> float:
    # proxy heurístico: sobreposição conceitual + comprimento útil; não é modelo treinado
    ta = set(re.findall(r"[a-z]{4,}", a.lower()))
    tb = set(re.findall(r"[a-z]{4,}", b.lower()))
    inter = len(ta & tb)
    union = len(ta | tb) or 1
    jacc = inter / union
    len_bonus = min(len(a), len(b)) / 260.0
    return round(max(0.0, min(1.0, 0.55 * jacc + 0.45 * len_bonus + 0.15)), 3)

def availability_proxy(paths: set[str], max_paths: int) -> float:
    # proxy: mais paths/ocorrências no RAG => mais disponível/clichê
    return round(min(1.0, len(paths) / max(1, max_paths)), 3)

def alien_score(coh: float, avail: float) -> float:
    return round(coh * (1.0 - avail), 3)

def bootstrap():
    """Auto-conserto de invocacao (medido 28/11, mesmo padrao dos outros
    alien-sampling-*): sem venv/PYTHONPATH o script morre com
    'No module named jarvis'. Re-execa com ~/.venvs/lab + src do jarvis."""
    import os
    import sys
    if os.environ.get("ALIEN_BOOTSTRAPPED"):
        return
    try:
        import requests  # noqa: F401
        sys.path.insert(0, os.path.expanduser(
            "~/projects/nixos-ai/modules/ai/jarvis/src"))
        import jarvis.core.rag  # noqa: F401
        return
    except Exception:
        pass
    venv = os.path.expanduser("~/.venvs/lab/bin/python")
    src = os.path.expanduser("~/projects/nixos-ai/modules/ai/jarvis/src")
    if os.path.exists(venv):
        env = dict(os.environ, ALIEN_BOOTSTRAPPED="1")
        old = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = src + (":" + old if old else "")
        os.execve(venv, [venv] + sys.argv, env)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--top", type=int, default=12)
    ap.add_argument("--avail-max", type=int, default=35)
    ap.add_argument("--min-alien", type=float, default=0.15)
    ap.add_argument("--dry-run", action="store_true", help="não consulta RAG pesado; gera saída mínima")
    ap.add_argument("--export-dir", default=str(Path.home()/ "work/hybrid"))
    args = ap.parse_args()

    if args.dry_run:
        res = {"event":"alien_lacuna_v3","ok":True,"dry_run":True,"ts":time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),"paper_basis":PAPER_REF,"rule":"Hipótese != evidência."}
        out = Path(args.out); out.parent.mkdir(parents=True, exist_ok=True); out.write_text(json.dumps(res,ensure_ascii=False,indent=2)+"\n")
        print(json.dumps(res, ensure_ascii=False))
        return

    bootstrap()
    from jarvis.core.rag import HybridSearch
    hs = HybridSearch()

    chunks, seen = [], set()
    for seed in SEEDS:
        for coll in COLLS:
            try:
                hits = hs.search(seed, top_k=3, collection=coll, use_rerank=False)
            except Exception:
                hits = []
            for h in hits:
                if h.path in seen: continue
                p = h.payload or {}
                if coll == "books" and not (p.get("arxiv_id") or p.get("title")):
                    # mantém books úteis, mas evita lixo sem procedência
                    pass
                seen.add(h.path)
                snip = str(p.get("content", ""))[:1400]
                chunks.append({
                    "path": h.path,
                    "arxiv": p.get("arxiv_id"),
                    "title": str(p.get("title") or "")[:140],
                    "collection": coll,
                    "snippet": snip,
                })

    atoms = []
    for c in chunks:
        for s in sentences(c["snippet"]):
            atoms.append({"atom": s, **c})
    uniq, keys = [], set()
    for x in atoms:
        k = norm(x["atom"])[:160]
        if not k or k in keys: continue
        keys.add(k); uniq.append(x)

    freq = Counter()
    for x in uniq:
        low = x["atom"].lower()
        for t in KEY:
            if t in low: freq[t] += 1
    terms = [t for t, c in freq.most_common(10) if c >= 2]
    buckets = {t: (t,) for t in terms}
    if len(buckets) < 3:
        buckets = {"loop": ("loop","depth","recurrent"), "cache": ("cache","context","memory"), "compression": ("compress","token","entropy")}

    directions = {}
    for name, ts in buckets.items():
        ds = [x for x in uniq if any(t in x["atom"].lower() for t in ts)]
        directions[name] = {"atoms": len(ds), "papers": sorted({x["path"] for x in ds})[:8]}

    pairs = []
    names = list(directions.keys())
    for i in range(len(names)):
        for j in range(i+1, len(names)):
            A = sorted(uniq, key=lambda x: (x.get("collection") != "books", x.get("path","")))
            left = next((x for x in A if any(t in x["atom"].lower() for t in buckets[names[i]])), None)
            right = next((x for x in A if any(t in x["atom"].lower() for t in buckets[names[j]]) and x["path"] != (left or {}).get("path")), None)
            if not left or not right: continue
            q = " ".join(sorted(set(re.findall(r"[a-z]{4,}", (left["atom"]+" "+right["atom"]).lower())))[:6])
            hits = set()
            score_sum = 0.0; score_n = 0
            for coll in COLLS:
                try:
                    for h in hs.search(q, top_k=4, collection=coll, use_rerank=False):
                        hits.add(h.path)
                        sc = float(getattr(h, "score", 0.0) or 0.0)
                        if sc > 0: score_sum += sc; score_n += 1
                except Exception:
                    pass
            avail = availability_proxy(hits, args.avail_max)
            coh_lex = coherence_proxy(left["atom"], right["atom"])
            coh_sem = min(1.0, (score_sum / score_n) if score_n else 0.0)
            coh = round(0.55*coh_lex + 0.45*coh_sem, 3)
            alien = alien_score(coh, avail)
            claim = f"{left['atom']} | {right['atom']}"
            audit = bool(left["path"] and right["path"] and left["atom"] in left.get("snippet","") and right["atom"] in right.get("snippet",""))
            if not audit: continue
            gate = {
                "metric": "val_loss, acc, bytes/token ou latência (escolher 1 primária)",
                "baseline": "medir baseline atual no mesmo setup antes de mudar",
                "limit": "pré-registrar delta mínimo (ex: Δval_loss <= -0.01 ou +0.5pp acc)",
                "cost": "registrar VRAM, tempo, tokens, hardware",
                "scale": ">=3 tamanhos/configs antes de concluir",
            }
            actionability = 1 if all(gate.values()) else 0
            promote = bool(actionability and alien >= args.min_alien and len(hits) <= args.avail_max)
            pairs.append({
                "id": f"lac-{names[i]}-{names[j]}",
                "directions": [names[i], names[j]],
                "claim": claim,
                "coherence_proxy": coh,
                "availability_proxy": avail,
                "availability_paths": len(hits),
                "alien_score": alien,
                "actionability": actionability,
                "promote": promote,
                "gate": gate,
                "sources": [
                    {"path": left["path"], "arxiv": left.get("arxiv"), "title": left.get("title"), "atom": left["atom"]},
                    {"path": right["path"], "arxiv": right.get("arxiv"), "title": right.get("title"), "atom": right["atom"]},
                ],
                "status": "hipótese — NÃO evidência; só promover com gate pré-registrado medido",
            })

    # dedup por claim normalizado
    seen_claim, dedup = set(), []
    for c in pairs:
        k = norm(c["claim"])[:180]
        if k in seen_claim: continue
        seen_claim.add(k); dedup.append(c)
    dedup.sort(key=lambda p: (-p["alien_score"], p["availability_paths"], -p["coherence_proxy"]))
    top = dedup[:args.top]
    recommended = [p["id"] for p in top if p["promote"]][:3]

    res = {
        "event": "alien_lacuna_v3",
        "paper_basis": PAPER_REF,
        "mode": "heuristic v3 (lexical+semantic proxy coherence, availability, alien score; no trained Lacuna models)",
        "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "chunks": len(chunks),
        "atoms": len(uniq),
        "audit_discarded": max(0, len(atoms) - len(uniq)),
        "directions": directions,
        "criteria": {
            "alien_score": "coherence_proxy * (1 - availability_proxy)",
            "promote_if": f"actionability==1 and alien_score>={args.min_alien} and availability_paths<={args.avail_max}",
        },
        "recommended_next": recommended,
        "rule": "Hipótese != evidência. Promover só com gate pré-registrado: métrica, baseline, limite, custo, >=3 tamanhos.",
        "hypotheses": top,
        "promovidas": sum(1 for p in top if p["promote"]),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n")
    # export
    try:
        exp_dir = Path(args.export_dir); exp_dir.mkdir(parents=True, exist_ok=True)
        exp = exp_dir / f"alien-lacuna-v3-{time.strftime('%Y%m%d-%H%M%S')}.json"
        exp.write_text(json.dumps({"recommended_next": recommended, "top": top[:5], "ts": res["ts"], "paper_basis": PAPER_REF}, ensure_ascii=False, indent=2)+"\n")
        res["export"] = str(exp)
    except Exception as e:
        res["export_error"] = str(e)[:200]
    # bus summary (best-effort)
    try:
        import subprocess
        msg = f"alien-lacuna-v3: atoms={len(uniq)} hyp={len(top)} promovidas={res['promovidas']} rec={','.join(recommended) or '-'} out={out}"
        subprocess.run(["bash","-lc","command -v bus-post >/dev/null && bus-post --kind status --to todos "+json.dumps(msg)], timeout=20, cwd=str(Path.home()))
        res["bus_posted"] = True
    except Exception as e:
        res["bus_posted"] = False; res["bus_error"] = str(e)[:200]
    out.write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"ok": True, "chunks": len(chunks), "atoms": len(uniq), "hypotheses": len(top), "promovidas": res["promovidas"], "recommended_next": recommended, "export": res.get("export")}, ensure_ascii=False))

if __name__ == "__main__":
    main()
