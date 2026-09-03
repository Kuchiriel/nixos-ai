"""
Persona Executor — bridges personas to harness execution directly.

This module connects:
  PersonaRegistry (who)
  → Task Queue (what task)
  → Harness (how to execute)
  → LLMClient (real LLM calls)
  → ToolExecutor (file operations)

NO DEPENDENCY ON orchestrator.py or workitem.py (PAUSADO).

Usage:
    executor = PersonaExecutor(project="Corretor")
    result = executor.execute_with_persona(
        task="Add type hints to correct()",
        persona_id="backend_engineer",
    )
"""

from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from typing import Any, Optional

from jarvis.core.persona import Persona, PersonaRegistry


@dataclass
class ExecutionResult:
    """Result of a persona-executed task."""
    success: bool
    persona_id: str
    task_id: str
    message: str
    files_changed: list[str] = field(default_factory=list)
    commit_sha: str | None = None
    duration_seconds: float = 0.0
    error: str | None = None


class PersonaExecutor:
    """Executes tasks using personas through the harness pipeline.

    Directly uses:
    - PersonaRegistry for persona selection
    - Task Queue for task persistence
    - Harness for execution pipeline
    """

    def __init__(self, project: str = "nixos-ai"):
        self.project = project
        self.registry = PersonaRegistry()
        self._harness = None

    def _get_harness(self):
        """Lazy-load harness to avoid circular imports."""
        if self._harness is None:
            # Set project root for harness path resolution
            project_path = f"/home/nixos/projects/{self.project}"
            os.environ["JARVIS_PROJECT_ROOT"] = project_path

            from nightwatch.harness import Harness, HarnessConfig
            config = HarnessConfig(
                project=self.project,
                dry_run=False,
                max_retries=1,
            )
            self._harness = Harness(config=config)
        return self._harness

    def execute_with_persona(
        self,
        task: str,
        persona_id: str | None = None,
        project: str | None = None,
    ) -> ExecutionResult:
        """Execute a task using a specific persona.

        Args:
            task: Task description
            persona_id: Persona to use (auto-select if None)
            project: Project to work on (uses default if None)

        Returns:
            ExecutionResult with outcome
        """
        start_time = time.time()
        project = project or self.project

        # 1. Select persona
        if persona_id:
            persona = self.registry.get(persona_id)
        else:
            persona = self.registry.select_for_task(task)

        if not persona:
            return ExecutionResult(
                success=False,
                persona_id="unknown",
                task_id="",
                message="No persona selected",
                error="No matching persona found",
            )

        # 2. Create task in queue directly (no orchestrator)
        from nightwatch.task_queue import Task, TaskStatus

        task_id = f"pe-{int(time.time())}-{persona.id[:8]}"

        # Auto-detect target files from project
        target_files = []
        project_path = f"/home/nixos/projects/{project}"
        if os.path.exists(project_path):
            for f in os.listdir(project_path):
                if f.endswith('.py') and not f.startswith('.'):
                    target_files.append(f)

        harness_task = Task(
            id=task_id,
            project=project,
            description=task,
            priority=5,
            risk="low",
            target_files=target_files[:5],  # Limit to 5 files
            acceptance_criteria=task,
            repository=project_path,
            language="python",
        )

        # 3. Execute through harness pipeline
        try:
            harness = self._get_harness()
            harness.queue.add_task(harness_task)

            # Publish task_started event via global EventBus
            from jarvis.core.eventbus import get_bus
            get_bus().publish("harness.task", {
                "event_type": "task_started",
                "task_id": task_id,
                "description": task[:100],
                "persona": persona.id,
                "project": project,
            })

            success = harness.execute_task(harness_task)

            duration = time.time() - start_time

            if success:
                # Publish task_completed event
                get_bus().publish("harness.task", {
                    "event_type": "task_completed",
                    "task_id": task_id,
                    "commit": harness_task.commit_sha or "",
                    "files": harness_task.target_files,
                })

                return ExecutionResult(
                    success=True,
                    persona_id=persona.id,
                    task_id=task_id,
                    message=f"Task completed by {persona.name}",
                    files_changed=harness_task.target_files,
                    commit_sha=harness_task.commit_sha,
                    duration_seconds=duration,
                )
            else:
                # Publish task_failed event
                get_bus().publish("harness.task", {
                    "event_type": "task_failed",
                    "task_id": task_id,
                    "error": harness_task.last_error or "Execution failed",
                })

                return ExecutionResult(
                    success=False,
                    persona_id=persona.id,
                    task_id=task_id,
                    message=f"Task failed: {harness_task.last_error}",
                    error=harness_task.last_error,
                    duration_seconds=duration,
                )

        except Exception as e:
            duration = time.time() - start_time

            # Publish task_failed event
            try:
                from jarvis.core.eventbus import get_bus
                get_bus().publish("harness.task", {
                    "event_type": "task_failed",
                    "task_id": task_id,
                    "error": str(e)[:200],
                })
            except Exception:
                pass

            return ExecutionResult(
                success=False,
                persona_id=persona.id,
                task_id=task_id,
                message=f"Execution error: {str(e)}",
                error=str(e),
                duration_seconds=duration,
            )

    def execute_pipeline(
        self,
        tasks: list[dict[str, str]],
        project: str | None = None,
    ) -> list[ExecutionResult]:
        """Execute a pipeline of tasks with automatic persona selection.

        Args:
            tasks: List of {"task": "...", "persona": "optional"} dicts
            project: Project to work on

        Returns:
            List of ExecutionResults
        """
        results = []
        for task_def in tasks:
            result = self.execute_with_persona(
                task=task_def["task"],
                persona_id=task_def.get("persona"),
                project=project,
            )
            results.append(result)

            # Stop on failure if critical
            if not result.success and task_def.get("critical", False):
                break

        return results

    def summary(self) -> str:
        """Summary of executor state."""
        lines = [
            f"PersonaExecutor:",
            f"  Project: {self.project}",
            f"  Personas: {len(self.registry.list_all())}",
        ]
        return "\n".join(lines)
