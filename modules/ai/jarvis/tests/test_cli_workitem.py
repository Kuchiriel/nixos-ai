"""Tests for the workitem CLI transition command."""

from types import SimpleNamespace

import pytest
from jarvis.cli.main import _cmd_workitem, build_parser
from nightwatch import task_queue as task_queue_module


@pytest.fixture
def demo_queue(tmp_path, monkeypatch):
    """Create an isolated per-project queue with one discovered task."""
    monkeypatch.setattr(task_queue_module, "STATE_DIR", tmp_path)
    monkeypatch.setattr(
        task_queue_module, "TASK_QUEUE_FILE", tmp_path / "legacy_tasks.json"
    )
    monkeypatch.setattr(
        task_queue_module, "MISSION_STATE_FILE", tmp_path / "legacy_mission.json"
    )

    queue = task_queue_module.TaskQueue(project="demo")
    task = task_queue_module.Task(
        id="task-1",
        project="demo",
        description="Research a measurable improvement",
    )
    queue._tasks = [task]
    queue._save()
    return queue


def _args(**overrides):
    values = {
        "project": "demo",
        "create": None,
        "transition": None,
        "list": False,
        "next": False,
        "burndown": False,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_workitem_transition_persists_valid_status(demo_queue, capsys):
    assert _cmd_workitem(_args(transition=("task-1", "READY"))) == 0

    persisted = task_queue_module.TaskQueue(project="demo").get_task("task-1")
    assert persisted is not None
    assert persisted.status == "READY"
    assert "DISCOVERED -> READY" in capsys.readouterr().out


def test_workitem_transition_rejects_invalid_transition(demo_queue, capsys):
    assert _cmd_workitem(_args(transition=("task-1", "COMPLETED"))) == 1

    persisted = task_queue_module.TaskQueue(project="demo").get_task("task-1")
    assert persisted is not None
    assert persisted.status == "DISCOVERED"
    assert "Invalid transition" in capsys.readouterr().err


def test_workitem_transition_rejects_unknown_task(demo_queue, capsys):
    assert _cmd_workitem(_args(transition=("missing", "READY"))) == 1
    assert "Task not found" in capsys.readouterr().err


def test_workitem_transition_rejects_unknown_status(demo_queue, capsys):
    assert _cmd_workitem(_args(transition=("task-1", "NOPE"))) == 1
    assert "Invalid status" in capsys.readouterr().err


def test_workitem_parser_routes_transition_arguments():
    args = build_parser().parse_args(
        ["workitem", "--project", "demo", "--transition", "task-1", "READY"]
    )

    assert args.project == "demo"
    assert list(args.transition) == ["task-1", "READY"]
