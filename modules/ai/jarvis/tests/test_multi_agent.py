"""Tests for nightwatch/multi_agent.py — persona, handoff, orchestrator."""

from __future__ import annotations

import time

import pytest

from nightwatch.multi_agent import (
    AgentPersona,
    HandoffContext,
    Orchestrator,
    PersonaStatus,
)


def test_persona_initial_state():
    """Persona starts in IDLE state."""
    p = AgentPersona("coder", role="Engineer")
    assert p.status == PersonaStatus.IDLE
    assert p.tasks_completed == 0
    assert p.tasks_failed == 0


def test_persona_execute_success():
    """Persona executes task and tracks success."""
    p = AgentPersona("coder")
    result = p.execute("Fix bug")
    assert result["success"] is True
    assert p.tasks_completed == 1
    assert p.status == PersonaStatus.COMPLETED


def test_persona_execute_failure():
    """Persona handles execution failure."""
    def failing_fn(task, ctx):
        return {"output": "failed", "success": False}

    p = AgentPersona("coder", _execute_fn=failing_fn)
    result = p.execute("Do something")
    assert result["success"] is False
    assert p.tasks_failed == 1
    assert p.status == PersonaStatus.FAILED


def test_persona_execute_exception():
    """Persona catches exceptions during execution."""
    def exploding_fn(task, ctx):
        raise ValueError("boom")

    p = AgentPersona("coder", _execute_fn=exploding_fn)
    result = p.execute("Do something")
    assert result["success"] is False
    assert "boom" in result["output"]
    assert p.tasks_failed == 1


def test_persona_execute_custom_fn():
    """Persona uses custom execute function."""
    def custom_fn(task, ctx):
        return {"output": f"done: {task}", "success": True, "artifacts": {"file": "out.py"}}

    p = AgentPersona("coder", _execute_fn=custom_fn)
    result = p.execute("Write code")
    assert result["output"] == "done: Write code"
    assert result["artifacts"]["file"] == "out.py"


def test_handoff_context():
    """Handoff creates proper context."""
    a = AgentPersona("coder")
    b = AgentPersona("reviewer")
    ctx = a.handoff_to(b, "Review PR", artifacts={"diff": "..."}, notes="Looks good")
    assert ctx.from_persona == "coder"
    assert ctx.to_persona == "reviewer"
    assert ctx.task == "Review PR"
    assert ctx.artifacts["diff"] == "..."
    assert ctx.notes == "Looks good"
    assert a.status == PersonaStatus.WAITING
    assert b.status == PersonaStatus.ACTIVE


def test_persona_stats():
    """Stats returns current state."""
    p = AgentPersona("coder", role="Engineer")
    stats = p.stats
    assert stats["name"] == "coder"
    assert stats["role"] == "Engineer"
    assert stats["status"] == "idle"
    assert stats["completed"] == 0


def test_orchestrator_empty():
    """Orchestrator with no personas returns error."""
    orch = Orchestrator()
    result = orch.run(["task1"])
    assert "error" in result


def test_orchestrator_single_persona():
    """Orchestrator runs task through single persona."""
    orch = Orchestrator()
    orch.add_persona(AgentPersona("coder"))
    result = orch.run(["Fix bug"])
    assert result["total"] == 1
    assert result["succeeded"] == 1
    assert result["failed"] == 0


def test_orchestrator_two_personas():
    """Orchestrator runs task through two personas with handoff."""
    orch = Orchestrator()
    orch.add_persona(AgentPersona("coder"))
    orch.add_persona(AgentPersona("reviewer"))
    result = orch.run(["Implement feature"])
    assert result["total"] == 2  # one result per persona
    assert result["succeeded"] == 2
    # Check handoff occurred
    assert orch.personas[0].last_handoff is not None
    assert orch.personas[0].last_handoff.to_persona == "reviewer"


def test_orchestrator_multiple_tasks():
    """Orchestrator runs multiple tasks through persona pipeline."""
    orch = Orchestrator()
    orch.add_persona(AgentPersona("coder"))
    orch.add_persona(AgentPersona("reviewer"))
    result = orch.run(["Task A", "Task B", "Task C"])
    assert result["total"] == 6  # 3 tasks × 2 personas
    assert result["succeeded"] == 6


def test_orchestrator_context_flow():
    """Context flows between personas via handoff."""
    received_contexts = []

    def spy_fn(task, ctx):
        received_contexts.append(ctx)
        return {"output": "ok", "success": True}

    orch = Orchestrator()
    orch.add_persona(AgentPersona("coder", _execute_fn=spy_fn))
    orch.add_persona(AgentPersona("reviewer", _execute_fn=spy_fn))
    orch.run(["Test task"])

    # First persona gets clean context
    assert "task" in received_contexts[0]
    # Second persona gets previous_result in context
    assert "previous_result" in received_contexts[1]
    assert "handoff" in received_contexts[1]


def test_orchestrator_failure_propagation():
    """Failure in one persona doesn't crash the orchestrator."""
    def failing_fn(task, ctx):
        return {"output": "error", "success": False}

    orch = Orchestrator()
    orch.add_persona(AgentPersona("coder", _execute_fn=failing_fn))
    orch.add_persona(AgentPersona("reviewer"))
    result = orch.run(["Task"])
    assert result["total"] == 2
    assert result["failed"] == 1
    assert result["succeeded"] == 1


def test_orchestrator_personas_property():
    """personas property returns list of personas."""
    orch = Orchestrator()
    orch.add_persona(AgentPersona("a"))
    orch.add_persona(AgentPersona("b"))
    assert len(orch.personas) == 2
    assert orch.personas[0].name == "a"
    assert orch.personas[1].name == "b"


def test_create_llm_executor_returns_callable():
    """create_llm_executor returns a callable."""
    from nightwatch.multi_agent import create_llm_executor

    executor = create_llm_executor()
    assert callable(executor)


def test_create_llm_executor_with_custom_params():
    """create_llm_executor accepts custom parameters."""
    from nightwatch.multi_agent import create_llm_executor

    executor = create_llm_executor(
        system_prompt="You are a reviewer.",
        max_tokens=512,
        temperature=0.5,
        timeout=30,
    )
    assert callable(executor)


def test_create_llm_executor_handles_offline():
    """create_llm_executor handles LLM being offline gracefully."""
    from nightwatch.multi_agent import create_llm_executor
    import os
    os.environ["LLAMA_CPP_URL"] = "http://127.0.0.1:19999"  # wrong port

    executor = create_llm_executor(timeout=2)
    result = executor("test task", {})
    assert result["success"] is False
    assert "error" in result["output"].lower()


def test_create_file_executor_returns_callable():
    """create_file_executor returns a callable."""
    from nightwatch.multi_agent import create_file_executor

    executor = create_file_executor()
    assert callable(executor)


def test_create_file_executor_list_files(tmp_path):
    """create_file_executor lists files when task contains 'list'."""
    from nightwatch.multi_agent import create_file_executor

    (tmp_path / "test.py").write_text("print('hello')")
    executor = create_file_executor(project_root=str(tmp_path))
    result = executor("list files", {})
    assert result["success"] is True
    assert "test.py" in result["output"]


def test_create_file_executor_default_task(tmp_path):
    """create_file_executor handles default task."""
    from nightwatch.multi_agent import create_file_executor

    executor = create_file_executor(project_root=str(tmp_path))
    result = executor("do something", {})
    assert result["success"] is True
