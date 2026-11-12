#!/usr/bin/env python3
"""nv-gate — transparent rate-limit gate for the NVIDIA free tier (integrate.api.nvidia.com).

Purpose: the NVIDIA free tier has a ~40 requests/minute nominal cap, but the
EFFECTIVE limit measured against the endpoint is ~8 requests/minute (a ramp of
1.5s between requests already hit 429 on request #2; with 8 concurrent clients
only 6 of 120 passed = 8/min in a 60s window). NVIDIA also throttles
"free-tier abusers" harder — multiple agents bursting look exactly like that.
The opencode client retries 3x fast and then fails the whole agent turn with
"Too Many Requests". This gate sits in front of the provider and turns the
burst into a queue:

  * token bucket shared by every client (the owner + all agents) — default
    8 requests/minute, burst 2 (measured effective ceiling, not the nominal
    40; source: opencode/NVIDIA_NIM_GROUND_TRUTH.md §5 no repo do bus);
  * upstream 429 -> retry with exponential backoff (honours Retry-After), so
    the client sees the answer instead of an error;
  * upstream 502/503/504 and connection resets -> also retried (the NIM edge
    kills long prefills; retrying inside a total time budget smaller than
    the opencode headerTimeout turns a dead turn into a slow answer);
  * SSE streaming is passed through chunk by chunk (no buffering);
  * the Authorization header is forwarded untouched: the gate NEVER sees or
    stores a key — systemd's EnvironmentFile is not involved.

Usage:
  nv-gate.py [--port 8095] [--rpm 8] [--burst 2] [--upstream https://integrate.api.nvidia.com]

Endpoints:
  * everything else -> forwarded to <upstream><path>?<query>
  * GET /__gate/health -> JSON counters (no secrets)

Example:
  opencode provider nvidia -> options.baseURL = http://127.0.0.1:8095/v1
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

HOP_BY_HOP = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailers", "transfer-encoding", "upgrade", "content-encoding",
    "content-length",
}


class Bucket:
    """Token bucket: `rpm` requests per minute, `burst` instant."""

    def __init__(self, rpm: float, burst: int) -> None:
        self.rate = max(rpm, 0.1) / 60.0
        self.capacity = float(max(burst, 1))
        self.tokens = self.capacity
        self.updated = time.monotonic()
        self.lock = threading.Lock()
        # (08/11) Quantos segundos o token ainda precisa para a ULTIMA
        # recusa. Sem isso o log dizia "queue exhausted after 0.0s wait",
        # que e mentira: o pedido foi recusado na hora porque o token
        # precisaria de mais tempo que o max_wait.
        self.last_need = 0.0

    def take(self, max_wait: float) -> tuple[bool, float]:
        """Consume one token; returns (granted, waited_seconds)."""
        waited = 0.0
        deadline = time.monotonic() + max_wait
        while True:
            with self.lock:
                now = time.monotonic()
                self.tokens = min(self.capacity, self.tokens + (now - self.updated) * self.rate)
                self.updated = now
                if self.tokens >= 1.0:
                    self.tokens -= 1.0
                    self.last_need = 0.0
                    return True, waited
                need = (1.0 - self.tokens) / self.rate
            if now + need > deadline:
                self.last_need = need
                return False, waited
            sleep_for = min(need, max_wait - waited)
            if sleep_for <= 0:
                return False, waited
            time.sleep(sleep_for)
            waited += sleep_for


class Stats:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.counts = {
            "requests": 0, "ok": 0, "upstream_429": 0, "client_429": 0,
            "errors": 0, "retries": 0, "queued_seconds": 0.0,
            # (04/11) contadores dos novos códigos retentáveis (o 504 do
            # edge do NIM era o que matava o turno em silêncio).
            "upstream_502": 0, "upstream_503": 0, "upstream_504": 0,
            "upstream_io": 0,
        }

    def bump(self, key: str, value: float = 1) -> None:
        with self.lock:
            # setdefault: contador novo não pode virar KeyError dentro do
            # handler (o traceback matava a conexão sem resposta).
            self.counts.setdefault(key, 0)
            if key.endswith("seconds"):
                self.counts[key] += value
            else:
                self.counts[key] += value

    def snapshot(self) -> dict:
        with self.lock:
            return dict(self.counts)


class Gate(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "nv-gate/1.0"

    # injected by main()
    upstream = "https://integrate.api.nvidia.com"
    bucket: Bucket
    stats = Stats()
    max_wait = 120.0
    max_retries = 6
    backoff_start = 2.0
    verbose = False
    # (04/11) ORÇAMENTO DE TEMPO do retry. O opencode aborta o request no
    # headerTimeout (900s na config) — se o gate ainda estuviera tentando
    # depois disso, o turno já morreu sem resposta. O orçamento do gate é
    # MENOR que o headerTimeout do opencode: o gate desiste primeiro, com
    # um erro claro, e sobra tempo pro opencode fazer o retry dele.
    retry_budget = 480.0
    # (04/11) CÓDIGOS RETENTÁVEIS. 429 = limite de taxa. 502/503/504 =
    # edge/infra do NIM: com contexto grande o prefill passa do limite do
    # edge e o NIM devolve 504 — o turno morria pq o gate só retentava
    # 429. Medido: prompt mínimo = 200 em ~2s; o 504 só aparece com
    # contexto grande (e aí repetir costuma dar certo).
    retry_codes = (429, 502, 503, 504)
    # (09/11, sweep-2026-11) GUARDA DE CONTEXTO: request que o upstream ja
    # rejeitou por context_length nao precisa ser reenviado. Medido 09/11:
    # 91 rejeicoes em 6h, todas com request > 1MB (media 5,4MB) =>
    # o upstream respondia {'details':{'type':'context_length','limit':
    # 1048576,'actual':1541675}} e o gate repassava o 400 ao cliente.
    # Cada reenvio consome o bucket (8 RPM) por segundos de upstream, e o
    # efeito colateral era a FILA: 14 esperas (ate 21s) em 6h, que é o
    # sintoma que mata os clientes de timeout curto (o coord-mcp, 25s).
    # Aqui o gate aprende o tamanho rejeitado por path (modelo) e falha
    # rapido o que é do mesmo tamanho, sem gastar upstream nem bucket.
    # A correcao de raiz continua sendo o TETO DE SESSAO (o
    # limit.input do opencode): o request nao deveria chegar perto do
    # limite da API. Este guarda e o disjuntor, nao a correcao.
    ctx_reject_bytes: dict[str, int] = {}
    ctx_guard_ratio = 0.9
    # (09/11, sweep-2026-11) VIA PRIORITARIA: os requests PEQUENOS (as
    # entregas da frota, o coord-mcp, o heartbeat) nao podem ficar na fila
    # dos monsters de 5,4 MB. Medido: 14 esperas de ate 21s em 6h (com o
    # bucket de 8 RPM), e o sintoma visivel e o cliente de timeout curto
    # (o coord-mcp, 25s) morrendo antes da resposta. Aqui os pequenos
    # tem o proprio bucket, mais rapido, e os grandes ficam no de sempre.
    # O FATOR e 2 (nao 4) de proposito: 8 (grandes) + 16 (pequenos) = 24
    # RPM, abaixo do teto de 40 RPM do upstream, para nao estourar a cota.
    small_bucket = None
    small_bytes = 262144
    small_rpm_factor = 2.0

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        if self.verbose:
            sys.stderr.write("nv-gate: " + (fmt % args) + "\n")

    def warn(self, fmt: str, *args) -> None:  # noqa: A003
        """Evento de taxa: SEMPRE no journal (sem depender de --verbose).

        Medido 08/11: com o log so no --verbose, o servico (que roda sem a
        flag) deixava 0 linhas no journal => nao dava para dizer se o 429 do
        cliente era o gate (fila do bucket esgotada) ou o upstream (NIM),
        nem quantos retries aconteceu. Agora: 1 linha por evento.
        """
        sys.stderr.write("nv-gate: WARN " + (fmt % args) + "\n")
        sys.stderr.flush()

    def _forward(self) -> None:
        self.stats.bump("requests")
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None

        headers = {}
        for key, value in self.headers.items():
            if key.lower() in HOP_BY_HOP or key.lower() in ("host", "authorization-mirror"):
                continue
            headers[key] = value

        bucket = self.bucket
        if self.small_bucket is not None and length <= self.small_bytes:
            bucket = self.small_bucket
        granted, waited = bucket.take(self.max_wait)
        if waited:
            self.stats.bump("queued_seconds", waited)
            # (08/11) Medido no sweep: com burst de 6 requests, 3 voltaram 200
            # e 3 NAO completaram no timeout do cliente (25s no curl) — o gate
            # ESPERA o token em vez de recusar, entao a fila vira o consumidor
            # do tempo e o opencode ve "socket closed unexpectedly" (nao 429).
            # A espera e' o sintoma; sem log nao ha como ver.
            if waited >= 10.0:
                self.warn("queue wait %.1fs (bucket %s) — the client may have "
                          "timed out before the token came", waited,
                          "rpm=%.0f burst=%d" % (bucket.rate * 60,
                                                 int(bucket.capacity)))
        if not granted:
            self.stats.bump("client_429")
            self.warn("gate queue exhausted: token needs %.1fs, max_wait %.0fs "
                      "(waited %.1fs, request %d bytes) -> 429 to the client",
                      bucket.last_need, self.max_wait, waited, length)
            self._json(429, {"error": {"message": "nv-gate: rate limit queue exhausted",
                                       "type": "rate_limit_error"}})
            return

        url = self.upstream + self.path
        attempt = 0
        backoff = self.backoff_start
        deadline = time.monotonic() + self.retry_budget
        # (09/11) DISJUNTOR DE CONTEXTO: se o upstream ja recusou por
        # context_length um request deste path com tamanho >= 90% daquele,
        # este request vai ser recusado tambem. Falha aqui, sem gastar o
        # upstream nem o bucket (a fila do bucket e o sintoma que mata os
        # clientes de timeout curto). A correcao de raiz e o teto de sessao
        # no opencode; aqui e so para nao queimar cota com reenvio inutil.
        ctx_limit = self.ctx_reject_bytes.get(self.path, 0)
        if ctx_limit and length >= ctx_limit * self.ctx_guard_ratio:
            self.stats.bump("ctx_short_circuit")
            self.warn("context guard: request %d bytes >= %d bytes que o upstream "
                      "ja recusou por context_length -> 400 local, sem reenviar",
                      length, ctx_limit)
            self._json(400, {"error": {
                "message": "nv-gate: request too large for the upstream context",
                "type": "Bad Request",
                "code": 400,
                "details": {"type": "context_length",
                            "limit": ctx_limit,
                            "actual": length}}})
            return
        while True:
            attempt += 1
            req = urllib.request.Request(url, data=body, headers=headers, method=self.command)
            try:
                with urllib.request.urlopen(req, timeout=600) as resp:
                    self._relay(resp)
                    self.stats.bump("ok")
                    return
            except urllib.error.HTTPError as exc:
                retriable = (exc.code in self.retry_codes
                             and attempt <= self.max_retries
                             and time.monotonic() + backoff < deadline)
                if retriable:
                    self.stats.bump(f"upstream_{exc.code}")
                    self.stats.bump("retries")
                    delay = backoff
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    if retry_after:
                        try:
                            delay = max(delay, min(float(retry_after), 60.0))
                        except ValueError:
                            pass
                    self.warn("upstream %d, retry %d in %.1fs (request %d bytes)",
                              exc.code, attempt, delay, length)
                    time.sleep(delay)
                    backoff = min(backoff * 2, 30.0)
                    continue
                payload = exc.read()[:4000]
                self.stats.bump("errors")
                # (09/11) CONTEXTO: se o upstream recusou por context_length,
                # guarda o tamanho recusado DESTE path (modelo) para falhar
                # rapido o proximo request do mesmo tamanho.
                if exc.code == 400 and b"context_length" in payload:
                    prev = self.ctx_reject_bytes.get(self.path, 0)
                    self.ctx_reject_bytes[self.path] = max(prev, length)
                    self.stats.bump("ctx_rejected")
                # O CORPO do erro do upstream e o unico lugar com a verdade:
                # o cliente opencode ve "Cannot connect to API" (o 400 vira
                # erro de conexao generico) e o log do cliente nao guarda o
                # corpo. Medido 08/11: o upstream aceita payload de 6,9 MiB
                # (200), entao o 400 do pedido de compactacao (5,37 MB) nao
                # e tamanho — e a razao esta no corpo. Uma linha, truncada.
                detail = " ".join(payload.decode("utf-8", "replace").split())[:240]
                self.warn("upstream %d not retried (attempt %d, request %d bytes) "
                          "-> relayed to client | upstream says: %s",
                          exc.code, attempt, length, detail or "(vazio)")
                self._relay_error(exc.code, payload)
                return
            except (urllib.error.URLError, OSError) as exc:
                # (04/11) timeout/reset do upstream = transitório: o edge
                # matou a conexão (o NIM com contexto grande passa de
                # 600s de prefill). Retenta dentro do orçamento.
                if (attempt <= self.max_retries
                        and time.monotonic() + backoff < deadline):
                    self.stats.bump("upstream_io")
                    self.stats.bump("retries")
                    self.log_message("upstream io %s, retry %d in %.1fs",
                                     exc, attempt, backoff)
                    time.sleep(backoff)
                    backoff = min(backoff * 2, 30.0)
                    continue
                self.stats.bump("errors")
                self._json(502, {"error": {"message": f"nv-gate: upstream unreachable: {exc}",
                                           "type": "upstream_error"}})
                return

    def _relay(self, resp) -> None:
        try:
            self.send_response(resp.status)
            for key, value in resp.headers.items():
                if key.lower() in HOP_BY_HOP:
                    continue
                self.send_header(key, value)
            self.send_header("Transfer-Encoding", "chunked")
            self.end_headers()
            while True:
                chunk = resp.read(8192)
                if not chunk:
                    break
                self.wfile.write(f"{len(chunk):X}\r\n".encode())
                self.wfile.write(chunk)
                self.wfile.write(b"\r\n")
                self.wfile.flush()
            self.wfile.write(b"0\r\n\r\n")
            self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError, OSError):
            pass
        except Exception as exc:
            # Um client que desiste no meio do relay NAO pode derrubar o
            # processo inteiro (causa de varias quedas hoje, retries de 400/
            # 429 com corpo gigante). Log curto, segue o baile.
            try:
                self.warn("relay falhou apos %s: %s", getattr(resp, "status", "?"), exc)
            except Exception:
                pass

    def _relay_error(self, code: int, payload: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError, OSError):
            pass

    def _json(self, code: int, data: dict) -> None:
        payload = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError, OSError):
            pass

    def do_GET(self) -> None:
        if self.path.startswith("/__gate/health"):
            self._json(200, {"ok": True, "rpm": self.bucket.rate * 60,
                             "burst": int(self.bucket.capacity), **self.stats.snapshot()})
            return
        self._forward()

    def do_POST(self) -> None:
        self._forward()

    def do_DELETE(self) -> None:
        self._forward()

    def handle_error(self, request, client_address) -> None:
        exc = sys.exc_info()[1]
        if isinstance(exc, (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, TimeoutError)):
            return
        super().handle_error(request, client_address)


def main() -> int:
    parser = argparse.ArgumentParser(description="rate-limit gate for NVIDIA free tier")
    parser.add_argument("--port", type=int, default=int(os.environ.get("NV_GATE_PORT", "8095")))
    parser.add_argument("--rpm", type=float, default=float(os.environ.get("NV_GATE_RPM", "24")))
    parser.add_argument("--burst", type=int, default=int(os.environ.get("NV_GATE_BURST", "4")))
    parser.add_argument("--upstream", default=os.environ.get(
        "NV_GATE_UPSTREAM", "https://integrate.api.nvidia.com"))
    parser.add_argument("--max-wait", type=float, default=float(os.environ.get("NV_GATE_MAX_WAIT", "120")))
    parser.add_argument("--retry-budget", type=float,
                        default=float(os.environ.get("NV_GATE_RETRY_BUDGET", "480")))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    Gate.upstream = args.upstream.rstrip("/")
    Gate.bucket = Bucket(args.rpm, args.burst)
    # (09/11) via prioritaria para os pedidos pequenos (ver Gate.small_bucket)
    Gate.small_bucket = Bucket(args.rpm * Gate.small_rpm_factor,
                               args.burst * 2)
    Gate.max_wait = args.max_wait
    Gate.retry_budget = args.retry_budget
    Gate.verbose = args.verbose

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Gate)
    server.daemon_threads = True
    sys.stderr.write(
        f"nv-gate: listening on 127.0.0.1:{args.port} -> {Gate.upstream} "
        f"(rpm={args.rpm}, burst={args.burst}, retry_budget={args.retry_budget}s)\n")
    sys.stderr.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
