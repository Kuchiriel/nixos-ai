"""Unit tests for mission-control action endpoints (tasks/services/chat/remote)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import pytest
from fastapi import HTTPException

from jarvis.webui import api as A
import nightwatch.task_queue as tq


@pytest.fixture
def qdir(tmp_path, monkeypatch):
    monkeypatch.setattr(tq, "STATE_DIR", tmp_path)
    return tmp_path


def test_retry_404():
    with pytest.raises(HTTPException) as ei:
        A.task_retry("nope")
    assert ei.value.status_code == 404


def test_cancel_404():
    with pytest.raises(HTTPException) as ei:
        A.task_cancel("nope")
    assert ei.value.status_code == 404


def test_retry_happy(qdir):
    q = tq.TaskQueue(project="t")
    t = tq.Task(id="r1", project="t", description="x", target_files=[],
                repository=str(qdir))
    q._tasks.append(t)
    t.fail("boom"); t.fail("boom"); t.fail("boom")
    assert t.status == "FAILED"
    q._save()
    r = A.task_retry("r1")
    assert r["status"] == "READY"
    assert tq.TaskQueue(project="t").get_task("r1").attempts == 0


def test_retry_refuses_active(qdir):
    q = tq.TaskQueue(project="t")
    t = tq.Task(id="r2", project="t", description="x", target_files=[],
                repository=str(qdir), status="READY")
    q._tasks.append(t)
    q._save()
    with pytest.raises(HTTPException) as ei:
        A.task_retry("r2")
    assert ei.value.status_code == 409


def test_cancel_happy(qdir):
    q = tq.TaskQueue(project="t")
    t = tq.Task(id="c1", project="t", description="x", target_files=[],
                repository=str(qdir), status="READY")
    q._tasks.append(t)
    q._save()
    r = A.task_cancel("c1")
    assert r["status"] == "ABANDONED"


def test_service_invalid_action():
    with pytest.raises(HTTPException) as ei:
        A.service_action("x", "explode")
    assert ei.value.status_code == 400


def test_service_allowlist():
    r = A.service_action("nonexistent-svc", "restart")
    assert r["success"] is False


def test_chat_empty():
    with pytest.raises(HTTPException) as ei:
        A.chat(A.ChatRequest(message="  "))
    assert ei.value.status_code == 400


def test_remote_shape():
    r = A.remote_status()
    assert set(r) == {"env_file", "providers", "cascade"}
    assert r["cascade"][0] == "local"
