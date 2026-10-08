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
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
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

    def __init__(self, project: str = "nixos-ai", dry_run: bool = False):
        self.project = project
        self.dry_run = dry_run
        try:
            from jarvis.core.config import get_config
            _pdir = get_config().personas_dir
        except Exception:
            _pdir = None
        self.registry = PersonaRegistry(personas_dir=_pdir)
        # Harness cache is keyed BY PROJECT. Before, `self._harness` was a
        # single slot built for `self.project` on first use, so
        # execute_with_persona(project="B") on an executor created for "A"
        # ran the harness rooted at A while reporting B — the "harness built
        # for a different project" failure.
        self._harnesses: dict[str, Any] = {}

    def _get_harness(self, project: str | None = None):
        """Lazy-load a harness per project to avoid circular imports."""
        project = project or self.project
        cached = self._harnesses.get(project)
        if cached is not None:
            return cached

        from jarvis.core.config import get_config
        from pathlib import Path
        import os as _os

        cfg = get_config()
        workspace = Path(_os.environ.get("JARVIS_WORKSPACE_ROOT",
                                         Path.home() / "projects"))
        project_path = workspace / project
        # Validate before building: a harness rooted at a path that does not
        # exist would silently fall back to nixos-ai inside find_repo_root.
        if not project_path.is_dir():
            raise FileNotFoundError(
                f"project directory not found for '{project}': {project_path}")
        from jarvis.core.paths import set_project_root
        set_project_root(project_path)

        from nightwatch.harness import Harness, HarnessConfig
        config = HarnessConfig(
            project=project,
            dry_run=self.dry_run,
            max_retries=1,
        )
        harness = Harness(config=config)
        self._harnesses[project] = harness
        return harness

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

        # Scope the task to the REQUESTED project. Uses the project's real
        # structure (cited paths / matching files), never a root-level "*.py"
        # listing, and never a directory outside the project.
        from jarvis.mission.projects import project_root_for, scoped_files
        target_files: list[str] = []
        repository = ""
        try:
            root = project_root_for(project)
            repository = str(root)
            target_files = scoped_files(root, task, limit=5)
        except FileNotFoundError:
            # Unknown project: fail closed instead of guessing a repo.
            return ExecutionResult(
                success=False,
                persona_id=persona.id,
                task_id=task_id,
                message=f"project not found: {project}",
                error=f"project not found: {project}",
                duration_seconds=time.time() - start_time,
            )

        # Acceptance criteria must be checkable, not the objective restated.
        from jarvis.mission.verify import criteria_from_description
        acceptance = criteria_from_description(task, expect_changes=True)

        harness_task = Task(
            id=task_id,
            project=project,
            description=task,
            priority=5,
            risk="low",
            target_files=target_files[:5],
            acceptance_criteria="; ".join(
                f"{c.kind}:{c.target or '-'}" for c in acceptance),
            repository=repository,
            language="python",
        )

        # 3. Execute through harness pipeline, scoped to THIS project
        try:
            harness = self._get_harness(project)
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

            # Snapshot BEFORE execution so attribution is this task's work,
            # not everything already dirty in the tree.
            from jarvis.mission.verify import take_snapshot as _snap
            before = _snap(repository)

            success = harness.execute_task(harness_task)

            duration = time.time() - start_time

            # Changed files = diff between the two snapshots. Running
            # `git diff --name-only HEAD` here attributed every pre-existing
            # or foreign modification to this task.
            after = _snap(repository)
            actual_files_changed: list[str] = before.changed_paths(after)

            if success:
                # Publish task_completed event
                get_bus().publish("harness.task", {
                    "event_type": "task_completed",
                    "task_id": task_id,
                    "commit": harness_task.commit_sha or "",
                    "files": actual_files_changed or harness_task.target_files,
                })

                return ExecutionResult(
                    success=True,
                    persona_id=persona.id,
                    task_id=task_id,
                    message=f"Task completed by {persona.name}",
                    files_changed=actual_files_changed or harness_task.target_files,
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
            except Exception as pub_err:
                import logging
                logging.getLogger(__name__).warning(
                    "Failed to publish task_failed event: %s", pub_err
                )

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
