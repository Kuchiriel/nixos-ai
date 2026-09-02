"""P3 validation: Task.fail()/.complete() persist immediately, atomically,
surviving a simulated crash between the call and TaskQueue._save().

Not testing that fail() sets self.status — that's trivial. Testing that
the state is on DISK after fail() returns, read fresh (new process
simulation: reload from the file, not from the live object).
"""
from __future__ import annotations

import json

import nightwatch.task_queue as tq_mod
from nightwatch.task_queue import Task, TaskStatus


def test_fail_persists_to_disk_before_returning(tmp_path, monkeypatch):
    queue_file = tmp_path / "task_queue.json"
    monkeypatch.setattr(tq_mod, "TASK_QUEUE_FILE", queue_file)

    task = Task(id="t1", project="p", description="d", priority="medium", risk="low")
    task.fail("simulated tool crash")

    assert queue_file.exists(), "fail() retornou mas nada foi escrito em disco"
    on_disk = json.loads(queue_file.read_text())
    persisted = next(t for t in on_disk if t["id"] == "t1")
    assert persisted["status"] == task.status
    assert persisted["last_error"] == "simulated tool crash"
    assert persisted["attempts"] == 1


def test_fail_write_is_atomic_no_tmp_left_behind(tmp_path, monkeypatch):
    queue_file = tmp_path / "task_queue.json"
    monkeypatch.setattr(tq_mod, "TASK_QUEUE_FILE", queue_file)

    task = Task(id="t2", project="p", description="d", priority="medium", risk="low")
    task.fail("err")

    tmp_file = queue_file.with_suffix(".tmp")
    assert not tmp_file.exists(), (
        "arquivo .tmp sobrou — rename() nao aconteceu, escrita nao terminou"
    )


def test_process_restart_reads_the_failed_state_not_stale(tmp_path, monkeypatch):
    """Simula: processo A chama fail() e morre. Processo B (nova instancia
    Task, simulando reload apos restart) le do disco."""
    queue_file = tmp_path / "task_queue.json"
    monkeypatch.setattr(tq_mod, "TASK_QUEUE_FILE", queue_file)

    task_a = Task(id="t3", project="p", description="d", priority="medium", risk="low",
                  max_attempts=3)
    task_a.fail("boom")
    # "processo A morre" aqui — nenhuma outra escrita acontece

    on_disk = json.loads(queue_file.read_text())
    reloaded = next(t for t in on_disk if t["id"] == "t3")
    assert reloaded["status"] == TaskStatus.READY.value  # attempts=1 < max_attempts=3
    assert reloaded["attempts"] == 1

    task_b = Task(**{k: v for k, v in reloaded.items() if k in Task.__dataclass_fields__})
    task_b.fail("boom again")
    on_disk_2 = json.loads(queue_file.read_text())
    reloaded_2 = next(t for t in on_disk_2 if t["id"] == "t3")
    assert reloaded_2["attempts"] == 2
