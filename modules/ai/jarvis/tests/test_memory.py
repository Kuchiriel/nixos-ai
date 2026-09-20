"""Testes da memória episódica (core/memory.py) com mocks."""
import pytest
pytestmark = pytest.mark.integration

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
        self.deleted_ids = []

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

    def _request(self, method, path, json=None):
        if "scroll" in path:
            flt = (json or {}).get("filter", {}).get("must", [])
            kinds = [c["match"]["value"] for c in flt
                     if c.get("key") == "kind"]
            pts = [{"id": p["id"], "payload": p["payload"]}
                   for p in self.points
                   if not kinds or p["payload"].get("kind") in kinds]
            lim = (json or {}).get("limit", 20)
            return {"result": {"points": pts[:lim]}}
        raise AssertionError("unexpected " + path)

    def delete_points(self, name, ids):
        self.deleted_ids.extend(ids)
        self.points = [p for p in self.points if p["id"] not in ids]


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

        def post(self, url, json=None, timeout=120, **kw):
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


def test_lessons_includes_facts_and_errors(monkeypatch) -> None:
    """lessons() injeta facts/errors além de lessons (L8: v41 + quoting
    facts no store mas invisíveis ao filtro lesson-only — 41 falhas com a
    cura guardada). Decisions continuam fora."""
    from jarvis.core.memory import MemoryEvent
    mem, _, _ = _mem(monkeypatch)
    mem.remember(MemoryEvent(kind=KIND_LESSON, text="Task: t. Error: e. Fix: f",
                             task="t", error_pattern="e", fix="f"))
    mem.remember_fact("bonsai: JSON com aspas simples quebra; usar jq -n")
    mem.remember(MemoryEvent(kind="decision", text="usar jq sempre"))
    out = mem.lessons("shell json quoting fix")
    assert "STATE(lesson): task='t'" in out
    assert "jq -n" in out
    assert "usar jq sempre" not in out


def test_lessons_empty_without_hits(monkeypatch) -> None:
    """Store vazio → string vazia (sem injeção fantasma)."""
    mem, _, _ = _mem(monkeypatch)
    assert mem.lessons("qualquer coisa") == ""


def test_lessons_fact_carries_age(monkeypatch) -> None:
    """Fact velho anota idade (freshness visível; fato de setembro ≠ hoje).
    Sem ts → sem marcador."""
    import time
    from jarvis.core.memory import MemoryEvent
    mem, _, _ = _mem(monkeypatch)
    mem.remember(MemoryEvent(
        kind="fact", text="dado antigo relevante",
        timestamp=time.time() - 10 * 86400))
    mem.remember(MemoryEvent(kind="fact", text="dado novo relevante"))
    out = mem.lessons("dado relevante")
    assert "[10d ago] dado antigo relevante" in out
    assert "STATE(known-fact): dado novo relevante" in out


def test_lesson_supersedes_same_task(monkeypatch) -> None:
    """Segunda lesson mesma task aposenta a anterior (freshness: sem isso
    '0/3' convive com '0/47' e ambos injetam)."""
    mem, store, _ = _mem(monkeypatch)
    mem.remember_lesson(task="Shell JSON", error_pattern="e1", fix="old")
    assert len(store.points) == 1
    mem.remember_lesson(task="shell  json", error_pattern="e2", fix="new")
    assert len(store.points) == 1
    assert len(store.deleted_ids) == 1
    assert store.points[0]["payload"]["fix"] == "new"


def test_lesson_keeps_different_task(monkeypatch) -> None:
    """Tasks distintas convivem (supersede só no match normalizado)."""
    mem, store, _ = _mem(monkeypatch)
    mem.remember_lesson(task="Alpha", error_pattern="e", fix="f1")
    mem.remember_lesson(task="Beta", error_pattern="e", fix="f2")
    assert len(store.points) == 2
    assert store.deleted_ids == []
