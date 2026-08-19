"""Benchmark da cascata — mede a latência de cada rota do `jarvis ask`.

O legado media tudo (BENCHMARKS_BEFORE_AFTER.md): com fast paths, greetings
foram de 19.7s → 134ms (134x), math 19s → 122ms, system status 17.9s → 350ms.
Este benchmark registra a mesma métrica por rota, para sabermos onde estão os
gargalos e regredir de forma objetiva.

Metas (alvo = latência por rota, no host final):
  - fastpath:  < 200ms  (zero LLM, regra declarativa)
  - doctor:    < 500ms  (health checks HTTP locais)
  - nixos:     < 1.5s   (mcp-nixos via stdio)
  - rag:       < 1.5s   (busca híbrida Qdrant)
  - agent:     < 30s    (LLM local + tools — o mais caro, só quando necessário)
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Callable

# (rota, exemplo de pedido, meta em ms)
ROUTE_CASES: list[tuple[str, str, float]] = [
    ("fastpath", "leia o livro hobbit", 200),
    ("doctor", "como está a saúde do sistema?", 500),
    ("nixos", "existe services.qdrant.enable?", 1500),
    ("rag", "onde está vector_store.py?", 1500),
    ("agent", "explique o que é o mcp-nixos", 30000),
]


@dataclass
class BenchResult:
    route: str
    query: str
    ms: float
    meta_ms: float
    ok: bool
    error: str = ""
    detail: dict[str, Any] = field(default_factory=dict)

    @property
    def verdict(self) -> str:
        if self.error:
            return "ERROR"
        return "OK" if self.ok else "LENTO"


def _time_call(fn: Callable[[], Any]) -> tuple[float, Any]:
    start = time.perf_counter()
    result = fn()
    return (time.perf_counter() - start) * 1000.0, result


def run_benchmark(
    cases: list[tuple[str, str, float]] | None = None,
    *,
    top_k: int = 5,
) -> list[BenchResult]:
    """Executa as rotas da cascata e mede a latência de cada uma."""
    from jarvis.core.router import (
        handle_agent, handle_doctor, handle_fastpath, handle_nixos, handle_rag,
        route_request,
    )

    results: list[BenchResult] = []
    for route, query, meta_ms in (cases or ROUTE_CASES):
        res = BenchResult(route=route, query=query, ms=0.0, meta_ms=meta_ms, ok=False)

        def run() -> dict[str, Any]:
            r = route_request(query)
            if r.handler != route:
                res.detail["roteou_para"] = r.handler
            if route == "fastpath":
                return handle_fastpath(query)
            if route == "doctor":
                return handle_doctor()
            if route == "nixos":
                return handle_nixos(query)
            if route == "rag":
                return handle_rag(query, top_k=top_k)
            return handle_agent(query)

        try:
            ms, out = _time_call(run)
            res.ms = ms
            res.ok = ms <= meta_ms
            if "error" in out and out["error"]:
                res.error = str(out["error"])[:120]
            if route == "rag":
                res.detail["hits"] = len(out.get("hits", []))
            if route == "agent":
                res.detail["turns"] = out.get("_turns")
        except Exception as exc:  # noqa: BLE001 — benchmark nunca quebra
            res.error = str(exc)[:120]
        results.append(res)
    return results


def bench_report(
    cases: list[tuple[str, str, float]] | None = None,
    *,
    top_k: int = 5,
) -> dict[str, Any]:
    """Relatório em dict (JSON) + tabela legível."""
    results = run_benchmark(cases, top_k=top_k)
    total_ms = sum(r.ms for r in results)
    ok_count = sum(1 for r in results if r.ok and not r.error)
    return {
        "total_ms": round(total_ms, 1),
        "rotas_ok": f"{ok_count}/{len(results)}",
        "results": [
            {
                "route": r.route,
                "query": r.query,
                "ms": round(r.ms, 1),
                "meta_ms": r.meta_ms,
                "ok": r.ok,
                "verdict": r.verdict,
                **(r.detail or {}),
                **({"error": r.error} if r.error else {}),
            }
            for r in results
        ],
    }


def _table(report: dict[str, Any]) -> str:
    lines = [
        f"Benchmark da cascata — total {report['total_ms']}ms, rotas OK {report['rotas_ok']}",
        "-" * 88,
        f"{'rota':<10} {'meta':>8} {'ms':>8}  {'verdict':<7} query",
        "-" * 88,
    ]
    for r in report["results"]:
        lines.append(
            f"{r['route']:<10} {r['meta_ms']:>7.0f}ms {r['ms']:>7.1f}ms  "
            f"{r['verdict']:<7} {r['query'][:50]}"
        )
        for k, v in r.items():
            if k not in ("route", "query", "ms", "meta_ms", "ok", "verdict"):
                lines.append(f"  · {k}: {v}")
    return "\n".join(lines)


def main_benchmark(argv: list[str] | None = None) -> int:
    """Entry point CLI: jarvis benchmark [--top-k N] [--json]."""
    import argparse

    parser = argparse.ArgumentParser(prog="jarvis benchmark", description="Mede latência por rota da cascata")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--json", action="store_true", help="saída JSON pura")
    args = parser.parse_args(argv)

    report = bench_report(top_k=args.top_k)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(_table(report))
    return 0 if report["rotas_ok"] == f"{len(report['results'])}/{len(report['results'])}" else 1


if __name__ == "__main__":
    raise SystemExit(main_benchmark())
