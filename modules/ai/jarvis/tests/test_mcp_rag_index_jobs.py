"""rag_index jobs — retorno imediato, status consultavel, persistencia (12/11).

MOTIVO: indexar uma arvore grande dentro da chamada MCP estourava o timeout do
cliente. O handler ganhou `background`/`async` (fire-and-forget) e um estado de
job; sem teste, uma regressao volta a bloquear a sessao sem ninguem notar.

Estes testes usam stubs (sem Qdrant/embeddings) e provam:
  * background retorna imediatamente com job_id e status running;
  * o job termina em done com o resultado e fica consultavel;
  * o estado sobrevive a um "restart" (recarga do JSON de jobs);
  * job desconhecido devolve erro estruturado;
  * job running antigo e marcado `stale` (nao fica "rodando" para sempre).
"""

from __future__ import annotations

import json
import time
import types

import pytest

try:
    from jarvis import mcp_server as m
except Exception as exc:  # pragma: no cover - sandbox sem deps do core
    pytest.skip(f"jarvis.mcp_server indisponivel: {exc}", allow_module_level=True)


class _FakeIndexer:
    skipped: list = []

    def __init__(self) -> None:
        self.skipped = [("a.md", "unchanged")]

    def index_directory(self, path, force=False, deadline_s=None):
        return 2


@pytest.fixture()
def handler(tmp_path, monkeypatch):
    """Handler com estado limpo, stubs e arquivo de jobs em tmp."""
    monkeypatch.setenv("JARVIS_RAG_INDEX_JOBS_PATH", str(tmp_path / "jobs.json"))
    monkeypatch.setattr(m, "_RAG_INDEX_JOBS", {})
    monkeypatch.setattr(m, "_RAG_INDEX_JOBS_LOADED", False)

    rag = types.ModuleType("jarvis.core.rag")
    rag.HybridIndexer = _FakeIndexer
    monkeypatch.setitem(__import__("sys").modules, "jarvis.core.rag", rag)

    audiobook = types.ModuleType("jarvis.core.audiobook")
    audiobook.sweep_books = lambda: {"new": [], "pending": []}
    monkeypatch.setitem(__import__("sys").modules, "jarvis.core.audiobook", audiobook)
    return m


def _wait(handler, job_id, timeout=5.0):
    deadline = time.time() + timeout
    while time.time() < deadline:
        state = json.loads(handler._handle_rag_index_status({"job_id": job_id}))
        if state.get("status") != "running":
            return state
        time.sleep(0.02)
    return json.loads(handler._handle_rag_index_status({"job_id": job_id}))


def test_background_returns_immediately_and_completes(handler):
    started = time.time()
    out = json.loads(handler._handle_rag_index({"path": "/tmp/x", "background": True}))
    assert time.time() - started < 2.0, "background bloqueou a chamada"
    assert out["status"] == "running"
    job_id = out["job_id"]

    state = _wait(handler, job_id)
    assert state["status"] == "done", state
    assert "Indexed 2 files" in state["result"]
    assert state["finished_at"] and state["finished_at"] >= state["started_at"]


def test_async_alias_also_tracks_job(handler):
    out = json.loads(handler._handle_rag_index({"path": "/tmp/y", "async": True}))
    assert out["status"] == "running"
    assert _wait(handler, out["job_id"])["status"] == "done"


def test_job_state_survives_reload(handler, tmp_path):
    out = json.loads(handler._handle_rag_index({"path": "/tmp/z", "background": True}))
    job_id = out["job_id"]
    _wait(handler, job_id)

    # simula restart do servidor: estado em memoria zerado, arquivo permanece
    handler._RAG_INDEX_JOBS = {}
    handler._RAG_INDEX_JOBS_LOADED = False

    state = json.loads(handler._handle_rag_index_status({"job_id": job_id}))
    assert state["job_id"] == job_id
    assert state["status"] == "done"
    saved = json.loads((tmp_path / "jobs.json").read_text())
    assert saved["version"] == 1
    assert [j["job_id"] for j in saved["jobs"]] == [job_id]


def test_sync_index_also_creates_a_job(handler):
    msg = handler._handle_rag_index({"path": "/tmp/sync"})
    assert "Indexed 2 files" in msg
    jobs = json.loads(handler._handle_rag_index_status({"limit": 5}))
    assert len(jobs) == 1
    assert jobs[0]["status"] == "done"
    assert jobs[0]["background"] is False


def test_unknown_job_id_is_structured_error(handler):
    out = json.loads(handler._handle_rag_index_status({"job_id": "ragidx-nao-existe"}))
    assert "error" in out and "unknown job_id" in out["error"]


def test_status_reachable_through_meta_tool(handler):
    out = json.loads(handler._handle_rag_index({"path": "/tmp/meta", "background": True}))
    _wait(handler, out["job_id"])
    text = handler.call_tool("tools_call", {"name": "rag_index_status", "args": {"job_id": out["job_id"]}})
    assert json.loads(text)["status"] == "done"


def test_old_running_job_is_marked_stale(handler):
    handler._RAG_INDEX_JOBS["ragidx-old"] = {
        "job_id": "ragidx-old",
        "path": "/tmp/old",
        "background": True,
        "force": False,
        "deadline_s": None,
        "status": "running",
        "started_at": time.time() - 7200,
        "finished_at": None,
        "result": None,
        "error": None,
    }
    state = json.loads(handler._handle_rag_index_status({"job_id": "ragidx-old"}))
    assert state["status"] == "running"
    assert state.get("stale") is True


def test_job_failure_is_recorded_as_error(handler, monkeypatch):
    class _Boom(_FakeIndexer):
        def index_directory(self, path, force=False, deadline_s=None):
            raise RuntimeError("qdrant offline")

    rag = __import__("sys").modules["jarvis.core.rag"]
    monkeypatch.setattr(rag, "HybridIndexer", _Boom)

    out = json.loads(handler._handle_rag_index({"path": "/tmp/boom", "background": True}))
    state = _wait(handler, out["job_id"])
    assert state["status"] == "error"
    assert "qdrant offline" in state["error"]
