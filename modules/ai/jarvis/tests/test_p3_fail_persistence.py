"""P3 validation: Task.fail()/_persist_now() persiste imediatamente e de
forma atômica, sobrevivendo a crash simulado entre a chamada e qualquer
save posterior.

Nota: _persist_now() usa _task_queue_file(task.project) (namespaced por
projeto desde que P6 foi resolvido), não o TASK_QUEUE_FILE global.
Os testes monkeypatcam STATE_DIR pra isolar o IO sem depender de nenhum
estado real do disco.
"""
from __future__ import annotations

import json

import pytest

import nightwatch.task_queue as tq_mod
from nightwatch.task_queue import Task, TaskStatus


@pytest.fixture(autouse=True)
def isolated_state_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(tq_mod, "STATE_DIR", tmp_path)


def test_fail_persists_to_disk_before_returning(tmp_path):
    task = Task(id="t1", project="test-proj", description="d", priority="medium", risk="low")
    task.fail("simulated tool crash")

    queue_file = tq_mod._task_queue_file("test-proj")
    assert queue_file.exists(), "fail() retornou mas nada foi escrito em disco"
    on_disk = json.loads(queue_file.read_text())
    persisted = next(t for t in on_disk if t["id"] == "t1")
    assert persisted["last_error"] == "simulated tool crash"
    assert persisted["attempts"] == 1


def test_fail_write_is_atomic_no_tmp_left_behind(tmp_path):
    task = Task(id="t2", project="test-proj", description="d", priority="medium", risk="low")
    task.fail("err")

    queue_file = tq_mod._task_queue_file("test-proj")
    tmp_file = queue_file.with_suffix(".tmp")
    assert not tmp_file.exists(), (
        "arquivo .tmp sobrou — rename() não aconteceu, escrita não terminou atomicamente"
    )


def test_process_restart_reads_failed_state(tmp_path):
    """Simula processo A chamando fail() e morrendo. Processo B (nova
    instância) lê do disco — não do objeto vivo em memória."""
    task_a = Task(id="t3", project="test-proj", description="d", priority="medium", risk="low",
                  max_attempts=3)
    task_a.fail("boom")

    queue_file = tq_mod._task_queue_file("test-proj")
    on_disk = json.loads(queue_file.read_text())
    reloaded = next(t for t in on_disk if t["id"] == "t3")
    assert reloaded["attempts"] == 1
    assert reloaded["status"] == TaskStatus.READY.value  # attempts=1 < max_attempts=3


def test_different_projects_get_different_files(tmp_path):
    """P6: estado de projeto A não contamina projeto B — arquivos separados."""
    task_a = Task(id="t4", project="proj-a", description="d", priority="medium", risk="low")
    task_b = Task(id="t5", project="proj-b", description="d", priority="medium", risk="low")
    task_a.fail("err-a")
    task_b.fail("err-b")

    file_a = tq_mod._task_queue_file("proj-a")
    file_b = tq_mod._task_queue_file("proj-b")
    assert file_a != file_b, "P6 regression: projetos usando o mesmo arquivo de estado"
    ids_a = {t["id"] for t in json.loads(file_a.read_text())}
    ids_b = {t["id"] for t in json.loads(file_b.read_text())}
    assert "t5" not in ids_a, "task do projeto B vazou pro arquivo do projeto A"
    assert "t4" not in ids_b, "task do projeto A vazou pro arquivo do projeto B"
