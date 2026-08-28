"""Minimal eval harness for agent trajectory recording and task evaluation.

Records complete agent trajectories (prompts, tool calls, results, timing)
and evaluates them against task templates with clear success criteria.

Usage:
    from jarvis.core.eval_harness import EvalHarness, TaskTemplate

    harness = EvalHarness()
    task = TaskTemplate(
        id="fix-import",
        description="Fix missing import in module X",
        setup="echo 'broken' > /tmp/test.py",
        success_criteria={"exit_code": 0, "output_contains": "import"},
    )
    result = harness.run_task(task, agent_fn)
    harness.save_results("eval_results.jsonl")
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

from jarvis.core.logging import get_logger

log = get_logger("eval_harness")


@dataclass
class TaskTemplate:
    """Defines an eval task with setup, prompt, and success criteria."""
    id: str
    description: str
    prompt: str  # what to send to the agent
    setup: str = ""  # shell command to run before the task
    teardown: str = ""  # shell command to run after the task
    success_criteria: dict[str, Any] = field(default_factory=dict)
    # success_criteria keys:
    #   exit_code: int — expected exit code
    #   output_contains: str — output must contain this string
    #   output_not_contains: str — output must NOT contain this string
    #   file_exists: str — file must exist after task
    #   file_contains: dict[str, str] — {path: substring}
    #   max_turns: int — max turns allowed
    #   max_time_s: int — max wall-clock time
    timeout_s: int = 120


@dataclass
class TrajectoryStep:
    """One step in an agent trajectory."""
    turn: int
    role: str  # "assistant" | "tool" | "system"
    content: str
    tool_calls: list[dict] | None = None
    tool_name: str | None = None
    tool_args: dict | None = None
    tool_output: str | None = None
    duration_ms: float = 0
    tokens_in: int = 0
    tokens_out: int = 0


@dataclass
class EvalResult:
    """Result of evaluating a single task."""
    task_id: str
    success: bool
    criteria_met: dict[str, bool]
    trajectory: list[TrajectoryStep]
    total_turns: int
    total_time_s: float
    total_tool_calls: int
    error: str | None = None


class EvalHarness:
    """Records trajectories and evaluates tasks."""

    def __init__(self, results_dir: str | Path | None = None):
        self.results_dir = Path(results_dir) if results_dir else Path("eval_results")
        self.results_dir.mkdir(parents=True, exist_ok=True)
        self.results: list[EvalResult] = []

    def run_task(self, task: TaskTemplate,
                 agent_fn: Callable[[str], dict[str, Any]]) -> EvalResult:
        """Run a task through the agent and record the trajectory.

        agent_fn should accept a prompt and return:
            {"response": str, "tool_calls": list, "turns": int, ...}
        """
        import subprocess
        import shlex

        trajectory: list[TrajectoryStep] = []
        criteria_met: dict[str, bool] = {}
        error = None

        try:
            # Setup
            if task.setup:
                # Usa shlex.split() ao invés de shell=True para segurança
                argv = shlex.split(task.setup)
                subprocess.run(argv, capture_output=True,
                               timeout=30, text=True)

            start = time.monotonic()

            # Run agent
            result = agent_fn(task.prompt)

            elapsed = time.monotonic() - start

            # Build trajectory from result
            turns = result.get("turns", 0)
            tool_calls = result.get("tools_called", [])

            for i, tc in enumerate(tool_calls):
                trajectory.append(TrajectoryStep(
                    turn=i,
                    role="tool",
                    content=tc.get("output", "")[:500],
                    tool_name=tc.get("name"),
                    tool_args=json.loads(tc["args_preview"]) if tc.get("args_preview") else None,
                ))

            # Final response
            trajectory.append(TrajectoryStep(
                turn=turns,
                role="assistant",
                content=result.get("final_response", "")[:500],
            ))

            # Check success criteria
            final_text = result.get("final_response", "")
            exit_code = result.get("exit_code", 0)

            if "exit_code" in task.success_criteria:
                criteria_met["exit_code"] = (exit_code == task.success_criteria["exit_code"])
            if "output_contains" in task.success_criteria:
                criteria_met["output_contains"] = (
                    task.success_criteria["output_contains"] in final_text
                )
            if "output_not_contains" in task.success_criteria:
                criteria_met["output_not_contains"] = (
                    task.success_criteria["output_not_contains"] not in final_text
                )
            if "file_exists" in task.success_criteria:
                criteria_met["file_exists"] = Path(task.success_criteria["file_exists"]).exists()
            if "max_turns" in task.success_criteria:
                criteria_met["max_turns"] = (turns <= task.success_criteria["max_turns"])
            if "max_time_s" in task.success_criteria:
                criteria_met["max_time_s"] = (elapsed <= task.success_criteria["max_time_s"])

            # If no criteria specified, success = got a response
            if not criteria_met:
                criteria_met["has_response"] = bool(final_text)

            success = all(criteria_met.values()) if criteria_met else True

            # Teardown
            if task.teardown:
                argv = shlex.split(task.teardown)
                subprocess.run(argv, capture_output=True,
                               timeout=30, text=True)

            eval_result = EvalResult(
                task_id=task.id,
                success=success,
                criteria_met=criteria_met,
                trajectory=trajectory,
                total_turns=turns,
                total_time_s=elapsed,
                total_tool_calls=len(tool_calls),
            )

        except Exception as e:
            error = str(e)
            eval_result = EvalResult(
                task_id=task.id,
                success=False,
                criteria_met={},
                trajectory=trajectory,
                total_turns=0,
                total_time_s=0,
                total_tool_calls=0,
                error=error,
            )

        self.results.append(eval_result)
        log.info("eval_task", detail={
            "task_id": task.id,
            "success": eval_result.success,
            "turns": eval_result.total_turns,
            "time_s": round(eval_result.total_time_s, 1),
        })
        return eval_result

    def save_results(self, filename: str = "eval_results.jsonl") -> Path:
        """Save all results to JSONL."""
        path = self.results_dir / filename
        with open(path, "w") as f:
            for r in self.results:
                record = {
                    "task_id": r.task_id,
                    "success": r.success,
                    "criteria_met": r.criteria_met,
                    "total_turns": r.total_turns,
                    "total_time_s": round(r.total_time_s, 2),
                    "total_tool_calls": r.total_tool_calls,
                    "error": r.error,
                    "trajectory_summary": [
                        {"role": s.role, "tool": s.tool_name, "content": s.content[:200]}
                        for s in r.trajectory
                    ],
                }
                f.write(json.dumps(record) + "\n")
        return path

    def summary(self) -> dict[str, Any]:
        """Return summary statistics."""
        if not self.results:
            return {"total": 0}
        return {
            "total": len(self.results),
            "passed": sum(1 for r in self.results if r.success),
            "failed": sum(1 for r in self.results if not r.success),
            "avg_turns": round(sum(r.total_turns for r in self.results) / len(self.results), 1),
            "avg_time_s": round(sum(r.total_time_s for r in self.results) / len(self.results), 1),
            "avg_tool_calls": round(sum(r.total_tool_calls for r in self.results) / len(self.results), 1),
        }


# ── Built-in task templates for nixos-ai ──

JARVIS_EVAL_TASKS = [
    TaskTemplate(
        id="read-existing-file",
        description="Read a known file from the project",
        prompt="Read the file modules/ai/jarvis/src/jarvis/core/config.py and tell me what class it defines.",
        success_criteria={"output_contains": "class"},
    ),
    TaskTemplate(
        id="list-directory",
        description="List a directory",
        prompt="List the contents of the modules/ai/jarvis/src/jarvis/core/ directory.",
        success_criteria={"output_contains": ".py"},
    ),
    TaskTemplate(
        id="shell-echo",
        description="Run a simple shell command",
        prompt="Run the command: echo hello-jarvis-eval",
        success_criteria={"output_contains": "hello-jarvis-eval"},
    ),
    TaskTemplate(
        id="write-and-read",
        description="Write a file and read it back",
        prompt="Write 'eval-test-content' to /tmp/jarvis-eval-test.txt, then read it back and confirm the content.",
        success_criteria={"output_contains": "eval-test-content"},
        teardown="rm -f /tmp/jarvis-eval-test.txt",
    ),
    TaskTemplate(
        id="code-search",
        description="Search for a function definition",
        prompt="Use code_search to find the function 'get_config' in the jarvis codebase.",
        success_criteria={"output_contains": "get_config"},
    ),
]
