#!/usr/bin/env python3
"""rag-eval.py — recall@k e MRR do RAG híbrido contra perguntas de resposta conhecida.

USO:
  nix develop --command python3 scripts/rag-eval.py
  nix develop --command python3 scripts/rag-eval.py --top-k 8 --rerank both
  nix develop --command python3 scripts/rag-eval.py --fixture scripts/rag-eval-queries.jsonl

CONTRATO:
  - Fixture = JSONL com {"query": str, "expect": str, "note": str?}; `expect`
    é um sufixo de path que precisa aparecer no payload do hit (ex.:
    "core/rag.py"). Fixture default: scripts/rag-eval-queries.jsonl.
  - Mede somente leitura: chama HybridSearch.search, não indexa nem apaga.
  - Reporta por pergunta o rank do acerto e o top-3 de paths, e no fim
    recall@k e MRR por modo (com e sem reranker).
  - Motivo (medido 19/11): "pontos indexados" não prova qualidade de
    retrieval; sem pergunta de resposta conhecida, mudança de boost/rerank
    vira opinião. Este script é o juiz reproduzível.
  - Sai != 0 se o fixture estiver vazio ou se algum modo tiver recall 0.
  - `--min-recall F` transforma o harness em gate de regressao: sai 2 se
    qualquer modo ficar abaixo de F (ex.: 0.9 para nao regressar ao 1/5 historico).

EXEMPLO:
  python3 scripts/rag-eval.py --top-k 8 --rerank both
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
DEFAULT_FIXTURE = HERE / "rag-eval-queries.jsonl"


def load_fixture(path: Path) -> list[dict]:
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        rows.append(json.loads(line))
    return rows


def run_mode(rows: list[dict], top_k: int, use_rerank: bool) -> dict:
    sys.path.insert(0, str(HERE.parent / "modules/ai/jarvis/src"))
    from jarvis.core.rag import HybridSearch

    search = HybridSearch()
    ranks: list[int | None] = []
    for row in rows:
        hits = search.search(row["query"], top_k=top_k, use_rerank=use_rerank)
        paths = [str(hit.path) for hit in hits]
        want = row["expect"]
        rank = next((i + 1 for i, p in enumerate(paths) if want in p), None)
        ranks.append(rank)
        top3 = ", ".join(os.path.basename(p) or "<sem path>" for p in paths[:3])
        label = f"rank {rank}" if rank else "MISS"
        print(f"  [{'rerank' if use_rerank else 'fusion'}] {label:8s} {row['query'][:60]}")
        print(f"           top3: {top3}")
    found = [r for r in ranks if r]
    recall = len(found) / len(ranks)
    mrr = sum(1.0 / r for r in found) / len(ranks)
    return {"recall": recall, "mrr": mrr, "ranks": ranks}


def main() -> int:
    ap = argparse.ArgumentParser(description="recall@k do RAG híbrido")
    ap.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    ap.add_argument("--top-k", type=int, default=8)
    ap.add_argument("--rerank", choices=["on", "off", "both"], default="both")
    ap.add_argument("--min-recall", type=float, default=None,
                    help="gate de regressao: falha (2) se recall < F em qualquer modo")
    args = ap.parse_args()

    rows = load_fixture(args.fixture)
    if not rows:
        print(f"fixture vazio: {args.fixture}", file=sys.stderr)
        return 2

    modes: list[bool] = {"on": [True], "off": [False], "both": [False, True]}[args.rerank]
    results = {}
    for use_rerank in modes:
        print(f"\n== rerank={'on' if use_rerank else 'off'} (top_k={args.top_k}) ==")
        results[use_rerank] = run_mode(rows, args.top_k, use_rerank)

    print("\n== resumo ==")
    for use_rerank, res in results.items():
        print(f"rerank={'on ' if use_rerank else 'off'}  recall@{args.top_k}="
              f"{res['recall']:.2f}  MRR={res['mrr']:.3f}  ranks={res['ranks']}")
    if not all(r["recall"] > 0 for r in results.values()):
        return 1
    if args.min_recall is not None:
        below = {("on" if k else "off"): r["recall"]
                 for k, r in results.items() if r["recall"] < args.min_recall}
        if below:
            print("GATE FAIL recall abaixo de %.2f: %s" % (args.min_recall, below), file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
