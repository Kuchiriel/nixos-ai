#!/usr/bin/env python3
"""alien-sampling --scan: varredura REAL dos papers em ~/Books/papers.

Diferente do alien-sampling.py original (pares fixos no codigo), este le
titulos/termos dos arquivos e gera combinacoes entre conceitos mediveis.
Cada hipotese carrega os CAMINHOS de origem e um gate a pre-registrar.
Nao e' evidencia — e' candidato a experimento.
"""
import argparse, json, re, time
from pathlib import Path

METRIC = ("loss", "token", "bits", "compression", "context", "attention",
          "latency", "throughput", "memory", "cache", "accuracy", "perplexity",
          "scale", "quantization", "retrieval", "multimodal", "video", "audio")
STOP = set("the a an and or of to in for with on is are we our this that from by as at it be".split())

def concepts(root):
    out = []
    for p in sorted(root.rglob("*.md")):
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if len(txt) < 400:
            continue
        head = next((l.lstrip("# ").strip() for l in txt.splitlines() if l.startswith("#")), p.stem)
        low = txt[:12000].lower()
        words = re.findall(r"[a-z][a-z0-9-]{3,}", low)
        freq = {}
        for w in words:
            if w not in STOP:
                freq[w] = freq.get(w, 0) + 1
        terms = [w for w, _ in sorted(freq.items(), key=lambda kv: -kv[1])[:12]]
        metrics = [m for m in METRIC if m in low]
        aid = re.search(r"(\d{4}\.\d{4,5})", p.name)
        out.append({"id": (aid.group(1) if aid else p.stem[:24]),
                    "title": head[:120], "path": str(p),
                    "terms": terms, "metrics": metrics})
    return out

def score(a, b):
    sa, sb = set(a["terms"]), set(b["terms"])
    overlap = len(sa & sb) / max(1, min(len(sa), len(sb)))
    ma, mb = set(a["metrics"]), set(b["metrics"])
    bridge = len(ma & mb)
    return (0.6 * (1 - overlap)) + (0.4 * min(bridge, 4) / 4)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default="/home/nixos/Books/papers")
    ap.add_argument("--out", required=True)
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()
    cs = concepts(Path(a.root))
    pairs = []
    for i in range(len(cs)):
        for j in range(i + 1, len(cs)):
            pairs.append((score(cs[i], cs[j]), i, j))
    pairs.sort(reverse=True)
    seen, out = set(), []
    for s, i, j in pairs:
        x, y = cs[i], cs[j]
        key = tuple(sorted((x["id"], y["id"])))
        if key in seen: continue
        seen.add(key)
        out.append({"a": x["id"], "b": y["id"],
                    "titles": [x["title"], y["title"]],
                    "sources": [x["path"], y["path"]],
                    "shared_metrics": sorted(set(x["metrics"]) & set(y["metrics"])),
                    "score": round(s, 3),
                    "hypothesis": f"Combinar o mecanismo de '{x['title'][:70]}' com a representacao de '{y['title'][:70]}' — qual métrica compartilhada melhora sem custo extra?",
                    "status": "candidate",
                    "gate": "PRE-REGISTRAR antes de qualquer experimento: metrica, baseline e limite numerico."})
        if len(out) >= a.top:
            break
    res = {"event": "alien_scan", "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "papers_scanned": len(cs), "hypotheses": out,
           "note": "candidatos, nao evidencia; nao reescrever hipoteses antigas"}
    Path(a.out).write_text(json.dumps(res, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"papers": len(cs), "hypotheses": len(out), "out": a.out}))

if __name__ == "__main__":
    main()
