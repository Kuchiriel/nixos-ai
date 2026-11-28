#!/usr/bin/env python3
"""alien-sampling com RAG MULTICOLECAO: codigo do LLM + Books/YouTube + papers.

Cada hipotese carrega trechos recuperados com colecao/path/arxiv/titulo.
Gate a pre-registrar. Nao e' evidencia.
"""
import argparse, itertools, json, time
from pathlib import Path

QUERIES = {
    "codigo_llm": "ScaleLM wordlevel 8 blocos elastic loop KV cache F79",
    "compressao": "lossless compression arithmetic coding wikipedia",
    "kv_contexto": "KV cache long context memory attention",
    "quantizacao": "ternary quantization QAT low bit",
    "multimodal": "multimodal vision language audio encoder",
    "transcricoes": "local AI agent harness browser control YouTube",
}
TEMPLATES = [
    ("{a} + {b}", "O mecanismo de {A} pode reduzir o gargalo de {B} com o mesmo orcamento?"),
    ("{a} -> {b}", "A tecnica de {A} aplicada dentro do pipeline de {B} melhora a metrica compartilhada?"),
]
TECH = ("arithmetic coding", "kv cache", "entropy", "attention", "quantization",
        "speculative", "retrieval", "compression", "multimodal", "elastic",
        "loop", "sparse", "tokenizer", "browser", "harness")

def bootstrap():
    """Auto-conserto de invocacao (medido 28/11): o script quebrava com
    'No module named jarvis'/'requests' quando rodado com o python3 do sistema.
    Se o import ja funciona, segue; senao re-exec com o venv lab + PYTHONPATH
    do jarvis. Uma vez so (ALIEN_BOOTSTRAPPED evita loop)."""
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
    # NixOS: realpath do python3 do sistema e do venv podem ser O MESMO binario
    # (medido 28/11) — nao comparar realpath; o venue cumpre o papel pelo
    # pyvenv.cfg do diretorio. A bandeira ALIEN_BOOTSTRAPPED evita o loop.
    if os.path.exists(venv):
        env = dict(os.environ, ALIEN_BOOTSTRAPPED="1")
        old = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = src + (":" + old if old else "")
        os.execve(venv, [venv] + sys.argv, env)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True)
    ap.add_argument("--collections", default="code_index,books,jarvis_test_frontier_2026_11")
    ap.add_argument("--top", type=int, default=12)
    a = ap.parse_args()
    bootstrap()
    from jarvis.core.rag import HybridSearch
    hs = HybridSearch()
    colls = [c.strip() for c in a.collections.split(",") if c.strip()]
    groups, seen_paths = {}, set()
    for tag, q in QUERIES.items():
        items = []
        for coll in colls:
            for h in hs.search(q, top_k=2, collection=coll, use_rerank=False):
                if h.path in seen_paths:
                    continue
                seen_paths.add(h.path)
                p = h.payload or {}
                items.append({"tag": tag, "collection": coll, "query": q,
                              "path": h.path, "arxiv": p.get("arxiv_id"),
                              "title": p.get("title"),
                              "score": round(float(h.score), 3),
                              "snippet": str(p.get("content", ""))[:300]})
        groups[tag] = items
    def terms(ev):
        low = (ev["snippet"] + " " + str(ev["title"]) + " " + str(ev["path"])).lower()
        return [t for t in TECH if t in low]
    pairs = list(itertools.combinations(QUERIES.items(), 2))
    hyps = []
    for rnd in range(2):
        for (ta, _), (tb, _) in pairs:
            xs, ys = groups[ta], groups[tb]
            if rnd >= len(xs) or rnd >= len(ys):
                continue
            x, y = xs[rnd], ys[rnd]
            if x["path"] == y["path"]:
                continue
            tx, ty = terms(x), terms(y)
            name, tmpl = TEMPLATES[min(rnd, len(TEMPLATES)-1)]
            hyps.append({"id": f"{ta}-{tb}-{rnd}", "pair": [ta, tb],
                "template": name,
                "hypothesis": tmpl.format(A=", ".join(tx[:2]) or ta,
                                          B=", ".join(ty[:2]) or tb),
                "collections": [x["collection"], y["collection"]],
                "shared_terms": sorted(set(tx) & set(ty)),
                "evidence": [x, y], "status": "candidate",
                "gate": "PRE-REGISTRAR metrica, baseline, limite e custo ANTES de experimento"})
            if len(hyps) >= a.top: break
        if len(hyps) >= a.top: break
    out = {"event": "alien_rag_multi",
           "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
           "collections": colls, "queries": QUERIES,
           "trechos_recuperados": sum(len(v) for v in groups.values()),
           "hipoteses": hyps,
           "note": "candidatos de codigo+books+papers, nao evidencia"}
    Path(a.out).write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(json.dumps({"trechos": out["trechos_recuperados"],
                      "hipoteses": len(hyps), "out": a.out}))

if __name__ == "__main__":
    main()
