"""Teste do endpoint clear_failed da webui (04/11, sweep).

O bug: o handler lia um path FIXO (`nightwatch/task_queue.json`) enquanto a
fila e POR PROJETO (`task_queue-<project>.json`) → o endpoint devolvia SEMPRE
`{"cleared": 0, "remaining": 0}` e o dono acreditava ter limpado a fila.
O conserto usa a API do TaskQueue (um por projeto, escrita atomica) e a
transicao suportada FAILED -> BLOCKED.

Teste OFFLINE: fila temporaria (tmp_path) via monkeypatch do STATE_DIR + HOME.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[2] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))


@pytest.fixture()
def vault_home(tmp_path, monkeypatch):
    """HOME + STATE_DIR apontando para a mesma arvore temporaria."""
    import nightwatch.task_queue as tq

    home = tmp_path / "home"
    state = home / ".local/state/jarvis/nightwatch"
    state.mkdir(parents=True)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setattr(tq, "STATE_DIR", state)
    monkeypatch.setattr(tq, "TASK_QUEUE_FILE", state / "task_queue.json")
    monkeypatch.setattr(tq, "MISSION_STATE_FILE", state / "mission_state.json")
    monkeypatch.setattr(tq, "LOOP_DETECTOR_FILE", state / "loop_detector.json")
    return state


def _write_queue(state: Path, project: str, tasks: list[dict]) -> None:
    (state / f"task_queue-{project}.json").write_text(
        json.dumps(tasks, indent=2), encoding="utf-8")


def _task(tid: str, status: str, project: str) -> dict:
    return {
        "id": tid,
        "description": f"task {tid}",
        "project": project,
        "status": status,
        "attempts": 1,
        "created_at": 1.0,
        "updated_at": 1.0,
    }


def _clear():
    import jarvis.webui.api as api

    return api.clear_failed_tasks()


def test_clear_failed_marks_failed_tasks_blocked(vault_home):
    _write_queue(vault_home, "nixos-ai", [
        _task("t1", "FAILED", "nixos-ai"),
        _task("t2", "READY", "nixos-ai"),
    ])
    out = _clear()
    assert out["cleared"] == 1, "a tarefa FAILED tem de sair do bucket"
    data = json.loads((vault_home / "task_queue-nixos-ai.json").read_text())
    by_id = {t["id"]: t for t in data}
    assert by_id["t1"]["status"] == "BLOCKED", "FAILED -> BLOCKED (transicao valida)"
    assert by_id["t2"]["status"] == "READY", "nao mexe em tarefa que nao estava FAILED"


def test_clear_failed_across_projects(vault_home):
    _write_queue(vault_home, "nixos-ai", [_task("a", "FAILED", "nixos-ai")])
    _write_queue(vault_home, "canary-official",
                 [_task("b", "FAILED", "canary-official")])
    out = _clear()
    assert out["cleared"] == 2, "as filas de TODOS os projetos contam"
    assert out["per_project"] == {"canary-official": 1, "nixos-ai": 1}


def test_clear_failed_no_queue_is_noop(vault_home):
    out = _clear()
    assert out["cleared"] == 0
    assert out["remaining"] == 0
