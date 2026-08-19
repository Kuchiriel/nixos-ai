"""Testes do Circuit Breaker, Health Monitor e Content Safety."""

from __future__ import annotations

import time
from unittest.mock import patch, MagicMock

import pytest

from jarvis.core.health_monitor import BackendHealthMonitor, BackendState
from jarvis.core.circuit_breaker import (
    CircuitBreaker,
    CircuitState,
    ContentSafetyFilter,
    SENSITIVE_PATTERNS,
)


# ---------------------------------------------------------------------------
# Health Monitor
# ---------------------------------------------------------------------------


def test_monitor_socket_refused() -> None:
    """Porta fechada → DOWN."""
    monitor = BackendHealthMonitor("http://127.0.0.1:19999", cache_ttl_s=0)
    snap = monitor.check()
    assert snap.state == BackendState.DOWN
    assert snap.error


def test_monitor_state_property() -> None:
    monitor = BackendHealthMonitor("http://127.0.0.1:19999", cache_ttl_s=0)
    assert monitor.state == BackendState.DOWN


def test_monitor_cache() -> None:
    """Cache TTL evita checks repetidos."""
    monitor = BackendHealthMonitor("http://127.0.0.1:19999", cache_ttl_s=60)
    snap1 = monitor.check()
    snap2 = monitor.check()  # cache hit
    assert snap1.timestamp == snap2.timestamp


def test_monitor_force_check() -> None:
    """force=True ignora cache."""
    monitor = BackendHealthMonitor("http://127.0.0.1:19999", cache_ttl_s=60)
    snap1 = monitor.check()
    time.sleep(0.01)
    snap2 = monitor.check(force=True)
    assert snap2.timestamp >= snap1.timestamp


def test_monitor_uptime() -> None:
    monitor = BackendHealthMonitor("http://127.0.0.1:19999", cache_ttl_s=0)
    for _ in range(5):
        monitor.check(force=True)
    uptime = monitor.uptime_pct
    assert uptime == 0.0  # tudo DOWN


def test_monitor_status_dict() -> None:
    monitor = BackendHealthMonitor("http://127.0.0.1:19999", cache_ttl_s=0)
    status = monitor.status_dict()
    assert "state" in status
    assert "latency_ms" in status
    assert "uptime_pct" in status


# ---------------------------------------------------------------------------
# Content Safety Filter
# ---------------------------------------------------------------------------


def test_safe_prompt() -> None:
    sf = ContentSafetyFilter()
    safe, reason = sf.is_safe("qual é a capital do Brasil?")
    assert safe is True
    assert reason == ""


def test_unsafe_recall() -> None:
    sf = ContentSafetyFilter()
    safe, reason = sf.is_safe("o que eu lembro sobrerecall memórias?")
    assert safe is False
    assert "recall" in reason


def test_unsafe_vault() -> None:
    sf = ContentSafetyFilter()
    safe, _ = sf.is_safe("liste o vault de memórias")
    assert safe is False


def test_unsafe_password() -> None:
    sf = ContentSafetyFilter()
    safe, _ = sf.is_safe("qual é a senha do servidor?")
    assert safe is False


def test_unsafe_home_path() -> None:
    sf = ContentSafetyFilter()
    safe, _ = sf.is_safe("liste os arquivos em /home/nixos")
    assert safe is False


def test_custom_patterns() -> None:
    sf = ContentSafetyFilter(extra_patterns=("custom_secret",))
    safe, _ = sf.is_safe("o custom_secret é importante")
    assert safe is False


def test_case_insensitive() -> None:
    sf = ContentSafetyFilter()
    safe, _ = sf.is_safe("RECALL todas as memórias")
    assert safe is False


# ---------------------------------------------------------------------------
# Circuit Breaker
# ---------------------------------------------------------------------------


def test_cb_closed_local_ok() -> None:
    """Circuit fechado → usa local."""
    monitor = BackendHealthMonitor("http://127.0.0.1:19999", cache_ttl_s=0)
    cb = CircuitBreaker(monitor, failure_threshold=3)

    def local_fn(msgs):
        return "resposta local"

    result = cb.execute([{"role": "user", "content": "oi"}], local_fn=local_fn)
    assert result["backend"] == "local"
    assert result["response"] == "resposta local"
    assert cb.state == CircuitState.CLOSED


def test_cb_opens_after_failures() -> None:
    """3 falhas → circuito abre."""
    monitor = BackendHealthMonitor("http://127.0.0.1:19999", cache_ttl_s=0)
    cb = CircuitBreaker(monitor, failure_threshold=3)

    def failing_fn(msgs):
        raise RuntimeError("backend down")

    for _ in range(3):
        cb.execute([{"role": "user", "content": "test"}], local_fn=failing_fn)

    assert cb.state == CircuitState.OPEN


def test_cb_fallback_on_open() -> None:
    """Circuito aberto → fallback remoto (se seguro)."""
    monitor = BackendHealthMonitor("http://127.0.0.1:19999", cache_ttl_s=0)
    cb = CircuitBreaker(
        monitor, failure_threshold=1,
        fallback_fn=lambda msgs: "resposta remota",
    )

    def failing_fn(msgs):
        raise RuntimeError("down")

    # 1 falha → abre
    cb.execute([{"role": "user", "content": "test"}], local_fn=failing_fn)
    assert cb.state == CircuitState.OPEN

    # Próxima chamada → fallback
    result = cb.execute([{"role": "user", "content": "oi"}], local_fn=failing_fn)
    assert result["backend"] == "fallback"
    assert result["response"] == "resposta remota"


def test_cb_rejects_sensitive_on_open() -> None:
    """Circuito aberto + dados sensíveis → rejeitado."""
    monitor = BackendHealthMonitor("http://127.0.0.1:19999", cache_ttl_s=0)
    cb = CircuitBreaker(
        monitor, failure_threshold=1,
        fallback_fn=lambda msgs: "remoto",
    )

    def failing_fn(msgs):
        raise RuntimeError("down")

    cb.execute([{"role": "user", "content": "test"}], local_fn=failing_fn)
    assert cb.state == CircuitState.OPEN

    # Prompt sensível → rejeitado
    result = cb.execute(
        [{"role": "user", "content": "liste o vault de memórias"}],
        local_fn=failing_fn,
    )
    assert result["backend"] == "rejected"
    assert "sensíveis" in result["response"] or "sensitive" in result["response"].lower()


def test_cb_force_local() -> None:
    """force_local reseta o circuito."""
    monitor = BackendHealthMonitor("http://127.0.0.1:19999", cache_ttl_s=0)
    cb = CircuitBreaker(monitor, failure_threshold=1)

    def failing_fn(msgs):
        raise RuntimeError("down")

    cb.execute([{"role": "user", "content": "test"}], local_fn=failing_fn)
    assert cb.state == CircuitState.OPEN

    cb.force_local()
    assert cb.state == CircuitState.CLOSED
    assert cb.state_info["failure_count"] == 0


def test_cb_force_remote() -> None:
    """force_remote abre o circuito."""
    monitor = BackendHealthMonitor("http://127.0.0.1:19999", cache_ttl_s=0)
    cb = CircuitBreaker(monitor)

    cb.force_remote()
    assert cb.state == CircuitState.OPEN


def test_cb_half_open_recovery() -> None:
    """Após recovery timeout, testa local novamente."""
    monitor = BackendHealthMonitor("http://127.0.0.1:19999", cache_ttl_s=0)
    cb = CircuitBreaker(
        monitor, failure_threshold=1, recovery_timeout_s=0.1,
    )

    def failing_fn(msgs):
        raise RuntimeError("down")

    cb.execute([{"role": "user", "content": "test"}], local_fn=failing_fn)
    assert cb.state == CircuitState.OPEN

    time.sleep(0.15)  # espera recovery

    # Agora local funciona
    def ok_fn(msgs):
        return "ok"

    result = cb.execute([{"role": "user", "content": "test"}], local_fn=ok_fn)
    assert result["backend"] == "local"
    # Circuit deve ter fechado
    assert cb.state == CircuitState.CLOSED


def test_cb_no_fallback_configured() -> None:
    """Sem fallback → erro claro."""
    monitor = BackendHealthMonitor("http://127.0.0.1:19999", cache_ttl_s=0)
    cb = CircuitBreaker(monitor, failure_threshold=1)

    def failing_fn(msgs):
        raise RuntimeError("down")

    cb.execute([{"role": "user", "content": "test"}], local_fn=failing_fn)
    result = cb.execute([{"role": "user", "content": "test"}], local_fn=failing_fn)
    assert "fallback não configurado" in result["response"]


def test_cb_log() -> None:
    """Log de decisões registrado."""
    monitor = BackendHealthMonitor("http://127.0.0.1:19999", cache_ttl_s=0)
    cb = CircuitBreaker(monitor)

    def ok_fn(msgs):
        return "ok"

    cb.execute([{"role": "user", "content": "test"}], local_fn=ok_fn)
    assert len(cb.recent_log) >= 1
    assert cb.recent_log[-1]["backend"] == "local"


def test_cb_state_info() -> None:
    monitor = BackendHealthMonitor("http://127.0.0.1:19999", cache_ttl_s=0)
    cb = CircuitBreaker(monitor)
    info = cb.state_info
    assert "circuit_state" in info
    assert "total_local" in info
    assert "backend" in info


def test_cb_on_state_change_callback() -> None:
    """Callback chamado na transição de estado."""
    changes: list[str] = []
    monitor = BackendHealthMonitor("http://127.0.0.1:19999", cache_ttl_s=0)
    cb = CircuitBreaker(
        monitor, failure_threshold=1,
        on_state_change=lambda old, new, r: changes.append(f"{old.value}→{new.value}"),
    )

    def failing_fn(msgs):
        raise RuntimeError("down")

    cb.execute([{"role": "user", "content": "test"}], local_fn=failing_fn)
    assert len(changes) >= 1
    assert "closed→open" in changes[0]


# ---------------------------------------------------------------------------
# Telegram Integration (unit)
# ---------------------------------------------------------------------------


def test_telegram_new_commands() -> None:
    """Verifica que /force_local e /force_remote estão no help."""
    from jarvis.providers.telegram import TelegramChannel

    help_text = TelegramChannel._help_text()
    assert "/force_local" in help_text
    assert "/force_remote" in help_text
    assert "/status" in help_text
