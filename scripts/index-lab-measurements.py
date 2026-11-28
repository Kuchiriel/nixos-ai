#!/usr/bin/env python3
"""Indexa no RAG as medicoes/gates do ai-mesh e PROVA recall.

Uso:  python3 scripts/index-lab-measurements.py ["consulta de teste"]
Saida: JSON com contadores + top-5 hits (path, score).

Coleta o ai-mesh main via git archive (sem mexer no working tree, que pode
estar sujo de outros agentes), indexa docs/*2026-11-28*.md na colecao
lab_measurements e roda uma busca hibrida. Regra da casa: salvar no RAG sem
teste de recall e falso positivo.
"""
from __future__ import annotations
import json, subprocess, sys, tempfile
from dataclasses import replace
from pathlib import Path

SRC = Path("/home/nixos/projects/ai-mesh")
DST = Path("/home/nixos/work/hybrid/rag-docs")
DEFAULT_Q = "F149 hipercubo escala seed43 d1216 gate"


def main() -> int:
    q = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_Q
    subprocess.run(["git", "-C", str(SRC), "fetch", "origin", "main", "-q"], check=True)
    DST.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "-C", str(SRC), "archive", "origin/main", "docs"],
                   stdout=open("/tmp/rag-docs.tar", "wb"), check=True)
    subprocess.run(["tar", "-x", "-f", "/tmp/rag-docs.tar", "-C", str(DST)], check=True)
    from jarvis.core.config import Config
    from jarvis.core.rag import HybridIndexer, HybridSearch
    cfg = replace(Config(), qdrant_collection_code="lab_measurements")
    idx = HybridIndexer(cfg)
    idx.ensure_collection()
    files = sorted((DST / "docs").glob("*2026-11-28*.md"))
    n = 0
    fails = []
    for f in files:
        try:
            if idx.index_file(str(f), force=True):
                n += 1
        except Exception as exc:
            fails.append([f.name, type(exc).__name__])
    hits = HybridSearch(cfg).search(q, top_k=5, collection=cfg.qdrant_collection_code)
    out = {"collection": cfg.qdrant_collection_code, "indexed": n,
           "files": len(files), "fail": fails[:5], "query": q,
           "hits": [{"path": str(getattr(h, "path", "")),
                     "score": round(float(getattr(h, "score", 0) or 0), 3)} for h in hits]}
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if n > 0 and hits else 2


if __name__ == "__main__":
    raise SystemExit(main())
