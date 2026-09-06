"""Testes do Event Bus local (core/eventbus.py)."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import pytest

from jarvis.core.eventbus import EventBus, Event, get_bus


# ---------------------------------------------------------------------------
# Síncrono (CLI)
# ---------------------------------------------------------------------------


def test_publish_sync() -> None:
    bus = EventBus()
    received: list[Event] = []
    bus.subscribe("test", lambda e: received.append(e))
    bus.publish("test", {"key": "value"})
    assert len(received) == 1
    assert received[0].topic == "test"
    assert received[0].data == {"key": "value"}


def test_wildcard_subscriber() -> None:
    bus = EventBus()
    received: list[str] = []
    bus.subscribe("", lambda e: received.append(e.topic))
    bus.publish("topic_a", {})
    bus.publish("topic_b", {})
    assert received == ["topic_a", "topic_b"]


def test_no_cross_topic_delivery() -> None:
    bus = EventBus()
    received: list[str] = []
    bus.subscribe("only_a", lambda e: received.append("a"))
    bus.publish("only_b", {})
    assert received == []


def test_multiple_subscribers() -> None:
    bus = EventBus()
    count = {"a": 0, "b": 0}
    bus.subscribe("x", lambda e: count.update(a=count["a"] + 1))
    bus.subscribe("x", lambda e: count.update(b=count["b"] + 1))
    bus.publish("x", {})
    assert count == {"a": 1, "b": 1}


def test_retry_on_failure() -> None:
    bus = EventBus()
    attempts = {"n": 0}

    def flaky_handler(e: Event) -> None:
        attempts["n"] += 1
        if attempts["n"] < 3:
            raise ValueError("transient error")

    bus.subscribe("retry_test", flaky_handler, max_retries=3)
    bus.publish("retry_test", {})
    assert attempts["n"] == 3  # tentou 3x
    assert bus.stats["events_delivered"] == 1  # sucesso na 3ª


def test_dlq_on_max_retries() -> None:
    bus = EventBus()

    def always_fail(e: Event) -> None:
        raise RuntimeError("permanent failure")

    bus.subscribe("fail", always_fail, max_retries=1)
    bus.publish("fail", {})
    assert bus.stats["events_failed"] == 1
    dlq = bus.drain_dlq()
    assert len(dlq) == 1
    assert dlq[0].topic == "fail"


def test_stats() -> None:
    bus = EventBus()
    bus.subscribe("a", lambda e: None)
    bus.publish("a", {})
    bus.publish("a", {})
    stats = bus.stats
    assert stats["events_published"] == 2
    assert stats["events_delivered"] == 2
    assert stats["subscribers"] == 1


def test_subscribe_many() -> None:
    bus = EventBus()
    received: list[str] = []
    bus.subscribe_many(["a", "b", "c"], lambda e: received.append(e.topic))
    bus.publish("a", {})
    bus.publish("b", {})
    bus.publish("c", {})
    bus.publish("d", {})
    assert sorted(received) == ["a", "b", "c"]


def test_get_bus_singleton() -> None:
    import jarvis.core.eventbus as mod
    mod._bus = None
    a = get_bus()
    b = get_bus()
    assert a is b
    mod._bus = None# ---------------------------------------------------------------------------
# Assíncrono (daemon) — usa asyncio.run() para compatibilidade
# ---------------------------------------------------------------------------


def test_publish_async() -> None:
    async def _run() -> None:
        bus = EventBus(max_queue=10)
        received: list[Event] = []
        bus.subscribe("async_test", lambda e: received.append(e))
        await bus.start()
        await bus.publish_async("async_test", {"data": 42})
        await asyncio.sleep(0.2)
        await bus.stop()
        assert len(received) == 1
        assert received[0].data == {"data": 42}
    asyncio.run(_run())


def test_async_wildcard() -> None:
    async def _run() -> None:
        bus = EventBus(max_queue=10)
        received: list[str] = []
        bus.subscribe("", lambda e: received.append(e.topic))
        await bus.start()
        await bus.publish_async("x", {})
        await bus.publish_async("y", {})
        await asyncio.sleep(0.2)
        await bus.stop()
        assert sorted(received) == ["x", "y"]
    asyncio.run(_run())


def test_async_timeout() -> None:
    async def _run() -> None:
        bus = EventBus(max_queue=10)

        async def slow_handler(e: Event) -> None:
            await asyncio.sleep(10)  # muito lento

        bus.subscribe("timeout", slow_handler, max_retries=0, timeout_s=0.1)
        await bus.start()
        await bus.publish_async("timeout", {})
        await asyncio.sleep(0.3)
        await bus.stop()
        assert bus.stats["events_failed"] >= 1
    asyncio.run(_run())


def test_async_resilience() -> None:
    """Subscriber que falha não mata o bus."""
    async def _run() -> None:
        bus = EventBus(max_queue=10)
        results: list[str] = []

        def bad(e: Event) -> None:
            raise RuntimeError("boom")

        def good(e: Event) -> None:
            results.append("ok")

        bus.subscribe("resilience", bad, max_retries=0)
        bus.subscribe("resilience", good, max_retries=0)
        await bus.start()
        await bus.publish_async("resilience", {})
        await asyncio.sleep(0.2)
        await bus.stop()
        assert results == ["ok"]
        assert bus.stats["events_failed"] >= 1
    asyncio.run(_run())


# ---------------------------------------------------------------------------
# MISSÃO 3 (P1) — paratransição: handlers paralelos, ordered preservado
# ---------------------------------------------------------------------------


def test_async_parallel_slow_does_not_block() -> None:
    """Telemetria lenta (2s) NÃO degrada o fluxo principal."""
    async def _run() -> None:
        bus = EventBus(max_queue=100)
        slow_calls: list[float] = []
        fast_calls: list[float] = []

        async def slow_telemetry(e: Event) -> None:
            await asyncio.sleep(2.0)
            slow_calls.append(time.monotonic())

        def fast_main(e: Event) -> None:
            fast_calls.append(time.monotonic())

        bus.subscribe("t", slow_telemetry, max_retries=0, timeout_s=5.0)
        bus.subscribe("t", fast_main, max_retries=0)
        await bus.start()
        t0 = time.monotonic()
        await bus.publish_async("t", {})
        await asyncio.sleep(0.5)
        # fast já rodou (<0.5s) embora slow precise de 2s → paralelo
        assert len(fast_calls) == 1
        assert time.monotonic() - t0 < 1.0
        await asyncio.sleep(2.0)
        await bus.stop()
        assert len(slow_calls) == 1
    asyncio.run(_run())


def test_async_ordered_sequence() -> None:
    """ordered=True preserva sequência em ordem de registro."""
    async def _run() -> None:
        bus = EventBus(max_queue=10)
        order: list[str] = []
        bus.subscribe("o", lambda e: order.append("a"), max_retries=0, ordered=True)
        bus.subscribe("o", lambda e: order.append("b"), max_retries=0, ordered=True)
        await bus.start()
        await bus.publish_async("o", {})
        await asyncio.sleep(0.3)
        await bus.stop()
        assert order == ["a", "b"]
    asyncio.run(_run())


def test_sync_retry_still_works() -> None:
    """Retry síncrono preservado (sem loop: backoff; com loop: sem bloqueio)."""
    bus = EventBus()
    attempts = {"n": 0}

    def flaky(e: Event) -> None:
        attempts["n"] += 1
        if attempts["n"] < 2:
            raise ValueError("transient")

    bus.subscribe("r", flaky, max_retries=2)
    bus.publish("r", {})
    assert attempts["n"] == 2
    assert bus.stats["events_delivered"] == 1
