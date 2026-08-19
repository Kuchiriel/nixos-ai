"""Testes do modo idle (core/idle.py) — detecção, fila e worker."""

from __future__ import annotations

import time

from jarvis.core.config import Config
from jarvis.core.idle import IdleTask, IdleWorker, is_idle, load_is_low, user_is_idle


def _cfg(tmp_path) -> Config:
    return Config(state_dir=tmp_path / "state")


def _tasks(interval_min: int = 60) -> list[IdleTask]:
    runs = []

    def _run():
        runs.append("t1")
        return {"ok": True}

    return [IdleTask("t1", _run, interval_min)], runs


def _write_hb(worker: IdleWorker, name: str, ts: float) -> None:
    worker.state_dir.mkdir(parents=True, exist_ok=True)
    worker._heartbeat(name).write_text('{"last": %r}' % ts, encoding="utf-8")


# ---------------------------------------------------------------------------
# Detecção de idle
# ---------------------------------------------------------------------------

def test_load_is_low(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.core.idle.os.getloadavg", lambda: (1.0, 1.0, 1.0))
    assert load_is_low(max_load=2.0) is True
    monkeypatch.setattr("jarvis.core.idle.os.getloadavg", lambda: (3.5, 3.0, 2.5))
    assert load_is_low(max_load=2.0) is False


def test_user_is_idle_parses_loginctl(monkeypatch) -> None:
    class FakeRun:
        def __init__(self, out: str):
            self._out = out

        @property
        def stdout(self) -> str:
            return self._out

    def fake_run(cmd, **kw):
        assert cmd[0] == "loginctl"
        return FakeRun("IdleHint=yes\n")

    monkeypatch.setattr("jarvis.core.idle.subprocess.run", fake_run)
    assert user_is_idle(user="nixos") is True


def test_user_is_idle_timeout_returns_none(monkeypatch) -> None:
    def boom(cmd, **kw):
        raise __import__("subprocess").TimeoutExpired("loginctl", 3.0)

    monkeypatch.setattr("jarvis.core.idle.subprocess.run", boom)
    assert user_is_idle(user="nixos") is None


def test_is_idle_gates(tmp_path, monkeypatch) -> None:
    # carga alta → nunca idle
    monkeypatch.setattr("jarvis.core.idle.os.getloadavg", lambda: (5.0, 5.0, 5.0))
    monkeypatch.setattr("jarvis.core.idle.user_is_idle", lambda **k: True)
    assert is_idle() is False

    # carga baixa + usuário ocupado → não idle
    monkeypatch.setattr("jarvis.core.idle.os.getloadavg", lambda: (0.5, 0.5, 0.5))
    monkeypatch.setattr("jarvis.core.idle.user_is_idle", lambda **k: False)
    assert is_idle() is False

    # carga baixa + logind desconhecido → idle (decide pela carga)
    monkeypatch.setattr("jarvis.core.idle.user_is_idle", lambda **k: None)
    assert is_idle() is True

    # idle_check desligado → só carga importa
    monkeypatch.setattr("jarvis.core.idle.user_is_idle", lambda **k: False)
    assert is_idle(idle_check=False) is True


# ---------------------------------------------------------------------------
# Fila e worker
# ---------------------------------------------------------------------------

def test_due_tasks_respects_interval(tmp_path) -> None:
    worker = IdleWorker(_cfg(tmp_path), tasks=_tasks(interval_min=60)[0])
    # nunca rodou → tudo devido
    assert [t.name for t in worker.due_tasks()] == ["t1"]
    # heartbeat recente → não devido
    _write_hb(worker, "t1", time.time())
    assert worker.due_tasks() == []


def test_run_once_skips_when_busy(tmp_path, monkeypatch) -> None:
    tasks, runs = _tasks()
    worker = IdleWorker(_cfg(tmp_path), tasks=tasks)
    monkeypatch.setattr("jarvis.core.idle.is_idle", lambda **k: False)
    result = worker.run_once()
    assert result == {"ran": False, "reason": "sistema ocupado"}
    assert runs == []


def test_run_once_nothing_due(tmp_path, monkeypatch) -> None:
    tasks, _ = _tasks()
    worker = IdleWorker(_cfg(tmp_path), tasks=tasks)
    _write_hb(worker, "t1", time.time())
    monkeypatch.setattr("jarvis.core.idle.is_idle", lambda **k: True)
    result = worker.run_once()
    assert result == {"ran": False, "reason": "nada devido"}


def test_run_once_executes_due_task(tmp_path, monkeypatch) -> None:
    tasks, runs = _tasks()
    worker = IdleWorker(_cfg(tmp_path), tasks=tasks)
    monkeypatch.setattr("jarvis.core.idle.is_idle", lambda **k: True)
    result = worker.run_once()
    assert result["ran"] is True
    assert result["task"] == "t1"
    assert runs == ["t1"]
    # heartbeat gravado
    hb = worker._heartbeat("t1")
    assert hb.exists()
    import json
    assert json.loads(hb.read_text(encoding="utf-8"))["result"]["ok"] is True


def test_run_once_picks_most_overdue(tmp_path, monkeypatch) -> None:
    runs = []

    def mk(name: str, last: float):
        def _run():
            runs.append(name)
            return {"ok": True}

        return IdleTask(name, _run, 60), last

    # ambos devidos (intervalo 60min): um rodou há 70min, outro há 120min
    specs = [mk("novo", time.time() - 70 * 60), mk("velho", time.time() - 120 * 60)]
    tasks = [s[0] for s in specs]
    worker = IdleWorker(_cfg(tmp_path), tasks=tasks)
    for task, last in specs:
        _write_hb(worker, task.name, last)
    monkeypatch.setattr("jarvis.core.idle.is_idle", lambda **k: True)
    result = worker.run_once()
    assert result["task"] == "velho"  # o mais atrasado primeiro
    # (uma tarefa que nunca rodou tem last=0 → é a mais atrasada de todas)
    _write_hb(worker, "velho", 0.0)
    _write_hb(worker, "novo", time.time() - 70 * 60)
    assert worker.run_once()["task"] == "velho"


def test_run_once_force_ignores_idle(tmp_path, monkeypatch) -> None:
    tasks, runs = _tasks()
    worker = IdleWorker(_cfg(tmp_path), tasks=tasks)
    monkeypatch.setattr("jarvis.core.idle.is_idle", lambda **k: False)
    result = worker.run_once(force="t1")
    assert result["ran"] is True
    assert runs == ["t1"]


def test_run_once_force_unknown_task(tmp_path) -> None:
    worker = IdleWorker(_cfg(tmp_path), tasks=_tasks()[0])
    result = worker.run_once(force="nao-existe")
    assert result == {"ran": False, "reason": "tarefa desconhecida: nao-existe"}


def test_run_once_never_crashes_on_task_error(tmp_path, monkeypatch) -> None:
    def _boom():
        raise RuntimeError("estourou")

    worker = IdleWorker(_cfg(tmp_path), tasks=[IdleTask("boom", _boom, 60)])
    monkeypatch.setattr("jarvis.core.idle.is_idle", lambda **k: True)
    result = worker.run_once()
    assert result["ran"] is True
    assert result["result"]["exit"] == -1
    assert "estourou" in result["result"]["error"]
