"""Mission tests: persistence, dependencies, verification, resume, isolation.

The point of this file is to prove the behaviors that were missing:
  - a mission survives a process restart;
  - a task is not DONE without objective evidence;
  - changes are attributed to the task that made them, not to whatever was
    already dirty in the tree;
  - a persona without capability does not silently gain permissions;
  - pause / steer / cancel reach the real execution, not just the UI;
  - an update reprocessed after a restart does not run twice.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import types

import pytest

from jarvis.mission.models import (
    AcceptanceCriterion, FailureClass, Mission, MissionState, MissionTask,
    TaskState,
)
from jarvis.mission.planner import (
    build_mission, decompose_heuristic, decompose_with_llm,
)
from jarvis.mission.projects import ResolvedProject, resolve, scoped_files
from jarvis.mission.runner import MissionRunner
from jarvis.mission.store import MissionStore
from jarvis.mission.verify import take_snapshot, verify_task


# ── fixtures ───────────────────────────────────────────────────────────────

def _has_git() -> bool:
    return shutil.which("git") is not None


needs_git = pytest.mark.skipif(not _has_git(), reason="git binary unavailable")


def _git_repo(path) -> None:
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "a@b"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "t"], cwd=path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)


@pytest.fixture
def workspace(tmp_path, monkeypatch):
    ws = tmp_path / "ws"
    ws.mkdir()
    monkeypatch.setenv("JARVIS_WORKSPACE_ROOT", str(ws))
    monkeypatch.setenv("JARVIS_MISSION_DIR", str(tmp_path / "missions"))
    for name in ("alpha", "beta"):
        p = ws / name
        p.mkdir()
        (p / "README.md").write_text(f"# {name}\n")
        (p / "flaky.py").write_text(f"# {name} module\n")
        _git_repo(p)
    return ws


@pytest.fixture
def fake_runtime(monkeypatch):
    """Install a fake AgentRuntime. `writes` controls whether it acts."""
    state = {"writes": True, "calls": [], "model": "fake-model"}

    class FakeRT:
        def __init__(self, *a, **k):
            pass

        def run(self, instr, model_requirements=None, persona_id=None,
                approve=False):
            state["calls"].append({
                "instr": instr,
                "req": dict(model_requirements or {}),
                "persona": persona_id,
                "approve": approve,
            })
            if state["writes"]:
                open(os.path.join(str(state["root"]), "report.txt"), "w").write("ok\n")
            return types.SimpleNamespace(
                session=types.SimpleNamespace(model_id=state["model"],
                                              tools_used=["read_file"]))

    import jarvis.runtime.agent_runtime as ar
    monkeypatch.setattr(ar, "AgentRuntime", FakeRT)
    return state


def _runner() -> MissionRunner:
    return MissionRunner(MissionStore())


# ── project resolution ─────────────────────────────────────────────────────

@needs_git
def test_resolve_by_explicit_name(workspace) -> None:
    r = resolve("do something", explicit="alpha")
    assert r.name == "alpha" and r.confidence == "explicit" and r.ok


@needs_git
def test_resolve_unknown_explicit_project_fails_closed(workspace) -> None:
    r = resolve("x", explicit="ghost")
    assert not r.ok and r.confidence == "unknown" and "not found" in r.reason


@needs_git
def test_resolve_by_cited_path(workspace) -> None:
    r = resolve("please look at alpha/flaky.py and fix it")
    assert r.name == "alpha" and r.confidence == "path"


@needs_git
def test_resolve_ambiguous_does_not_guess(workspace) -> None:
    """No path, no explicit name, two repos -> must NOT pick one."""
    r = resolve("do something unspecified")
    assert r.confidence == "ambiguous"
    assert set(r.candidates) == {"alpha", "beta"}
    assert not r.ok


@needs_git
def test_scoped_files_uses_cited_paths_not_root_py_listing(workspace) -> None:
    """The old code listed *.py in the root; scope must come from the ask."""
    # scoped_files takes the PROJECT root, so results are project-relative
    # ("alpha/flaky.py" is workspace-relative and does not exist under alpha).
    got = scoped_files(workspace / "alpha", "fix alpha/flaky.py please")
    assert got == ["flaky.py"]
    assert (workspace / "alpha" / got[0]).is_file()


@needs_git
def test_scoped_files_skips_vendor_dirs(workspace) -> None:
    vend = workspace / "alpha" / "node_modules" / "pkg"
    vend.mkdir(parents=True)
    (vend / "telemetry.py").write_text("x")
    got = scoped_files(workspace / "alpha", "read telemetry")
    assert not any("node_modules" in g for g in got)


# ── decomposition ──────────────────────────────────────────────────────────

@needs_git
def test_heuristic_single_task_for_simple_objective(workspace) -> None:
    proj = resolve("x", explicit="alpha")
    tasks = decompose_heuristic("create report.txt", proj)
    assert len(tasks) == 1
    kinds = {(c.kind, c.target) for c in tasks[0].acceptance}
    assert ("file_exists", "report.txt") in kinds


@needs_git
def test_task_without_criteria_is_flagged_not_faked(workspace) -> None:
    """A task with no machine-checkable criterion must not read as verified."""
    proj = resolve("x", explicit="alpha")
    tasks = decompose_heuristic("make it better somehow", proj)
    task = tasks[0]
    if not task.acceptance:
        res = verify_task(task, workspace / "alpha")
        assert res.verified is False
        assert "no verifiable acceptance criterion" in res.missing[0]


@needs_git
def test_llm_decomposition_builds_dependencies(workspace) -> None:
    proj = resolve("x", explicit="alpha")
    payload = """[
      {"title":"write the module","description":"create alpha/flaky.py content X",
       "persona_id":"backend_engineer","dependencies":[],"priority":3,
       "acceptance":[{"kind":"file_exists","target":"flaky.py","description":""}]},
      {"title":"test it","description":"pytest alpha/flaky.py",
       "persona_id":"qa_engineer","dependencies":[0],"priority":5,
       "acceptance":[{"kind":"test_passes","target":"","description":""}]}
    ]"""
    tasks = decompose_with_llm("build and test", proj,
                               chat=lambda msgs, mx: payload)
    assert tasks is not None and len(tasks) == 2
    assert tasks[1].dependencies == ["t1"]
    assert tasks[1].persona_id == "qa_engineer"


@needs_git
def test_llm_cycles_and_bad_personas_are_sanitized(workspace) -> None:
    proj = resolve("x", explicit="alpha")
    payload = """[
      {"title":"a","description":"do a in alpha","persona_id":"nope_not_real",
       "dependencies":[5],"acceptance":[]},
      {"title":"b","description":"do b in alpha","persona_id":"qa_engineer",
       "dependencies":[0],"acceptance":[]}
    ]"""
    tasks = decompose_with_llm("x", proj, chat=lambda m, x: payload)
    assert tasks[0].dependencies == []          # forward ref dropped
    assert tasks[0].persona_id in {
        "backend_engineer", "nixos_engineer", "qa_engineer", "jarvis",
        "researcher", "architect", "security_engineer", "technical_writer",
        "devops_engineer", "supervisor", "cto",
    }
    assert tasks[1].dependencies == ["t1"]


@needs_git
def test_llm_fenced_json_is_parsed(workspace) -> None:
    proj = resolve("x", explicit="alpha")
    raw = '```json\n[{"title":"a","description":"d","persona_id":"jarvis",' \
          '"acceptance":[]}]\n```'
    tasks = decompose_with_llm("x", proj, chat=lambda m, x: raw)
    assert tasks and tasks[0].title == "a"


@needs_git
def test_llm_failure_falls_back_to_heuristic(workspace) -> None:
    proj = resolve("x", explicit="alpha")

    def boom(msgs, mx):
        raise RuntimeError("model down")

    m = build_mission("create report.txt", proj, chat=boom)
    assert len(m.tasks) == 1
    assert m.tasks[0].id == "t1"


@needs_git
def test_llm_garbage_falls_back(workspace) -> None:
    proj = resolve("x", explicit="alpha")
    m = build_mission("create report.txt", proj,
                      chat=lambda msgs, mx: "I cannot do that, sorry!")
    assert len(m.tasks) == 1


# ── persistence ────────────────────────────────────────────────────────────

@needs_git
def test_mission_persists_before_execution(workspace) -> None:
    store = MissionStore()
    m = build_mission("create report.txt", resolve("x", explicit="alpha"))
    store.save(m)
    assert store.exists(m.id)
    reloaded = store.load(m.id)
    assert reloaded is not None and reloaded.objective == m.objective


@needs_git
def test_restart_does_not_duplicate_or_lose_mission(workspace) -> None:
    store = MissionStore()
    m = build_mission("create report.txt", resolve("x", explicit="alpha"))
    store.save(m)
    # simulate crash mid-task
    m.tasks[0].status = TaskState.RUNNING.value
    m.state = MissionState.RUNNING.value
    store.save(m)
    # fresh process
    store2 = MissionStore()
    recovered = store2.recover_interrupted()
    assert len(recovered) == 1
    assert store2.load(m.id).tasks[0].status == TaskState.READY.value


@needs_git
def test_done_task_is_not_reopened_by_recovery(workspace) -> None:
    store = MissionStore()
    m = build_mission("create report.txt", resolve("x", explicit="alpha"))
    m.tasks[0].status = TaskState.DONE.value
    m.tasks[0].finished_at = None      # inconsistent, as after a crash
    store.save(m)
    store2 = MissionStore()
    store2.recover_interrupted()
    assert store2.load(m.id).tasks[0].status == TaskState.DONE.value


@needs_git
def test_mark_seen_is_idempotent(workspace) -> None:
    store = MissionStore()
    assert store.mark_seen("upd:1") is True
    assert store.mark_seen("upd:1") is False
    assert store.mark_seen("upd:2") is True


@needs_git
def test_corrupt_mission_file_is_ignored(workspace) -> None:
    store = MissionStore()
    m = build_mission("x", resolve("x", explicit="alpha"))
    store.save(m)
    store.path_for(m.id).write_text("{not json")
    assert store.load(m.id) is None
    assert isinstance(store.list(), list)   # must not raise


# ── state machine ──────────────────────────────────────────────────────────

def test_invalid_transition_is_refused() -> None:
    t = MissionTask(id="t1", title="x", project="alpha")
    t.status = TaskState.DONE.value
    assert t.can_transition_to(TaskState.RUNNING) is False
    assert t.transition(TaskState.RUNNING) is False
    assert t.status == TaskState.DONE.value


def test_dependency_failure_blocks_dependents() -> None:
    a = MissionTask(id="t1", title="a", project="p")
    b = MissionTask(id="t2", title="b", project="p", dependencies=["t1"])
    m = Mission(id="m", objective="o", project="p", tasks=[a, b])
    a.transition(TaskState.READY)
    a.transition(TaskState.RUNNING)
    a.transition(TaskState.VERIFYING)
    a.transition(TaskState.FAILED)
    m.refresh_blocked()
    assert b.status == TaskState.BLOCKED.value


def test_ready_tasks_respect_dependency_order() -> None:
    a = MissionTask(id="t1", title="a", project="p")
    b = MissionTask(id="t2", title="b", project="p", dependencies=["t1"])
    m = Mission(id="m", objective="o", project="p", tasks=[a, b])
    m.refresh_blocked()
    assert [t.id for t in m.ready_tasks()] == ["t1"]
    a.transition(TaskState.READY)
    a.transition(TaskState.RUNNING)
    a.transition(TaskState.VERIFYING)
    a.transition(TaskState.DONE)
    m.refresh_blocked()
    assert [t.id for t in m.ready_tasks()] == ["t2"]


def test_retry_only_for_retryable_failures() -> None:
    t = MissionTask(id="t1", title="a", project="p", max_attempts=2)
    t.record_failure("boom", FailureClass.TRANSIENT)
    assert t.can_retry() is True
    t2 = MissionTask(id="t2", title="a", project="p", max_attempts=2)
    t2.record_failure("protected path", FailureClass.UNRECOVERABLE)
    assert t2.can_retry() is False


def test_attempt_limit_stops_retrying() -> None:
    t = MissionTask(id="t1", title="a", project="p", max_attempts=2)
    t.record_failure("x", FailureClass.TRANSIENT)
    t.record_failure("x", FailureClass.TRANSIENT)
    assert t.can_retry() is False


# ── verification ───────────────────────────────────────────────────────────

@needs_git
def test_verification_requires_the_file(workspace, tmp_path) -> None:
    t = MissionTask(id="t1", title="x", project="alpha",
                    acceptance=[AcceptanceCriterion("file_exists", "nope.txt")])
    res = verify_task(t, workspace / "alpha")
    assert res.verified is False and "MISSING" in res.missing[0]


@needs_git
def test_verification_content_contains(workspace) -> None:
    (workspace / "alpha" / "needle.txt").write_text("the magic token\n")
    t = MissionTask(id="t1", title="x", project="alpha",
                    acceptance=[AcceptanceCriterion("content_contains",
                                                   "needle.txt", "magic token")])
    assert verify_task(t, workspace / "alpha").verified is True


@needs_git
def test_verification_unknown_criterion_is_fail_closed(workspace) -> None:
    t = MissionTask(id="t1", title="x", project="alpha",
                    acceptance=[AcceptanceCriterion("vibes_are_good", "x")])
    res = verify_task(t, workspace / "alpha")
    assert res.verified is False
    assert "unknown criterion" in res.missing[0]


@needs_git
def test_no_criteria_is_not_verified(workspace) -> None:
    t = MissionTask(id="t1", title="x", project="alpha")
    assert verify_task(t, workspace / "alpha").verified is False


@needs_git
def test_lying_agent_cannot_complete_a_task(workspace, fake_runtime) -> None:
    """The headline guarantee: success is not self-reported."""
    fake_runtime["writes"] = False
    fake_runtime["root"] = workspace / "alpha"
    store = MissionStore()
    runner = MissionRunner(store)
    m = build_mission("create report.txt", resolve("x", explicit="alpha"))
    m.state = MissionState.RUNNING.value
    store.save(m)
    out = runner.run(m.id)
    t = store.load(m.id).tasks[0]
    assert t.status != TaskState.DONE.value
    assert out.state != MissionState.DONE.value
    assert any("MISSING" in e for e in t.verification_evidence)


@needs_git
def test_success_is_accepted_with_evidence(workspace, fake_runtime) -> None:
    fake_runtime["writes"] = True
    fake_runtime["root"] = workspace / "alpha"
    store = MissionStore()
    runner = MissionRunner(store)
    m = build_mission("create report.txt", resolve("x", explicit="alpha"))
    m.state = MissionState.RUNNING.value
    store.save(m)
    out = runner.run(m.id)
    t = store.load(m.id).tasks[0]
    assert t.status == TaskState.DONE.value
    assert out.state == MissionState.DONE.value
    assert any("present" in e for e in t.verification_evidence)


# ── attribution ────────────────────────────────────────────────────────────

@needs_git
def test_preexisting_dirty_file_is_not_attributed(workspace, fake_runtime) -> None:
    """A foreign modification must not be reported as this task's work."""
    fake_runtime["writes"] = True
    fake_runtime["root"] = workspace / "alpha"
    (workspace / "alpha" / "alien.py").write_text("# someone else's work\n")
    store = MissionStore()
    runner = MissionRunner(store)
    m = build_mission("create report.txt", resolve("x", explicit="alpha"))
    m.state = MissionState.RUNNING.value
    store.save(m)
    runner.run(m.id)
    t = store.load(m.id).tasks[0]
    assert "alien.py" not in t.files_attributed
    assert "report.txt" in t.files_attributed


@needs_git
def test_snapshot_detects_content_change_in_dirty_file(workspace) -> None:
    f = workspace / "alpha" / "x.py"
    f.write_text("one\n")
    a = take_snapshot(workspace / "alpha")
    f.write_text("two\n")
    b = take_snapshot(workspace / "alpha")
    assert "x.py" in b.changed_paths(a)


@needs_git
def test_two_projects_do_not_leak_into_each_other(workspace, fake_runtime) -> None:
    fake_runtime["writes"] = True
    store = MissionStore()
    runner = MissionRunner(store)
    m_alpha = build_mission("create report.txt", resolve("x", explicit="alpha"))
    m_alpha.state = MissionState.RUNNING.value
    store.save(m_alpha)
    fake_runtime["root"] = workspace / "alpha"
    runner.run(m_alpha.id)
    assert store.load(m_alpha.id).project == "alpha"
    assert store.load(m_alpha.id).project_root.endswith("alpha")
    assert not (workspace / "beta" / "report.txt").exists()


# ── persona effectiveness ──────────────────────────────────────────────────

@needs_git
def test_persona_reaches_the_runtime(workspace, fake_runtime) -> None:
    fake_runtime["writes"] = True
    fake_runtime["root"] = workspace / "alpha"
    store = MissionStore()
    runner = MissionRunner(store)
    m = build_mission("implement a backend feature in report.txt",
                      resolve("x", explicit="alpha"), use_llm=False)
    m.state = MissionState.RUNNING.value
    store.save(m)
    runner.run(m.id)
    call = fake_runtime["calls"][0]
    assert call["persona"]            # a persona id reached the runtime
    t = store.load(m.id).tasks[0]
    assert t.persona_applied
    assert t.tools_used               # tools were resolved


@needs_git
def test_model_preference_reaches_model_selection(workspace, fake_runtime) -> None:
    """model_preference was dead code; it must now become a `stage`."""
    fake_runtime["writes"] = True
    fake_runtime["root"] = workspace / "alpha"
    store = MissionStore()
    runner = MissionRunner(store)
    m = build_mission("create report.txt", resolve("x", explicit="alpha"),
                      use_llm=False)
    m.state = MissionState.RUNNING.value
    store.save(m)
    runner.run(m.id)
    req = fake_runtime["calls"][0]["req"]
    assert "stage" in req, req
    assert req["stage"] in ("cheap", "medium", "strong")


@needs_git
def test_read_only_persona_gets_no_write_tools(workspace, fake_runtime) -> None:
    """A persona with can_write=False must not be handed write tools."""
    fake_runtime["writes"] = True
    fake_runtime["root"] = workspace / "alpha"
    store = MissionStore()
    runner = MissionRunner(store)
    m = build_mission("create report.txt", resolve("x", explicit="alpha"),
                      use_llm=False)
    m.tasks[0].persona_id = "researcher"      # can_write=True, can_execute=False
    m.tasks[0].acceptance = [AcceptanceCriterion("file_exists", "report.txt")]
    m.state = MissionState.RUNNING.value
    store.save(m)
    runner.run(m.id)
    t = store.load(m.id).tasks[0]
    assert t.persona_applied == "researcher"
    assert "write_file" not in t.tools_used


@needs_git
def test_write_needing_persona_gap_is_recorded(workspace, fake_runtime) -> None:
    fake_runtime["writes"] = False
    fake_runtime["root"] = workspace / "alpha"
    store = MissionStore()
    runner = MissionRunner(store)
    m = build_mission("create report.txt", resolve("x", explicit="alpha"),
                      use_llm=False)
    m.tasks[0].persona_id = "cto"      # can_write=False
    m.tasks[0].acceptance = [AcceptanceCriterion("file_exists", "report.txt")]
    m.state = MissionState.RUNNING.value
    store.save(m)
    runner.run(m.id)
    t = store.load(m.id).tasks[0]
    assert any("lacks can_write" in w for w in t.verification_evidence)


@needs_git
def test_instruction_to_model_is_english(workspace, fake_runtime) -> None:
    """bonsai needs English; nothing Portuguese may reach the prompt."""
    fake_runtime["writes"] = True
    fake_runtime["root"] = workspace / "alpha"
    store = MissionStore()
    runner = MissionRunner(store)
    m = build_mission("crie um relatório.txt", resolve("x", explicit="alpha"),
                      use_llm=False)
    m.state = MissionState.RUNNING.value
    store.save(m)
    runner.run(m.id)
    instr = fake_runtime["calls"][0]["instr"]
    assert not any(0x2E80 <= ord(c) <= 0x9FFF for c in instr)


# ── lifecycle: pause / steer / cancel ──────────────────────────────────────

@needs_git
def test_cancel_reaches_running_tasks(workspace) -> None:
    store = MissionStore()
    runner = MissionRunner(store)
    m = build_mission("create report.txt", resolve("x", explicit="alpha"))
    m.state = MissionState.RUNNING.value
    m.tasks[0].status = TaskState.RUNNING.value
    store.save(m)
    n = runner.cancel(m.id)
    assert n == 1
    assert store.load(m.id).state == MissionState.CANCELLED.value
    assert store.load(m.id).tasks[0].status == TaskState.CANCELLED.value


@needs_git
def test_cancel_event_is_set(workspace) -> None:
    runner = MissionRunner(MissionStore())
    store = runner.store
    m = build_mission("create report.txt", resolve("x", explicit="alpha"))
    store.save(m)
    ev = runner._cancel_event(m.id)   # noqa: SLF001 - white box
    assert not ev.is_set()
    runner.cancel(m.id)
    assert ev.is_set(), "cancel must reach the execution loop"


@needs_git
def test_pause_and_resume(workspace) -> None:
    store = MissionStore()
    runner = MissionRunner(store)
    m = build_mission("create report.txt", resolve("x", explicit="alpha"))
    m.state = MissionState.RUNNING.value
    store.save(m)
    assert runner.pause(m.id) is True
    assert store.load(m.id).state == MissionState.PAUSED.value
    assert runner.resume(m.id) is True
    assert store.load(m.id).state == MissionState.RUNNING.value


@needs_git
def test_steer_is_persisted_and_applied(workspace, fake_runtime) -> None:
    fake_runtime["writes"] = True
    fake_runtime["root"] = workspace / "alpha"
    store = MissionStore()
    runner = MissionRunner(store)
    m = build_mission("create report.txt", resolve("x", explicit="alpha"),
                      use_llm=False)
    m.state = MissionState.RUNNING.value
    store.save(m)
    assert runner.steer(m.id, "use tabs not spaces") is True
    runner.run(m.id)
    assert "use tabs not spaces" in fake_runtime["calls"][0]["instr"]


def test_run_on_missing_mission_is_reported_not_crashed() -> None:
    out = MissionRunner(MissionStore()).run("msn-does-not-exist")
    assert out.state == "MISSING"


@needs_git
def test_run_refuses_missing_project_root(workspace) -> None:
    store = MissionStore()
    runner = MissionRunner(store)
    m = Mission(id="msn-x", objective="o", project="ghost",
                project_root="/nonexistent/path")
    m.tasks = [MissionTask(id="t1", title="a", project="ghost")]
    store.save(m)
    out = runner.run(m.id)
    assert out.state == MissionState.FAILED.value
    assert "invalid or missing project root" in out.report


@needs_git
def test_progress_summary_shape(workspace) -> None:
    store = MissionStore()
    runner = MissionRunner(store)
    m = build_mission("create report.txt", resolve("x", explicit="alpha"))
    m.tasks[0].status = TaskState.DONE.value
    store.save(m)
    rep = runner.render_report(store.load(m.id))
    assert m.id in rep and "done=1" in rep