"""Convergence tests: nightwatch harness wired into live paths.

- Evaluator advisory review on devtools writes (LLM-free, CPU-only)
- team_bridge queue protocol (enqueue/claim/done/handoff/report)
- Checkpoint recovery summary generation (no LLM)
"""
import os

import pytest

from jarvis.core.devtools import _advisory_review
from nightwatch import team_bridge as tb


def test_advisory_review_flags_dangerous_pattern():
    diff = "+import os\n+os.system('rm -rf /')\n"
    rev = _advisory_review(diff)
    assert rev is not None
    assert rev["verdict"] == "fail"
    assert any("rm -rf" in i for i in rev["issues"])


def test_advisory_review_flags_removed_import():
    diff = "-import json\n+import sys\n"
    rev = _advisory_review(diff)
    assert rev is not None
    assert any("mport" in i for i in rev["issues"])


def test_advisory_review_clean_pass_returns_none():
    diff = "+def hello():\n+    return 1\n"
    assert _advisory_review(diff) is None


def test_advisory_review_never_raises():
    assert _advisory_review("") is None
    assert _advisory_review(None) is None  # type: ignore[arg-type]


@pytest.fixture()
def teamdir(tmp_path, monkeypatch):
    d = tmp_path / "team"
    (d / "reports").mkdir(parents=True)
    (d / "queue.md").write_text("# queue\n", encoding="utf-8")
    monkeypatch.setattr(tb, "TEAM_DIR", d)
    monkeypatch.setattr(tb, "QUEUE", d / "queue.md")
    monkeypatch.setattr(tb, "REPORTS", d / "reports")
    return d


def test_bridge_roundtrip(teamdir):
    assert tb.enqueue("t-1", "do thing", owner="dev") is True
    assert tb.enqueue("t-1", "dupe", owner="dev") is False  # id exists
    opened = tb.list_open(owner="dev")
    assert [t["id"] for t in opened] == ["t-1"]
    assert tb.claim("t-1", "dev") is True
    assert tb.claim("t-1", "dev") is False  # already claimed
    p = tb.write_report("t-1", "dev", "did it")
    assert p.exists()
    assert tb.done("t-1") is True
    assert tb.list_open(owner="dev") == []


def test_bridge_handoff_enqueues_addressed(teamdir):
    tid = tb.handoff("drift", "dev", "fix widget")
    opened = tb.list_open(owner="dev")
    assert any(t["id"] == tid for t in opened)


def test_bridge_team_executor_claims_and_reports(teamdir):
    from nightwatch.multi_agent import AgentPersona

    tb.enqueue("t-9", "wire thing", owner="any")
    persona = AgentPersona("dev", _execute_fn=tb.create_team_executor("dev"))
    res = persona.execute("t-9: wire thing", {"next_owner": "suite"})
    assert res["success"] is True
    assert "t-9" not in [t["id"] for t in tb.list_open()]  # done
    # automatic handoff to suite enqueued
    assert any(t["owner"] == "suite" for t in tb.list_open(owner="suite"))


def test_checkpoint_recovery_summary(tmp_path, monkeypatch):
    from nightwatch import checkpoint as cp_mod

    monkeypatch.setattr(cp_mod, "STATE_DIR", tmp_path)
    cp = cp_mod.create_checkpoint_for_task("task-1", "fix the widget", project="p1")
    cp.record_operation("edit", True)
    summary = cp_mod.generate_recovery_summary("p1")
    assert "fix the widget" in summary
    assert "edit" in summary
    ctx = cp_mod.get_recovery_context("p1")
    assert ctx is not None and ctx["task_id"] == "task-1" and ctx["can_retry"]
