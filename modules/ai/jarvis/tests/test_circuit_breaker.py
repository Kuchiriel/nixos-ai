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
    DataClass,
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
# MISSÃO 1 (P0) — Blindagem do fallback: choke point em _try_fallback
# ---------------------------------------------------------------------------


def _cb_with_spy_fallback(failure_threshold: int = 3):
    """CircuitBreaker com fallback espião (conta chamadas, nunca deve vazar)."""
    from unittest.mock import MagicMock
    monitor = BackendHealthMonitor("http://127.0.0.1:19999", cache_ttl_s=0)
    spy = MagicMock(return_value="remoto - NÃO DEVERIA TER SIDO CHAMADO")
    cb = CircuitBreaker(monitor, failure_threshold=failure_threshold, fallback_fn=spy)
    return cb, spy


def _failing_fn(msgs):
    raise RuntimeError("bonsai local down (injetado)")


def test_m1_local_failure_secret_never_egresses() -> None:
    """Falha local + segredo → fallback BLOQUEADO, spy nunca chamado."""
    cb, spy = _cb_with_spy_fallback()
    msgs = [{"role": "user", "content": "Analise este código:\nOPENROUTER_API_KEY=\"sk-or-v1-abc123XYZ456\""}]
    result = cb.execute(msgs, local_fn=_failing_fn)
    assert result["backend"] == "rejected"
    spy.assert_not_called()


def test_m1_secret_without_keywords_blocked() -> None:
    """Valor secreto SEM keyword por perto → SECRET, bloqueado."""
    sf = ContentSafetyFilter()
    cls, reason = sf.classify("revise: gsk_I7lysAgX8I9w6JqkDIVaWGdyb3FY8uty6HNy3")
    assert cls is DataClass.SECRET, reason
    safe, _ = sf.is_safe("revise: gsk_I7lysAgX8I9w6JqkDIVaWGdyb3FY8uty6HNy3")
    assert safe is False


def test_m1_pem_blocked() -> None:
    sf = ContentSafetyFilter()
    cls, _ = sf.classify("-----BEGIN RSA PRIVATE KEY-----\nMIIE...")
    assert cls is DataClass.SECRET


def test_m1_classify_levels() -> None:
    sf = ContentSafetyFilter()
    assert sf.classify("qual é a capital do Brasil?")[0] is DataClass.PUBLIC
    assert sf.classify("ver /etc/nginx/nginx.conf")[0] is DataClass.INTERNAL
    assert sf.classify("o que lembro sobre deploy? recall")[0] is DataClass.CONFIDENTIAL
    assert sf.classify("token=abc password: s3nh4")[0] is DataClass.SECRET


def test_m1_public_still_falls_back() -> None:
    """Prompt PUBLIC + falha local → fallback permitido (sem regressão)."""
    cb, spy = _cb_with_spy_fallback()
    result = cb.execute([{"role": "user", "content": "qual é a capital do Brasil?"}], local_fn=_failing_fn)
    assert result["backend"] == "fallback"
    spy.assert_called_once()


def test_m1_open_circuit_secret_stays_blocked() -> None:
    """Circuito OPEN + CONFIDENTIAL via execute() → rejected, spy nunca chamado."""
    cb, spy = _cb_with_spy_fallback(failure_threshold=1)
    cb.execute([{"role": "user", "content": "warmup"}], local_fn=_failing_fn)
    assert cb.state == CircuitState.OPEN
    spy.reset_mock()  # warmup PUBLIC corretamente usou fallback; zera p/ o teste real
    result = cb.execute(
        [{"role": "user", "content": "resuma minhas memórias episódicas"}],
        local_fn=_failing_fn,
    )
    assert result["backend"] == "rejected"
    spy.assert_not_called()


def test_m1_rejected_counted_in_state() -> None:
    cb, _ = _cb_with_spy_fallback()
    before = cb.state_info["total_rejected"]
    cb.execute(
        [{"role": "user", "content": "vault dump sk-or-v1-zzz"}],
        local_fn=_failing_fn,
    )
    assert cb.state_info["total_rejected"] == before + 1


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
