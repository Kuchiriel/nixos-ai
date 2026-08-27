"""Tests for the eval harness."""
import json
import pytest
from pathlib import Path
from jarvis.core.eval_harness import EvalHarness, TaskTemplate, EvalResult


@pytest.fixture
def harness(tmp_path):
    return EvalHarness(results_dir=tmp_path)


class TestTaskTemplate:
    def test_minimal_task(self):
        task = TaskTemplate(id="test", description="desc", prompt="hello")
        assert task.id == "test"
        assert task.setup == ""
        assert task.success_criteria == {}

    def test_task_with_criteria(self):
        task = TaskTemplate(
            id="test",
            description="desc",
            prompt="hello",
            success_criteria={"output_contains": "hello"},
        )
        assert task.success_criteria["output_contains"] == "hello"


class TestEvalHarness:
    def test_empty_summary(self, harness):
        s = harness.summary()
        assert s["total"] == 0

    def test_run_task_success(self, harness):
        task = TaskTemplate(
            id="echo-test",
            description="echo test",
            prompt="say hello",
            success_criteria={"output_contains": "hello"},
        )

        def agent_fn(prompt):
            return {
                "final_response": "hello world",
                "tools_called": [],
                "turns": 1,
            }

        result = harness.run_task(task, agent_fn)
        assert result.success is True
        assert result.criteria_met.get("output_contains") is True
        assert result.total_turns == 1
        assert result.total_tool_calls == 0

    def test_run_task_failure(self, harness):
        task = TaskTemplate(
            id="fail-test",
            description="fail test",
            prompt="do something",
            success_criteria={"output_contains": "expected"},
        )

        def agent_fn(prompt):
            return {
                "final_response": "wrong answer",
                "tools_called": [],
                "turns": 1,
            }

        result = harness.run_task(task, agent_fn)
        assert result.success is False
        assert result.criteria_met.get("output_contains") is False

    def test_run_task_with_tools(self, harness):
        task = TaskTemplate(
            id="tool-test",
            description="tool test",
            prompt="use a tool",
        )

        def agent_fn(prompt):
            return {
                "final_response": "done",
                "tools_called": [
                    {"name": "echo", "args_preview": '{"cmd":"hi"}', "output": "hi"},
                ],
                "turns": 2,
            }

        result = harness.run_task(task, agent_fn)
        assert result.success is True
        assert result.total_tool_calls == 1
        assert len(result.trajectory) == 2  # tool + final

    def test_run_task_exception(self, harness):
        task = TaskTemplate(
            id="error-test",
            description="error test",
            prompt="crash",
        )

        def agent_fn(prompt):
            raise RuntimeError("boom")

        result = harness.run_task(task, agent_fn)
        assert result.success is False
        assert result.error == "boom"

    def test_save_results(self, harness, tmp_path):
        task = TaskTemplate(id="save-test", description="desc", prompt="hi")

        def agent_fn(prompt):
            return {"final_response": "ok", "tools_called": [], "turns": 1}

        harness.run_task(task, agent_fn)
        path = harness.save_results("test_results.jsonl")
        assert path.exists()

        with open(path) as f:
            lines = f.readlines()
        assert len(lines) == 1
        record = json.loads(lines[0])
        assert record["task_id"] == "save-test"
        assert record["success"] is True

    def test_summary_after_runs(self, harness):
        def agent_fn_ok(prompt):
            return {"final_response": "ok", "tools_called": [], "turns": 1}

        def agent_fn_fail(prompt):
            return {"final_response": "fail", "tools_called": [], "turns": 1}

        task_ok = TaskTemplate(id="ok", description="d", prompt="p",
                               success_criteria={"output_contains": "ok"})
        task_fail = TaskTemplate(id="fail", description="d", prompt="p",
                                 success_criteria={"output_contains": "expected"})

        harness.run_task(task_ok, agent_fn_ok)
        harness.run_task(task_fail, agent_fn_fail)

        s = harness.summary()
        assert s["total"] == 2
        assert s["passed"] == 1
        assert s["failed"] == 1

    def test_trajectory_steps(self, harness):
        task = TaskTemplate(id="traj", description="d", prompt="p")

        def agent_fn(prompt):
            return {
                "final_response": "answer",
                "tools_called": [
                    {"name": "read_file", "args_preview": '{"path":"x.py"}', "output": "content"},
                    {"name": "run_tests", "args_preview": '{}', "output": "1 passed"},
                ],
                "turns": 3,
            }

        result = harness.run_task(task, agent_fn)
        assert len(result.trajectory) == 3  # 2 tools + 1 final
        assert result.trajectory[0].tool_name == "read_file"
        assert result.trajectory[1].tool_name == "run_tests"
        assert result.trajectory[2].role == "assistant"
