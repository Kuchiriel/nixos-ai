"""Testes do benchmark da cascata (core/benchmark.py) com mocks das rotas."""

import json

from jarvis.core import benchmark


def test_route_cases_have_legacy_targets() -> None:
    """Metas ancoradas nos benchmarks do legado (fast path ≪ LLM)."""
    routes = {r: meta for r, _, meta in benchmark.ROUTE_CASES}
    assert routes["fastpath"] < routes["doctor"]
    assert routes["doctor"] < routes["agent"]
    assert routes["rag"] < routes["agent"]
    assert routes["fastpath"] <= 200  # legado: 134ms


def test_run_benchmark_measures_all_routes(monkeypatch) -> None:
    """Cada rota é executada e medida; erros não quebram o benchmark."""
    from jarvis.core import router as router_mod

    def _fake_route(query):
        class R:
            handler = "doctor"
        return R()

    def _fast(query):
        import time
        time.sleep(0.01)
        return {"response": "fp"}

    def _doctor():
        return {"response": "ok"}

    def _nixos(query):
        return {"result": "x"}

    def _rag(query, **k):
        return {"hits": [1, 2]}

    def _agent(query, **k):
        return {"response": "r"}

    monkeypatch.setattr(router_mod, "route_request", _fake_route)
    monkeypatch.setattr(router_mod, "handle_fastpath", _fast)
    monkeypatch.setattr(router_mod, "handle_doctor", _doctor)
    monkeypatch.setattr(router_mod, "handle_nixos", _nixos)
    monkeypatch.setattr(router_mod, "handle_rag", _rag)
    monkeypatch.setattr(router_mod, "handle_agent", _agent)

    results = benchmark.run_benchmark()
    assert len(results) == 5
    for r in results:
        assert r.ms >= 0
        assert not r.error
    # fastpath levou ~10ms → ok contra meta 200ms
    fp = next(r for r in results if r.route == "fastpath")
    assert fp.ok
    assert fp.ms > 5


def test_run_benchmark_captures_error(monkeypatch) -> None:
    from jarvis.core import router as router_mod

    def _boom(query):
        raise RuntimeError("serviço fora do ar")

    def _route(query):
        class R:
            handler = "doctor"
        return R()

    monkeypatch.setattr(router_mod, "route_request", _route)
    monkeypatch.setattr(router_mod, "handle_doctor", _boom)

    results = benchmark.run_benchmark()
    agent = next(r for r in results if r.route == "doctor")
    assert agent.error
    assert agent.verdict == "ERROR"
    assert agent.ms >= 0


def test_bench_report_shape() -> None:
    """Relatório tem total, contagem e resultados com meta/verdict."""
    report = benchmark.bench_report(cases=[("doctor", "saúde?", 500)])
    assert "total_ms" in report
    assert "rotas_ok" in report
    assert len(report["results"]) == 1
    r = report["results"][0]
    assert r["route"] == "doctor"
    assert "meta_ms" in r and "verdict" in r


def test_main_benchmark_json(monkeypatch, capsys) -> None:
    import json as _json

    monkeypatch.setattr(benchmark, "run_benchmark", lambda **k: [])
    monkeypatch.setattr(benchmark, "bench_report", lambda **k: {"total_ms": 0, "rotas_ok": "0/0", "results": []})
    rc = benchmark.main_benchmark(["--json"])
    out = capsys.readouterr().out
    assert rc == 0
    assert _json.loads(out)["rotas_ok"] == "0/0"
