"""Tests para jarvis.core.queue — fila de mensagens leve."""

import json
import time

import pytest

from jarvis.core.queue import Queue


@pytest.fixture
def q(tmp_path):
    """Queue isolada por teste."""
    return Queue("test", base_dir=tmp_path, ttl_seconds=10.0)


class TestQueuePut:
    def test_put_returns_id(self, q):
        item_id = q.put({"prompt": "hello"})
        assert isinstance(item_id, str)
        assert len(item_id) == 12

    def test_put_persists(self, q):
        q.put({"prompt": "test"})
        items = q._read()
        assert len(items) == 1
        assert items[0]["payload"]["prompt"] == "test"
        assert items[0]["status"] == "pending"

    def test_put_with_priority(self, q):
        q.put({"p": "low"}, priority=0)
        q.put({"p": "high"}, priority=10)
        items = q._read()
        assert items[0]["payload"]["p"] == "high"
        assert items[1]["payload"]["p"] == "low"


class TestQueueGet:
    def test_get_returns_pending(self, q):
        q.put({"p": 1})
        item = q.get()
        assert item is not None
        assert item["payload"]["p"] == 1
        assert item["status"] == "processing"

    def test_get_returns_none_when_empty(self, q):
        assert q.get() is None

    def test_get_skips_expired(self, q):
        q.put({"p": 1}, ttl=0.01)
        time.sleep(0.02)
        assert q.get() is None

    def test_get_fifo_by_priority(self, q):
        q.put({"p": "low"}, priority=0)
        q.put({"p": "high"}, priority=10)
        q.put({"p": "mid"}, priority=5)
        assert q.get()["payload"]["p"] == "high"
        assert q.get()["payload"]["p"] == "mid"
        assert q.get()["payload"]["p"] == "low"


class TestQueueDone:
    def test_done_removes_item(self, q):
        item_id = q.put({"p": 1})
        q.get()
        assert q.done(item_id) is True
        assert q.peek() == []

    def test_done_unknown_id(self, q):
        assert q.done("nonexistent") is False


class TestQueueFail:
    def test_fail_marks_failed(self, q):
        item_id = q.put({"p": 1})
        q.get()
        assert q.fail(item_id, error="boom") is True
        items = q._read()
        assert items[0]["status"] == "failed"
        assert items[0]["error"] == "boom"


class TestQueuePurge:
    def test_purge_removes_expired(self, q):
        q.put({"p": 1}, ttl=0.01)
        q.put({"p": 2}, ttl=60)
        time.sleep(0.02)
        removed = q.purge()
        assert removed == 1
        assert len(q.peek()) == 1


class TestQueueStats:
    def test_stats(self, q):
        q.put({"p": 1}, ttl=0.01)
        q.put({"p": 2})
        q.put({"p": 3})
        time.sleep(0.02)  # item 1 expira
        q.get()  # pega item 2 (item 1 expirado, skipped)
        stats = q.stats()
        assert stats["pending"] == 1  # item 3
        assert stats["processing"] == 1  # item 2
        assert stats["expired"] == 1  # item 1


class TestQueueLen:
    def test_len(self, q):
        assert len(q) == 0
        q.put({"p": 1})
        assert len(q) == 1
        q.put({"p": 2})
        assert len(q) == 2
