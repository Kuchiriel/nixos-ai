"""Event Bus local — barramento de eventos assíncrono leve para o JARVIS.

Conecta subsistemas via filas asyncio (sem Redis/Kafka/dependências externas):
  - Wakeword → STT → FastPath/Agent → TTS / Telegram
  - Doctor → Self-heal → Logger
  - Triggers → Telegram alerts

Resiliência:
  - Cada subscriber é uma task asyncio isolada (falha não mata o bus)
  - Dead letter queue (DLQ) para eventos não processados
  - Timeouts configuráveis por subscriber
  - Retry com backoff linear (max 3 tentativas)

Uso síncrono (CLI): o módulo fornece `EventBus` síncrono que internamente
usa `asyncio.Queue` — funciona tanto em scripts quanto em daemons.

Zero dependências externas.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Awaitable


@dataclass
class Event:
    """Evento no barramento."""
    topic: str
    data: dict[str, Any] = field(default_factory=dict)
    ts: float = field(default_factory=time.time)
    source: str = ""
    retries: int = 0


# Tipo do handler: recebe um Event, retorna None (sync) ou awaitable
EventHandler = Callable[[Event], Any]


@dataclass
class Subscriber:
    """Um subscriber registrado no bus."""
    name: str
    handler: EventHandler
    topics: list[str]  # [] = recebe todos
    max_retries: int = 3
    timeout_s: float = 30.0


@dataclass
class BusStats:
    """Métricas do bus."""
    events_published: int = 0
    events_delivered: int = 0
    events_failed: int = 0
    dlq_size: int = 0


class EventBus:
    """Barramento de eventos asyncio leve.

    Exemplo síncrono (CLI):
        bus = EventBus()
        bus.subscribe("wake", my_handler)
        bus.publish("wake", {"audio": "/tmp/capture.wav"})

    Exemplo assíncrono (daemon):
        await bus.start()
        await bus.publish_async("wake", {"audio": "/tmp/capture.wav"})
        await bus.stop()
    """

    def __init__(self, max_queue: int = 1000) -> None:
        self._subscribers: dict[str, list[Subscriber]] = {}
        self._queue: asyncio.Queue[Event | None] | None = None
        self._dlq: list[Event] = []
        self._stats = BusStats()
        self._tasks: list[asyncio.Task[None]] = []
        self._running = False
        self._max_queue = max_queue

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "events_published": self._stats.events_published,
            "events_delivered": self._stats.events_delivered,
            "events_failed": self._stats.events_failed,
            "dlq_size": len(self._dlq),
            "subscribers": sum(len(v) for v in self._subscribers.values()),
        }

    # --- registro ---

    def subscribe(
        self,
        topic: str,
        handler: EventHandler,
        *,
        name: str = "",
        max_retries: int = 3,
        timeout_s: float = 30.0,
    ) -> None:
        """Registra um handler para um tópico. topic="" = todos os tópicos."""
        sub = Subscriber(
            name=name or handler.__name__,
            handler=handler,
            topics=[topic] if topic else [],
            max_retries=max_retries,
            timeout_s=timeout_s,
        )
        self._subscribers.setdefault(topic or "__all__", []).append(sub)

    def subscribe_many(self, topics: list[str], handler: EventHandler, **kw: Any) -> None:
        """Registra um handler para múltiplos tópicos."""
        for t in topics:
            self.subscribe(t, handler, **kw)

    # --- publicação síncrona (CLI) ---

    def publish(self, topic: str, data: dict[str, Any] | None = None, source: str = "") -> None:
        """Publica um evento (síncrono — para uso em CLI/scripts).

        Executa handlers inline (sem async). Adequado para CLI e testes.
        """
        event = Event(topic=topic, data=data or {}, source=source)
        self._stats.events_published += 1
        self._dispatch_sync(event)

    def _dispatch_sync(self, event: Event) -> None:
        """Dispatch síncrono — roda handlers diretamente (CLI/testes)."""
        targets = self._matching_subscribers(event.topic)
        for sub in targets:
            for attempt in range(sub.max_retries + 1):
                try:
                    sub.handler(event)
                    self._stats.events_delivered += 1
                    break
                except Exception:  # noqa: BLE001
                    if attempt == sub.max_retries:
                        self._stats.events_failed += 1
                        self._dlq.append(event)
                        break
                    time.sleep(0.1 * (attempt + 1))

    def _matching_subscribers(self, topic: str) -> list[Subscriber]:
        """Retorna subscribers que aceitam este tópico."""
        result: list[Subscriber] = []
        # Tópico específico
        if topic in self._subscribers:
            result.extend(self._subscribers[topic])
        # Wildcard (__all__)
        if "__all__" in self._subscribers:
            result.extend(self._subscribers["__all__"])
        return result

    # --- publicação assíncrona (daemon) ---

    async def start(self) -> None:
        """Inicia o loop de processamento do bus."""
        if self._running:
            return
        self._queue = asyncio.Queue(maxsize=self._max_queue)
        self._running = True
        self._tasks = [asyncio.create_task(self._process_loop())]

    async def stop(self) -> None:
        """Para o loop e aguarda as tasks."""
        self._running = False
        if self._queue:
            await self._queue.put(None)  # sentinel
        for t in self._tasks:
            try:
                await asyncio.wait_for(t, timeout=5.0)
            except (asyncio.TimeoutError, asyncio.CancelledError):
                t.cancel()
        self._tasks.clear()

    async def publish_async(self, topic: str, data: dict[str, Any] | None = None, source: str = "") -> None:
        """Publica um evento de forma assíncrona."""
        if self._queue is None:
            self.publish(topic, data, source)
            return
        event = Event(topic=topic, data=data or {}, source=source)
        self._stats.events_published += 1
        try:
            self._queue.put_nowait(event)
        except asyncio.QueueFull:
            self._stats.events_failed += 1
            self._dlq.append(event)

    async def _process_loop(self) -> None:
        """Loop principal: consome eventos e distribui para subscribers."""
        assert self._queue is not None
        while self._running:
            try:
                event = await asyncio.wait_for(self._queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if event is None:  # sentinel de shutdown
                break
            await self._dispatch_async(event)

    async def _dispatch_async(self, event: Event) -> None:
        """Dispatch assíncrono — roda handlers em tasks isoladas."""
        targets = self._matching_subscribers(event.topic)
        for sub in targets:
            for attempt in range(sub.max_retries + 1):
                try:
                    result = sub.handler(event)
                    if asyncio.iscoroutine(result):
                        await asyncio.wait_for(result, timeout=sub.timeout_s)
                    self._stats.events_delivered += 1
                    break
                except asyncio.TimeoutError:
                    event.retries = attempt + 1
                    if attempt == sub.max_retries:
                        self._stats.events_failed += 1
                        self._dlq.append(event)
                        break
                except Exception:  # noqa: BLE001
                    event.retries = attempt + 1
                    if attempt == sub.max_retries:
                        self._stats.events_failed += 1
                        self._dlq.append(event)
                        break
                    await asyncio.sleep(0.1 * (attempt + 1))

    # --- DLQ ---

    def drain_dlq(self) -> list[Event]:
        """Retorna e limpa a dead letter queue."""
        events = list(self._dlq)
        self._dlq.clear()
        return events


# ---------------------------------------------------------------------------
# Instância global (singleton)
# ---------------------------------------------------------------------------

_bus: EventBus | None = None


def get_bus() -> EventBus:
    """Retorna (ou cria) a instância global do bus."""
    global _bus
    if _bus is None:
        _bus = EventBus()
    return _bus
