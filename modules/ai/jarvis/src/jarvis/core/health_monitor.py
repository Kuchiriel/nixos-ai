"""Monitor de saúde do backend de inferência local (llama.cpp).

Monitora continuamente:
  - Status do socket/porta (connectivity)
  - Latência de health check (response time)
  - Disponibilidade do modelo carregado

Estados:
  - HEALTHY: backend responde < threshold_latency
  - DEGRADED: backend responde mas lento (> threshold_latency)
  - DOWN: backend não responde (timeout/refused)

Overhead mínimo: checks assíncronos com cache de resultado (TTL).
"""

from __future__ import annotations

import time
import socket
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import requests


class BackendState(str, Enum):
    HEALTHY = "healthy"
    DEGRADED = "degraded"
    DOWN = "down"
    UNKNOWN = "unknown"


@dataclass
class HealthSnapshot:
    """Snapshot de saúde do backend em um ponto no tempo."""
    state: BackendState = BackendState.UNKNOWN
    latency_ms: float = 0.0
    model: str = ""
    timestamp: float = field(default_factory=time.time)
    error: str = ""
    consecutive_failures: int = 0


class BackendHealthMonitor:
    """Monitor de saúde leve com cache de TTL.

    Exemplo:
        monitor = BackendHealthMonitor("http://127.0.0.1:8080")
        snap = monitor.check()  # health check com cache
        print(snap.state, snap.latency_ms)
    """

    def __init__(
        self,
        base_url: str = "http://127.0.0.1:8080",
        *,
        latency_threshold_ms: float = 5000.0,
        cache_ttl_s: float = 10.0,
        socket_timeout_s: float = 3.0,
        http_timeout_s: float = 5.0,
    ) -> None:
        self._base = base_url.rstrip("/")
        self._latency_threshold_ms = latency_threshold_ms
        self._cache_ttl_s = cache_ttl_s
        self._socket_timeout_s = socket_timeout_s
        self._http_timeout_s = http_timeout_s
        self._last_check: HealthSnapshot | None = None
        self._last_check_time: float = 0.0
        self._history: list[HealthSnapshot] = []
        self._max_history = 100

    @property
    def state(self) -> BackendState:
        """Estado atual (com cache)."""
        snap = self.check()
        return snap.state

    @property
    def last_snapshot(self) -> HealthSnapshot | None:
        return self._last_check

    def check(self, force: bool = False) -> HealthSnapshot:
        """Executa health check (com cache se não forçado)."""
        now = time.time()
        if not force and self._last_check and (now - self._last_check_time) < self._cache_ttl_s:
            return self._last_check

        snap = HealthSnapshot(timestamp=now)

        # 1. Socket check (rápido, ~1ms)
        if not self._check_socket():
            snap.state = BackendState.DOWN
            snap.error = "socket refused/timeout"
            snap.consecutive_failures = (self._last_check.consecutive_failures + 1) if self._last_check else 1
            self._record(snap)
            return snap

        # 2. HTTP health check (com latency)
        t0 = time.time()
        try:
            resp = requests.get(
                f"{self._base}/health",
                timeout=self._http_timeout_s,
            )
            snap.latency_ms = round((time.time() - t0) * 1000, 1)

            if resp.status_code == 200:
                snap.state = (
                    BackendState.HEALTHY
                    if snap.latency_ms < self._latency_threshold_ms
                    else BackendState.DEGRADED
                )
                # Tenta obter modelo
                try:
                    models_resp = requests.get(
                        f"{self._base}/v1/models",
                        timeout=self._http_timeout_s,
                    )
                    if models_resp.status_code == 200:
                        data = models_resp.json()
                        if data.get("data"):
                            snap.model = data["data"][0].get("id", "")
                except Exception:  # noqa: BLE001
                    pass
                snap.consecutive_failures = 0
            else:
                snap.state = BackendState.DOWN
                snap.error = f"HTTP {resp.status_code}"
                snap.consecutive_failures = (self._last_check.consecutive_failures + 1) if self._last_check else 1

        except requests.Timeout:
            snap.state = BackendState.DOWN
            snap.error = "timeout"
            snap.consecutive_failures = (self._last_check.consecutive_failures + 1) if self._last_check else 1
        except requests.RequestException as exc:
            snap.state = BackendState.DOWN
            snap.error = str(exc)[:200]
            snap.consecutive_failures = (self._last_check.consecutive_failures + 1) if self._last_check else 1

        self._record(snap)
        return snap

    def _check_socket(self) -> bool:
        """Verifica se a porta está aceitando conexões."""
        try:
            # Extrai host e porta da URL
            url = self._base.replace("http://", "").replace("https://", "")
            host_port = url.split("/")[0]
            if ":" in host_port:
                host, port = host_port.rsplit(":", 1)
            else:
                host, port = host_port, "80"
            s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            s.settimeout(self._socket_timeout_s)
            result = s.connect_ex((host, int(port)))
            s.close()
            return result == 0
        except (OSError, ValueError):
            return False

    def _record(self, snap: HealthSnapshot) -> None:
        """Registra snapshot no histórico."""
        self._last_check = snap
        self._last_check_time = snap.timestamp
        self._history.append(snap)
        if len(self._history) > self._max_history:
            self._history = self._history[-self._max_history:]

    @property
    def uptime_pct(self) -> float:
        """Percentual de uptime nas últimas checks."""
        if not self._history:
            return 100.0
        healthy = sum(1 for s in self._history if s.state in (BackendState.HEALTHY, BackendState.DEGRADED))
        return round(healthy / len(self._history) * 100, 1)

    @property
    def avg_latency_ms(self) -> float:
        """Latência média das checks saudáveis."""
        latencies = [s.latency_ms for s in self._history if s.state != BackendState.DOWN and s.latency_ms > 0]
        if not latencies:
            return 0.0
        return round(sum(latencies) / len(latencies), 1)

    def status_dict(self) -> dict[str, Any]:
        """Status completo em dict."""
        snap = self.check()
        return {
            "state": snap.state.value,
            "latency_ms": snap.latency_ms,
            "model": snap.model,
            "uptime_pct": self.uptime_pct,
            "avg_latency_ms": self.avg_latency_ms,
            "consecutive_failures": snap.consecutive_failures,
            "error": snap.error,
        }
