"""Unit tests for the discovery quality gate (safety.validate_task_quality)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nightwatch.safety import validate_task_quality
import nightwatch.task_queue as tq


def test_rejects_vacuous():
    assert not validate_task_quality("Tests failing: ", [], "x").passed
    assert not validate_task_quality("fix", [], "x").passed
    assert not validate_task_quality("", [], "x").passed


def test_rejects_directory_target(tmp_path):
    d = tmp_path / "tests"
    d.mkdir()
    g = validate_task_quality("Add real unit tests for parser", [str(d)], "x")
    assert not g.passed and g.stage_failed == "directory-target"


def test_rejects_protected_project():
    g = validate_task_quality("Update package versions everywhere", ["a.py"], "nixpkgs")
    assert not g.passed and g.stage_failed == "protected-project"


def test_accepts_good_and_create(tmp_path, monkeypatch):
    monkeypatch.setattr(tq, "STATE_DIR", tmp_path)
    q = tq.TaskQueue(project="t")
    ok_task = tq.Task(id="g1", project="t",
                      description="Add retry button to tasks page",
                      target_files=["new-component.svelte"])
    assert q.add_task(ok_task) is True
    bad = tq.Task(id="b1", project="t", description="Tests failing: ",
                  target_files=[])
    assert q.add_task(bad) is False
    assert q.get_task("b1") is None
