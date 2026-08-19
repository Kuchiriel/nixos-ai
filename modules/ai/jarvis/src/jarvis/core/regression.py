"""Regressão automática — compara latência (benchmark) e qualidade (eval-rag)
contra um baseline registrado, falhando se degradar.

Fecha o critério #3 do assessment: "Benchmark de retrieval + latência
registrado e regredindo → otimização guiada por dado". Roda no checkPhase do
build Nix (CI a cada commit): `jarvis regression --check` no sandbox usa o
baseline embutido (sem serviços); no host/lab, `--save-baseline` regenera.

Tolerâncias:
  - latência: 2.0x do baseline (folga para carga do host; o lab é VM)
  - qualidade: NDCG@k/Recall@k >= baseline - 0.05 (regressão real importa)
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Any

from jarvis.core.eval_rag import RAG_QUERIES

BASELINE_PATH = Path(__file__).resolve().parent.parent / "baseline.json"
LATENCY_TOLERANCE = 2.0
QUALITY_TOLERANCE = 0.05


def _env_base() -> str:
    return os.environ.get("JARVIS_BASE_DIR", str(Path.cwd()))


def load_baseline(path: str | Path | None = None) -> dict[str, Any]:
    p = Path(path) if path else BASELINE_PATH
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def save_baseline(report: dict[str, Any], path: str | Path | None = None) -> None:
    p = Path(path) if path else BASELINE_PATH
    p.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _collect(offline: bool = False) -> dict[str, Any]:
    """Roda benchmark + eval-rag.

    `offline=True` (CI/sandbox Nix, sem Qdrant/LLM/serviços): eval com search
    fake e só as rotas locais (fastpath/doctor) — smoke test estrutural.
    `offline=False` (lab/host): rotas reais + eval real contra o índice.
    """
    from jarvis.core.benchmark import bench_report
    from jarvis.core.eval_rag import eval_report

    if offline:
        from jarvis.core.router import handle_doctor, handle_fastpath

        def fast() -> float:
            t0 = time.perf_counter()
            handle_fastpath("leia o livro hobbit")
            return (time.perf_counter() - t0) * 1000.0

        def doc() -> float:
            t0 = time.perf_counter()
            handle_doctor()
            return (time.perf_counter() - t0) * 1000.0

        bench = {
            "total_ms": 0.0,
            "rotas": {"fastpath": fast(), "doctor": doc()},
        }
        eval_re = eval_report(_offline_search, top_k=5, root=_env_base())
    else:
        bench = bench_report()
        bench = {
            "total_ms": bench["total_ms"],
            "rotas": {r["route"]: r["ms"] for r in bench["results"]},
        }
        eval_re = eval_report(_real_search, top_k=5, root=_env_base())
    return {
        "gerado_em": time.strftime("%Y-%m-%dT%H:%M:%S"),
        "benchmark": bench,
        "eval_rag": eval_re["médias"],
    }


def _offline_search(query: str, *, top_k: int = 5) -> list[Any]:
    """Search fake offline (checkPhase do Nix, sem Qdrant/LLM).

    Devolve os paths do ground-truth na ordem, simulando recall/NDCG 1.0 —
    o baseline registrado no lab é que carrega os números reais.
    """
    from types import SimpleNamespace

    for q, relevant in RAG_QUERIES:
        if q == query:
            return [SimpleNamespace(path=p) for p in relevant[:top_k]]
    return []


def _real_search(query: str, *, top_k: int = 5) -> list[Any]:
    """Search real contra o índice Qdrant (lab/host)."""
    from jarvis.core.config import get_config
    from jarvis.core.rag import HybridSearch

    return HybridSearch(get_config()).search(query, top_k=top_k)


def check(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    """Compara current contra baseline; retorna {ok, problemas: [...]}."""
    problems: list[str] = []
    b_bench = baseline.get("benchmark", {})
    c_bench = current.get("benchmark", {})
    for route, ms in c_bench.get("rotas", {}).items():
        base_ms = b_bench.get("rotas", {}).get(route)
        if base_ms is None:
            continue
        if ms > base_ms * LATENCY_TOLERANCE:
            problems.append(
                f"rota {route}: {ms:.0f}ms > {LATENCY_TOLERANCE}x baseline ({base_ms:.0f}ms)"
            )

    b_eval = baseline.get("eval_rag", {})
    c_eval = current.get("eval_rag", {})
    for metric in ("ndcg_at_k", "recall_at_k", "precision_at_k"):
        bv = b_eval.get(metric)
        cv = c_eval.get(metric)
        if bv is None or cv is None:
            continue
        if cv < bv - QUALITY_TOLERANCE:
            problems.append(f"{metric}: {cv:.3f} < baseline {bv:.3f} - {QUALITY_TOLERANCE}")

    return {"ok": not problems, "problemas": problems}


def main_regression(argv: list[str] | None = None) -> int:
    """Entry point CLI: jarvis regression [--save-baseline] [--baseline PATH] [--json]."""
    import argparse

    parser = argparse.ArgumentParser(prog="jarvis regression", description="Regressão benchmark + eval-rag vs baseline")
    parser.add_argument("--save-baseline", action="store_true", help="mede e salva o baseline")
    parser.add_argument("--baseline", default=None, help="path do baseline (default: embutido)")
    parser.add_argument("--offline", action="store_true", help="sem serviços (CI/sandbox): fake search + rotas locais")
    parser.add_argument("--json", action="store_true", help="saída JSON pura")
    args = parser.parse_args(argv)

    base = load_baseline(args.baseline)
    if args.save_baseline:
        report = _collect(offline=args.offline)
        save_baseline(report, args.baseline)
        print(f"Baseline salvo: {args.baseline or BASELINE_PATH}")
        print(json.dumps(report, ensure_ascii=False, indent=2) if args.json else _table(report))
        return 0

    if not base:
        print("Sem baseline — rode `jarvis regression --save-baseline` no lab primeiro.", file=__import__("sys").stderr)
        return 3

    current = _collect(offline=args.offline)
    result = check(base, current)
    if args.json:
        print(json.dumps({"baseline": base, "atual": current, **result}, ensure_ascii=False, indent=2))
    else:
        print(_table(current))
        print(f"REGRESSÃO: {'OK ✓' if result['ok'] else 'FALHOU ✗'}")
        for p in result["problemas"]:
            print(f"  - {p}")
    return 0 if result["ok"] else 1


def _table(report: dict[str, Any]) -> str:
    bench = report.get("benchmark", {})
    lines = [f"Regressão — benchmark total {bench.get('total_ms', 0):.0f}ms"]
    for route, ms in bench.get("rotas", {}).items():
        lines.append(f"  {route:<10} {ms:>8.0f}ms")
    agg = report.get("eval_rag", {})
    top_k = agg.get("top_k", 5)
    lines.append(
        f"  eval-rag  NDCG@{top_k}={agg.get('ndcg_at_k', 0.0):.3f}  "
        f"Recall@{top_k}={agg.get('recall_at_k', 0.0):.3f}  "
        f"P@{top_k}={agg.get('precision_at_k', 0.0):.3f}"
    )
    if agg.get("erros", 0):
        lines.append(f"  (aviso: {agg['erros']} queries do eval falharam — serviços fora?)")
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main_regression())
