"""Testes da memória episódica (core/memory.py) com mocks."""

import time

from jarvis.core.memory import (
    KIND_LESSON,
    EpisodicMemory,
    MemoryEvent,
    _stable_id,
)
from jarvis.core.config import Config


class FakeStore:
    def __init__(self):
        self.points = []
        self.created = []
        self.deleted = []

    def is_available(self):
        return True

    def ensure_collection(self, name, dim=768):
        self.created.append(name)

    def delete_collection(self, name):
        self.deleted.append(name)

    def upsert(self, name, points):
        self.points.extend(points)

    def search_hybrid(self, name, dense, sparse, top_k=10, **kw):
        # retorna os pontos em ordem (score fake desc)
        hits = []
        for i, p in enumerate(self.points):
            hits.append({"id": p["id"], "score": 1.0 - i * 0.01, "payload": p["payload"]})
        return hits[:top_k]

    def count(self, name):
        return len(self.points)


class FakeLLM:
    def __init__(self):
        self.embedded = []

    def embed(self, text):
        self.embedded.append(text)
        return [0.1] * 4  # vetor fake


def _mem(monkeypatch):
    cfg = Config()
    mem = EpisodicMemory(cfg)
    store = FakeStore()
    llm = FakeLLM()
    monkeypatch.setattr(mem, "_store", store)
    monkeypatch.setattr(mem, "_llm", llm)
    return mem, store, llm


def test_remember_stores_payload(monkeypatch) -> None:
    mem, store, _ = _mem(monkeypatch)
    event = MemoryEvent(kind=KIND_LESSON, text="Task: x. Error: y. Fix: z",
                        task="x", error_pattern="y", fix="z")
    pid = mem.remember(event)
    assert pid is not None
    assert len(store.points) == 1
    point = store.points[0]
    assert point["id"] == pid
    assert point["vector"]["dense"] == [0.1] * 4
    assert "bm25" in point["vector"]
    assert point["payload"]["kind"] == "lesson"
    assert point["payload"]["fix"] == "z"


def test_remember_lesson_porta_experience_buffer(monkeypatch) -> None:
    mem, store, _ = _mem(monkeypatch)
    pid = mem.remember_lesson(task="fix build", error_pattern="undefined ref", fix="add -l")
    assert pid is not None
    assert store.points[0]["payload"]["kind"] == "lesson"
    assert store.points[0]["payload"]["task"] == "fix build"


def test_remember_empty_text(monkeypatch) -> None:
    mem, _, _ = _mem(monkeypatch)
    assert mem.remember(MemoryEvent(kind="fact", text="   ")) is None


def test_recall_filters_kinds(monkeypatch) -> None:
    mem, store, _ = _mem(monkeypatch)
    mem.remember(MemoryEvent(kind="fact", text="prefiro voz grave"))
    mem.remember(MemoryEvent(kind=KIND_LESSON, text="erro no build",
                             task="build", error_pattern="e", fix="f"))
    hits = mem.recall("algo", kinds=("lesson",))
    assert len(hits) == 1
    assert hits[0]["kind"] == "lesson"


def test_lessons_formats_like_legacy(monkeypatch) -> None:
    mem, _, _ = _mem(monkeypatch)
    mem.remember(MemoryEvent(kind=KIND_LESSON, text="Task: build. Error: e1. Fix: f1",
                             task="build", error_pattern="e1", fix="f1"))
    out = mem.lessons("build")
    assert "PAST LESSONS" in out
    assert "f1" in out
    assert "e1" in out


def test_lessons_empty(monkeypatch) -> None:
    mem, _, _ = _mem(monkeypatch)
    assert mem.lessons("nada") == ""


def test_agent_learns_on_failure(tmp_path, monkeypatch) -> None:
    """O agente grava lição quando um comando falha (auto-aprendizado)."""
    import json as jsonlib

    from jarvis.core.agent import Agent

    mem, store, _ = _mem(monkeypatch)

    class FailThenAnswer:
        calls = 0

        def _resp(self, payload):
            return type("R", (), {
                "json": lambda self: payload,
                "raise_for_status": lambda self: None,
            })()

        def get(self, url, timeout=5):
            return self._resp({"data": [{"id": "m"}]})

        def post(self, url, json=None, timeout=120):
            self.calls += 1
            if self.calls == 1:
                msg = {"role": "assistant", "content": "", "tool_calls": [{
                    "id": "c1", "type": "function",
                    "function": {"name": "execute_shell",
                                 "arguments": jsonlib.dumps({"cmd": "ls /nope-xyz"})},
                }]}
            else:
                msg = {"role": "assistant", "content": "final"}
            return self._resp({"choices": [{"message": msg}]})

    agent = Agent(Config(), session=FailThenAnswer(), memory=mem)
    result = agent.run("check")
    assert "ls /nope-xyz" in result.commands_run
    # uma lição foi gravada com o erro real
    assert len(store.points) == 1
    assert store.points[0]["payload"]["kind"] == "lesson"


def test_stable_id_deterministic() -> None:
    ts = 1700000000.0
    assert _stable_id("texto", ts) == _stable_id("texto", ts)
    assert _stable_id("texto", ts) != _stable_id("outro", ts)
