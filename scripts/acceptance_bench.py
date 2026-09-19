#!/usr/bin/env python3
"""Benchmark de aceitação do Knowledge System (v2, versionado).

Substitui o heredoc one-off da noite de 18/09. Diferenças v1→v2:
  - needles por PATH **ou** CONTEÚDO (v1 só path — chunk relevante dentro de
    arquivo dominante era falso-negativo);
  - matriz diversify on/off (mede o efeito da diversidade por fonte);
  - 4 queries extras (exact-payload, semantic-compaction, book-mentalism,
    paper-cwl).

Janelas: code PASS no top-5 (janela MCP), books PASS no top-3 (critério v1).
Uso: nix develop -c python3 scripts/acceptance_bench.py [--out logs/acceptance-bench-v2.json]
"""
from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "modules" / "ai" / "jarvis" / "src"))

from jarvis.core.config import Config  # noqa: E402
from jarvis.core.rag import HybridSearch  # noqa: E402

# (id, coleção, query, needle_path, needle_content, janela)
QUERIES = [
    ("exact-constant", "code", "DANGEROUS_CHAINING shlex security",
     "security.py", ["DANGEROUS_CHAINING"], 5),
    ("exact-env", "code", "JARVIS_EMBED_BASE_URL embeddings porta",
     "config.py", ["JARVIS_EMBED_BASE_URL"], 5),
    ("semantic-loop", "code", "como o harness evita repetir a mesma falha noite inteira",
     "loop_detector", ["LoopDetector", "loop_max_attempts", "repetição idêntica"], 5),
    ("self-context", "code", "onde o context budget é calculado tokens contexto",
     "context_budget", ["ContextBudget", "context_budget"], 5),
    ("extra-exact-var", "code", "JARVIS_QDRANT_COLLECTION_MEMORIES variável de ambiente",
     "config.py", ["JARVIS_QDRANT_COLLECTION_MEMORIES"], 5),
    ("extra-semantic-compaction", "code", "quando o contexto da sessão deve ser comprimido",
     "context_budget", ["compaction_threshold", "compact"], 5),
    ("book-caibalion", "books", "primeiro princípio da transmutação mental",
     "630O-Caibalion", [], 3),
    ("digest-nickyeo", "books", "custo por tarefa cumprida world true não custo por token",
     "nickyeo", [], 3),
    ("extra-book-mentalism", "books", "o universo é mental",
     "630O-Caibalion", [], 3),
    ("extra-paper-cwl", "books", "agentes com contexto longo além da compactação",
     "beyond-compaction", [], 3),
]


def _ident(hit) -> str:
    p = hit.payload or {}
    return str(p.get("path") or p.get("book") or p.get("source_id") or "?")


def run_one(search: HybridSearch, coll: str, query: str,
            needle_path: str, needle_content: list[str], window: int,
            *, diversify: bool) -> dict:
    real = {"code": "code_index", "books": "books", "memories": "memories"}[coll]
    cfg = dataclasses.replace(search._cfg, qdrant_collection_code=real)
    s = HybridSearch(cfg)
    hits = s.search(query, top_k=max(window * 4, 15), use_rerank=False,
                    diversify=diversify)
    best_rank = None
    for i, h in enumerate(hits[:window], 1):
        ident = _ident(h)
        content = str(h.payload.get("content") or "")
        in_path = needle_path.lower() in ident.lower()
        in_content = any(t.lower() in content.lower() for t in needle_content)
        if (in_path or in_content) and best_rank is None:
            best_rank = i
    return {
        "ok": best_rank is not None,
        "rank": best_rank,
        "window": window,
        "top": [{"rank": i, "ident": _ident(h).split("/")[-1][:60],
                 "score": round(float(h.score), 4)}
                for i, h in enumerate(hits[:window], 1)],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=str(REPO / "logs" / "acceptance-bench-v2.json"))
    args = ap.parse_args()

    s = HybridSearch(Config())
    results: dict = {}
    passed = {True: 0, False: 0}
    t0 = time.time()
    for qid, coll, query, np_, nc, win in QUERIES:
        results[qid] = {"query": query, "collection": coll}
        for div in (False, True):
            r = run_one(s, coll, query, np_, nc, win, diversify=div)
            results[qid][f"div_{'on' if div else 'off'}"] = r
            if r["ok"]:
                passed[div] += 1
        o = results[qid]["div_off"]
        n = results[qid]["div_on"]
        print(f"{qid:28s} off: {'PASS' if o['ok'] else 'fail'}@{o['rank']}  "
              f"on: {'PASS' if n['ok'] else 'fail'}@{n['rank']}  ({coll})")

    print(f"\n===== RESUMO: off {passed[False]}/{len(QUERIES)} · on {passed[True]}/{len(QUERIES)} · {time.time()-t0:.0f}s")
    out = Path(args.out)
    out.parent.mkdir(exist_ok=True)
    out.write_text(json.dumps(
        {"ran_at": time.strftime("%Y-%m-%dT%H:%M:%S"), "passed": passed,
         "total": len(QUERIES), "results": results},
        ensure_ascii=False, indent=1))
    print(f"→ {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
