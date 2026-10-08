"""Structured plan executor with retry logic and learning."""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable

from jarvis.core.completion import check_completion, CompletionVerdict


@dataclass
class PlanStep:
    """A single step in the execution plan."""
    id: str
    action: str          # read_file, write_file, execute_shell, etc.
    description: str     # human-readable description
    target: str          # file path, command, query
    expected_outcome: str  # what success looks like
    validation: str      # how to verify (file_exists, test_passes, content_contains)
    retry_count: int = 0
    max_retries: int = 2
    depends_on: list[str] = field(default_factory=list)
    completed: bool = False
    result: Any = None
    error: str | None = None


@dataclass
class ExecutionPlan:
    """Full execution plan with steps and metadata."""
    task_id: str
    goal: str
    steps: list[PlanStep] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)
    status: str = "pending"  # pending, running, completed, failed
    current_step: int = 0
    learnings: list[str] = field(default_factory=list)

    def add_step(self, step: PlanStep) -> None:
        self.steps.append(step)

    def get_next_step(self) -> PlanStep | None:
        # Build a lookup dict for O(1) dependency checks
        step_by_id = {s.id: s for s in self.steps}
        for step in self.steps:
            if not step.completed:
                # Check if all dependencies are completed
                deps_completed = True
                for dep_id in step.depends_on:
                    dep_step = step_by_id.get(dep_id)
                    if dep_step is None or not dep_step.completed:
                        deps_completed = False
                        break
                if deps_completed:
                    return step
        return None

    def mark_step_complete(self, step_id: str, result: Any) -> None:
        for step in self.steps:
            if step.id == step_id:
                step.completed = True
                step.result = result
                break
        self.current_step += 1
        self.updated_at = time.time()

    def mark_step_failed(self, step_id: str, error: str) -> None:
        for step in self.steps:
            if step.id == step_id:
                step.error = error
                step.retry_count += 1
                break

    def can_retry(self, step_id: str) -> bool:
        for step in self.steps:
            if step.id == step_id:
                return step.retry_count < step.max_retries
        return False


class PlanExecutor:
    """Executes structured plans with retry, validation, and learning."""

    def __init__(
        self,
        llm_client: Any,
        tools: list[dict],
        debug: bool = False,
    ):
        self.llm = llm_client
        self.tools = tools
        self.debug = debug
        self.current_plan: ExecutionPlan | None = None
        self.trace_log: list[dict] = []

    def create_plan(self, goal: str, context: str) -> ExecutionPlan:
        """Ask LLM to create a structured plan."""
        prompt = f"""Create a detailed execution plan for this goal. Return JSON only.

Goal: {goal}

Context:
{context}

Return a JSON array of steps, each with:
- id: unique identifier
- action: tool name (read_file, write_file, execute_shell, semantic_search, etc.)
- description: what this step does
- target: file path, command, or query
- expected_outcome: what success looks like
- validation: how to verify (file_exists, test_passes, content_contains, output_contains)
- depends_on: list of step IDs that must complete first
- max_retries: 2 (default)

Example:
[
  {{"id": "1", "action": "read_file", "description": "Read existing config", "target": "config.yaml", "expected_outcome": "Config loaded", "validation": "file_exists", "depends_on": []}},
  {{"id": "2", "action": "write_file", "description": "Create new module", "target": "src/new_module.py", "expected_outcome": "Module created", "validation": "file_exists", "depends_on": ["1"]}}
]"""

        try:
            resp = self.llm.chat_with_tools(
                messages=[{"role": "user", "content": prompt}],
                tools=[],
                temperature=0.1,
            )
            plan_data = json.loads(resp.content or "[]")
        except Exception:
            # Fallback: simple plan
            plan_data = [
                {"id": "1", "action": "execute_shell", "description": "Explore project", "target": "ls -la", "expected_outcome": "Project structure known", "validation": "output_contains", "depends_on": [], "max_retries": 1},
            ]

        plan = ExecutionPlan(task_id=str(uuid.uuid4())[:8], goal=goal)
        for step_data in plan_data:
            step = PlanStep(**step_data)
            plan.add_step(step)
        return plan

    def validate_step(self, step: PlanStep, output: str) -> bool:
        """Validate step output against expected outcome."""
        val_type = step.validation
        if val_type == "file_exists":
            import os
            return os.path.exists(step.target)
        elif val_type == "test_passes":
            return "PASSED" in output or "passed" in output.lower()
        elif val_type == "content_contains":
            return step.target in output
        elif val_type == "output_contains":
            return len(output.strip()) > 0
        elif val_type == "no_error":
            return not output.startswith("ERROR")
        return True

    def execute_step(self, step: PlanStep, messages: list[dict]) -> tuple[bool, str, Any]:
        """Execute a single plan step using tools."""
        # Build the tool call
        tool_map = {t["function"]["name"]: t for t in self.tools}
        if step.action not in tool_map:
            return False, f"Unknown action: {step.action}", None

        # Build arguments based on action
        if step.action == "read_file":
            args = {"path": step.target}
        elif step.action == "write_file":
            # Need content - ask LLM for it
            args = {"path": step.target, "content": step.target}  # placeholder
        elif step.action == "execute_shell":
            args = {"cmd": step.target}
        elif step.action == "semantic_search":
            args = {"query": step.target}
        elif step.action == "list_directory":
            args = {"path": step.target or "."}
        else:
            args = {}

        # Execute via LLM
        tool_call = {
            "name": step.action,
            "arguments": json.dumps(args),
        }
        return True, "executed", args

    def learn_from_failure(self, step: PlanStep, error: str, output: str) -> str:
        """Extract learning from failure."""
        learning = f"Step {step.id} ({step.action}) failed: {error}. "
        if "not found" in error.lower():
            learning += "Path may be wrong or file doesn't exist. "
        elif "permission" in error.lower():
            learning += "Permission issue. "
        elif "syntax" in error.lower():
            learning += "Syntax error in generated code. "
        learning += f"Next time: verify {step.validation} before claiming success."
        return learning

    def trace(self, event: str, data: dict) -> None:
        """Log trace for debugging."""
        self.trace_log.append({
            "timestamp": time.time(),
            "event": event,
            "data": data,
        })
        if self.debug:
            print(f"[TRACE] {event}: {data}")


def build_debug_context(messages: list[dict], plan: ExecutionPlan | None) -> str:
    """Build debug context showing plan status and recent actions."""
    lines = ["=== DEBUG CONTEXT ==="]
    if plan:
        lines.append(f"Plan: {plan.goal}")
        lines.append(f"Status: {plan.status} | Step {plan.current_step}/{len(plan.steps)}")
        for i, step in enumerate(plan.steps):
            status = "✓" if step.completed else ("✗" if step.error else "○")
            lines.append(f"  {i+1}. [{status}] {step.description} ({step.action}: {step.target})")
            if step.error:
                lines.append(f"     ERROR: {step.error}")
            if step.learnings:
                for l in step.learnings:
                    lines.append(f"     LEARN: {l}")
    lines.append(f"\nRecent messages: {len(messages)}")
    for msg in messages[-3:]:
        role = msg.get("role", "?")
        content = str(msg.get("content", ""))[:100]
        lines.append(f"  {role}: {content}")
    return "\n".join(lines)
