"""nv-gate — o gate de taxa do free tier NVIDIA (03/11).

CONTEXTO: o free tier do integrate.api.nvidia.com responde 40 requests/minute
por chave. Com 2-3 agentes simultaneos a rajada estoura o limite e o turno
inteiro morre em "Too Many Requests" (o opencode so faz 3 retries rapidos).
`scripts/nv-gate.py` e um proxy transparente que vira a rajada em fila:
token bucket compartilhado + retry com backoff no 429.

Estes testes existem para o gate NAO regredir para:
  * passthrough sem limite (volta o 429);
  * retry que devolve o erro ao cliente em vez de tentar de novo;
  * fila que trava o cliente em vez de esperar.
"""

import http.server
import importlib.util
import json
import threading
import time
import urllib.request
from pathlib import Path

import pytest


def _find_upwards(*candidates: str) -> Path | None:
    """Procura um arquivo subindo a arvore (o pacote nix so leva ./jarvis)."""
    for parent in Path(__file__).resolve().parents:
        for candidate in candidates:
            path = parent / candidate
            if path.is_file():
                return path
    return None


def _load_gate():
    path = _find_upwards("scripts/nv-gate.py")
    if path is None:
        # No sandbox do nix o pacote so leva ./jarvis -> o script nao existe:
        # o modulo inteiro e pulado (allow_module_level obrigatorio no pytest 8).
        pytest.skip("scripts/nv-gate.py nao encontrado neste checkout", allow_module_level=True)
    spec = importlib.util.spec_from_file_location("nv_gate", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


nv_gate = _load_gate()


def test_bucket_limits_rate_and_refuses_when_full():
    bucket = nv_gate.Bucket(rpm=60, burst=2)
    granted, _ = bucket.take(max_wait=0.2)
    assert granted is True
    granted, _ = bucket.take(max_wait=0.2)
    assert granted is True
    # sem tokens: com max_wait curto a fila recusa (429 pro cliente)
    granted, waited = bucket.take(max_wait=0.2)
    assert granted is False
    assert waited <= 0.5


def test_bucket_refills_over_time():
    bucket = nv_gate.Bucket(rpm=60, burst=1)  # 1 token/s
    assert bucket.take(max_wait=0.1)[0] is True
    assert bucket.take(max_wait=0.1)[0] is False
    time.sleep(1.1)  # ~1 token novo
    assert bucket.take(max_wait=0.1)[0] is True


def _fake_upstream(responses):
    """Servidor que devolve uma sequencia de status (429, 429, 200...)."""
    state = {"n": 0}

    class Handler(http.server.BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def do_POST(self):
            index = min(state["n"], len(responses) - 1)
            state["n"] += 1
            code = responses[index]
            body = b'{"ok":true}' if code == 200 else b""
            self.send_response(code)
            if code == 429:
                self.send_header("Retry-After", "0")
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args):
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, state


def test_gate_retries_429_and_returns_the_answer():
    server, state = _fake_upstream([429, 429, 200])
    gate = nv_gate.Gate
    gate.upstream = f"http://127.0.0.1:{server.server_address[1]}"
    gate.bucket = nv_gate.Bucket(rpm=600, burst=10)
    gate.max_wait = 5
    gate.backoff_start = 0.01  # backoff testável
    gate.stats = nv_gate.Stats()

    from http.server import ThreadingHTTPServer

    proxy = ThreadingHTTPServer(("127.0.0.1", 0), gate)
    threading.Thread(target=proxy.serve_forever, daemon=True).start()
    try:
        request = urllib.request.Request(
            f"http://127.0.0.1:{proxy.server_address[1]}/v1/chat/completions",
            data=b'{"model":"x"}',
            headers={"Content-Type": "application/json", "Authorization": "Bearer test"},
            method="POST",
        )
        with urllib.request.urlopen(request, timeout=30) as response:
            assert response.status == 200
            assert response.read() == b'{"ok":true}'
        assert state["n"] == 3, "o gate deveria ter tentado 3x"
        assert gate.stats.snapshot()["upstream_429"] == 2
        assert gate.stats.snapshot()["retries"] == 2
    finally:
        proxy.shutdown()
        server.shutdown()


def test_gate_health_has_no_secret():
    stats = nv_gate.Stats()
    snapshot = stats.snapshot()
    assert "authorization" not in json.dumps(snapshot).lower()
    assert "api_key" not in json.dumps(snapshot).lower()


def test_catalog_gate_is_below_the_published_limit():
    path = _find_upwards("modules/ai/free-providers.json", "free-providers.json")
    if path is None:
        pytest.skip("catalogo nao encontrado neste checkout")
    catalog = json.loads(path.read_text())
    gate = catalog["providers"]["nvidia"].get("gate")
    if not gate:
        pytest.skip("provider nvidia sem gate configurado")
    # 40 RPM = limite publicado do free tier; folga obrigatoria.
    assert gate["rpm"] <= 40
    assert gate["burst"] >= 1
    assert gate["port"] > 1024
