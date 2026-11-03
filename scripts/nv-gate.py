#!/usr/bin/env python3
"""nv-gate — transparent rate-limit gate for the NVIDIA free tier (integrate.api.nvidia.com).

Purpose: the free tier answers 40 requests/minute per key (NVIDIA throttles
"free-tier abusers" harder — multiple agents bursting look exactly like that).
The opencode client retries 3x fast and then fails the whole agent turn with
"Too Many Requests". This gate sits in front of the provider and turns the
burst into a queue:

  * token bucket shared by every client (the owner + all agents) — default
    24 requests/minute, burst 4 (margin under the 40 RPM cap);
  * upstream 429 -> retry with exponential backoff (honours Retry-After), so
    the client sees the answer instead of an error;
  * SSE streaming is passed through chunk by chunk (no buffering);
  * the Authorization header is forwarded untouched: the gate NEVER sees or
    stores a key — systemd's EnvironmentFile is not involved.

Usage:
  nv-gate.py [--port 8095] [--rpm 24] [--burst 4] [--upstream https://integrate.api.nvidia.com]

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
                    return True, waited
                need = (1.0 - self.tokens) / self.rate
            if now + need > deadline:
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
        }

    def bump(self, key: str, value: float = 1) -> None:
        with self.lock:
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
    verbose = False

    def log_message(self, fmt: str, *args) -> None:  # noqa: A003
        if self.verbose:
            sys.stderr.write("nv-gate: " + (fmt % args) + "\n")

    def _forward(self) -> None:
        self.stats.bump("requests")
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length) if length else None

        headers = {}
        for key, value in self.headers.items():
            if key.lower() in HOP_BY_HOP or key.lower() in ("host", "authorization-mirror"):
                continue
            headers[key] = value

        granted, waited = self.bucket.take(self.max_wait)
        if waited:
            self.stats.bump("queued_seconds", waited)
        if not granted:
            self.stats.bump("client_429")
            self._json(429, {"error": {"message": "nv-gate: rate limit queue exhausted",
                                       "type": "rate_limit_error"}})
            return

        url = self.upstream + self.path
        attempt = 0
        backoff = 2.0
        while True:
            attempt += 1
            req = urllib.request.Request(url, data=body, headers=headers, method=self.command)
            try:
                with urllib.request.urlopen(req, timeout=600) as resp:
                    self._relay(resp)
                    self.stats.bump("ok")
                    return
            except urllib.error.HTTPError as exc:
                if exc.code == 429 and attempt <= self.max_retries:
                    self.stats.bump("upstream_429")
                    self.stats.bump("retries")
                    delay = backoff
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    if retry_after:
                        try:
                            delay = max(delay, min(float(retry_after), 60.0))
                        except ValueError:
                            pass
                    self.log_message("upstream 429, retry %d in %.1fs", attempt, delay)
                    time.sleep(delay)
                    backoff = min(backoff * 2, 30.0)
                    continue
                payload = exc.read()[:4000]
                self.stats.bump("errors")
                self._relay_error(exc.code, payload)
                return
            except (urllib.error.URLError, OSError) as exc:
                self.stats.bump("errors")
                self._json(502, {"error": {"message": f"nv-gate: upstream unreachable: {exc}",
                                           "type": "upstream_error"}})
                return

    def _relay(self, resp) -> None:
        self.send_response(resp.status)
        for key, value in resp.headers.items():
            if key.lower() in HOP_BY_HOP:
                continue
            self.send_header(key, value)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()
        try:
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
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _relay_error(self, code: int, payload: bytes) -> None:
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
            pass

    def _json(self, code: int, data: dict) -> None:
        payload = json.dumps(data).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(payload)))
        self.end_headers()
        try:
            self.wfile.write(payload)
        except (BrokenPipeError, ConnectionResetError):
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


def main() -> int:
    parser = argparse.ArgumentParser(description="rate-limit gate for NVIDIA free tier")
    parser.add_argument("--port", type=int, default=int(os.environ.get("NV_GATE_PORT", "8095")))
    parser.add_argument("--rpm", type=float, default=float(os.environ.get("NV_GATE_RPM", "24")))
    parser.add_argument("--burst", type=int, default=int(os.environ.get("NV_GATE_BURST", "4")))
    parser.add_argument("--upstream", default=os.environ.get(
        "NV_GATE_UPSTREAM", "https://integrate.api.nvidia.com"))
    parser.add_argument("--max-wait", type=float, default=float(os.environ.get("NV_GATE_MAX_WAIT", "120")))
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args()

    Gate.upstream = args.upstream.rstrip("/")
    Gate.bucket = Bucket(args.rpm, args.burst)
    Gate.max_wait = args.max_wait
    Gate.verbose = args.verbose

    server = ThreadingHTTPServer(("127.0.0.1", args.port), Gate)
    server.daemon_threads = True
    sys.stderr.write(
        f"nv-gate: listening on 127.0.0.1:{args.port} -> {Gate.upstream} "
        f"(rpm={args.rpm}, burst={args.burst})\n")
    sys.stderr.flush()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
