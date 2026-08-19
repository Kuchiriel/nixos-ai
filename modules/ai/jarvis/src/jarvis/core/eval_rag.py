"""Avaliação da qualidade do retrieval do RAG — NDCG@k, Recall@k, Precision@k.

O benchmark (`core/benchmark.py`) mede a *latência* da cascata; este módulo
mede a *qualidade* do retrieval (critério #3 do assessment: "Benchmark de
retrieval (NDCG/Recall@k) + latência registrado e regredindo → otimização
guiada por dado").

Cada caso tem um ground-truth: os arquivos do repo que uma consulta *deveria*
recuperar (marcados como relevantes no payload do índice: `eval_relevant: true`).
O índice do lab é populado com esses marcadores via `jarvis eval-rag --seed`.

Métricas por query (top_k = nº de hits avaliados):
  - Precision@k  = |relevantes ∩ hits| / k
  - Recall@k     = |relevantes ∩ hits| / |relevantes|
  - NDCG@k       = DCG@k / IDCG@k (ganho 1 para relevante, log2(i+1) de desconto)
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass, field
from typing import Any

# ---------------------------------------------------------------------------
# Ground-truth: (query, [paths relevantes no índice])
# Paths relativos à raiz do repo (mesmo formato do payload `path` do indexador).
# ---------------------------------------------------------------------------
RAG_QUERIES: list[tuple[str, list[str]]] = [
    # --- núcleo (roteamento, memória, áudio) ---
    ("onde está o vetor de busca híbrida do qdrant", ["modules/ai/jarvis/src/jarvis/providers/vector_store.py"]),
    ("roteamento da cascata fastpath doctor nixos rag", ["modules/ai/jarvis/src/jarvis/core/router.py"]),
    ("lições aprendidas na memória episódica", ["modules/ai/jarvis/src/jarvis/core/memory.py"]),
    ("feedback de voz por sons para o usuário", ["modules/ai/jarvis/src/jarvis/core/feedback.py"]),
    ("padrões de texto rivescript para respostas rápidas", ["modules/ai/jarvis/src/jarvis/core/rules.py"]),
    # --- voz ---
    ("detecção de emoção por keywords para o tts", ["modules/ai/jarvis/src/jarvis/core/emotion.py"]),
    ("transcrição de áudio com whisper e vad calibrado", ["modules/ai/jarvis/src/jarvis/core/voice.py"]),
    # --- NixOS (self-knowledge) ---
    ("modelos declarativos openwakeword kokoro whisper", ["modules/ai/models.nix"]),
    ("serviço declarativo do banco vetorial qdrant", ["modules/services/qdrant.nix"]),
    ("denoise rnnoise no pipewire para o microfone", ["nixos/modules/audio.nix"]),
    ("calibração do wakeword com threshold e cooldown", ["home-manager/modules/services/jarvis-wakeword.nix"]),
]

DEFAULT_TOP_K = 5


@dataclass
class EvalResult:
    query: str
    relevant: list[str]
    hits: list[str]  # paths recuperados (top_k)
    top_k: int
    precision: float = 0.0
    recall: float = 0.0
    ndcg: float = 0.0
    error: str = ""

    @property
    def relevant_found(self) -> int:
        rel = set(self.relevant)
        return sum(1 for h in self.hits if h in rel)


def _ndcg_at_k(hits: list[str], relevant: set[str], k: int) -> float:
    """NDCG@k — ganho 1 para hit relevante, desconto log2(posição+1)."""
    dcg = 0.0
    for i, path in enumerate(hits[:k]):
        if path in relevant:
            dcg += 1.0 / math.log2(i + 2)
    idcg = sum(1.0 / math.log2(i + 2) for i in range(min(len(relevant), k)))
    return dcg / idcg if idcg > 0 else 0.0


def _norm(path: str, root: str) -> str:
    """Normaliza o path do índice (absoluto ou relativo) para relativo ao root."""
    p = os.path.abspath(path)
    r = os.path.abspath(root)
    try:
        rel = os.path.relpath(p, r)
    except ValueError:  # drives diferentes (Windows) — usa o path como está
        return path
    if not rel.startswith(".."):
        return rel
    # Fora do root: tenta só o sufixo (últimos 2 componentes) para casar
    # com ground-truth relativo mesmo que o index root difira do cwd.
    parts = rel.split(os.sep)
    if len(parts) >= 2:
        return os.path.join(*parts[-2:])
    return rel


def evaluate(
    search_fn: Any,
    queries: list[tuple[str, list[str]]] | None = None,
    *,
    top_k: int = DEFAULT_TOP_K,
    root: str = ".",
) -> list[EvalResult]:
    """Roda as queries contra `search_fn(query, top_k=...)` e calcula as métricas.

    `root` é a raiz do repo para normalizar paths absolutos do índice contra o
    ground-truth relativo (default: cwd).
    """
    results: list[EvalResult] = []
    for query, relevant in (queries or RAG_QUERIES):
        res = EvalResult(query=query, relevant=relevant, hits=[], top_k=top_k)
        try:
            hits = search_fn(query, top_k=top_k)
            res.hits = [_norm(h.path, root) for h in hits]
        except Exception as exc:  # noqa: BLE001 — eval nunca quebra
            res.error = str(exc)[:120]
            results.append(res)
            continue
        rel = set(relevant)
        found = res.relevant_found
        res.precision = found / top_k if top_k else 0.0
        res.recall = found / len(relevant) if relevant else 0.0
        res.ndcg = _ndcg_at_k(res.hits, rel, top_k)
        results.append(res)
    return results


def eval_report(
    search_fn: Any,
    queries: list[tuple[str, list[str]]] | None = None,
    *,
    top_k: int = DEFAULT_TOP_K,
    root: str = ".",
) -> dict[str, Any]:
    """Relatório agregado (médias) + por query, em dict (JSON-friendly)."""
    results = evaluate(search_fn, queries, top_k=top_k, root=root)
    ok = [r for r in results if not r.error]
    n = len(ok)
    agg = {
        "top_k": top_k,
        "queries": len(results),
        "erros": len(results) - n,
        "precision_at_k": round(sum(r.precision for r in ok) / n, 4) if n else 0.0,
        "recall_at_k": round(sum(r.recall for r in ok) / n, 4) if n else 0.0,
        "ndcg_at_k": round(sum(r.ndcg for r in ok) / n, 4) if n else 0.0,
    }
    return {
        "médias": agg,
        "por_query": [
            {
                "query": r.query,
                "precision_at_k": round(r.precision, 4),
                "recall_at_k": round(r.recall, 4),
                "ndcg_at_k": round(r.ndcg, 4),
                "relevant_found": r.relevant_found,
                "relevant_total": len(r.relevant),
                "hits": r.hits,
                **( {"error": r.error} if r.error else {}),
            }
            for r in results
        ],
    }


def _table(report: dict[str, Any]) -> str:
    agg = report["médias"]
    lines = [
        f"Eval RAG — top_k={agg['top_k']}, {agg['queries']} queries, {agg['erros']} erros",
        f"  Precision@{agg['top_k']}: {agg['precision_at_k']}   "
        f"Recall@{agg['top_k']}: {agg['recall_at_k']}   "
        f"NDCG@{agg['top_k']}: {agg['ndcg_at_k']}",
        "-" * 88,
    ]
    for r in report["por_query"]:
        found = r.get("relevant_found", 0)
        total = r.get("relevant_total", 0)
        lines.append(
            f"  [{found}/{total} relevante] p@{agg['top_k']}={r['precision_at_k']} "
            f"r={r['recall_at_k']} ndcg={r['ndcg_at_k']}  {r['query'][:45]}"
        )
        if r.get("error"):
            lines.append(f"    ERROR: {r['error']}")
        for hit in r.get("hits", [])[:3]:
            lines.append(f"    · {hit}")
    return "\n".join(lines)


def main_eval_rag(argv: list[str] | None = None) -> int:
    """Entry point CLI: jarvis eval-rag [--top-k N] [--json] [--seed]."""
    import argparse

    parser = argparse.ArgumentParser(prog="jarvis eval-rag", description="Qualidade do retrieval (NDCG/Recall@k)")
    parser.add_argument("--top-k", type=int, default=DEFAULT_TOP_K)
    parser.add_argument("--json", action="store_true", help="saída JSON pura")
    args = parser.parse_args(argv)

    from jarvis.core.config import get_config
    from jarvis.core.rag import HybridSearch

    cfg = get_config()
    search = HybridSearch(cfg)
    report = eval_report(search.search, top_k=args.top_k, root=".")
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_table(report))
    agg = report["médias"]
    ok = agg["erros"] == 0 and agg["recall_at_k"] >= 0.5 and agg["ndcg_at_k"] >= 0.5
    return 0 if ok else 2
