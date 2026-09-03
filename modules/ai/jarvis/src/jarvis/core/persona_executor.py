"""
Persona Executor — bridges orchestrator personas to harness execution.

This module connects:
  PersonaRegistry (who)
  → Orchestrator (what task)
  → Harness (how to execute)
  → LLMClient (real LLM calls)
  → ToolExecutor (file operations)

Usage:
    executor = PersonaExecutor(project="Corretor")
    result = executor.execute_with_persona(
        task="Add type hints to correct()",
        persona_id="backend_engineer",
    )
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Optional

from jarvis.core.persona import Persona, PersonaRegistry
from jarvis.core.orchestrator import Orchestrator, WorkItem, AgentInstance


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
    """Executes tasks using personas through the harness pipeline."""

    def __init__(self, project: str = "nixos-ai"):
        self.project = project
        self.registry = PersonaRegistry()
        self.orchestrator = Orchestrator()
        self._harness = None

    def _get_harness(self):
        """Lazy-load harness to avoid circular imports."""
        if self._harness is None:
            import os
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

        # 2. Create work item
        item = self.orchestrator.work_engine.create(
            title=task,
            description=task,
            project=project,
        )

        # 3. Assign to agent
        agent = self.orchestrator.assign_task(item.id, persona.id)
        if not agent:
            return ExecutionResult(
                success=False,
                persona_id=persona.id,
                task_id=item.id,
                message="Failed to assign task",
                error="Orchestrator could not create agent",
            )

        # 4. Execute via harness (if available)
        try:
            from nightwatch.task_queue import Task, TaskStatus
            
            # Create a Task for the harness
            # Auto-detect target files from project
            target_files = []
            import os
            project_path = f"/home/nixos/projects/{project}"
            if os.path.exists(project_path):
                for f in os.listdir(project_path):
                    if f.endswith('.py') and not f.startswith('.'):
                        target_files.append(f)
            
            harness_task = Task(
                id=item.id,
                project=project,
                description=task,
                priority=5,
                risk="low",
                target_files=target_files[:5],  # Limit to 5 files
                acceptance_criteria=task,
                repository=project_path,
                language="python",
            )
            
            # Add task to queue so harness can track state transitions
            harness = self._get_harness()
            harness.queue.add_task(harness_task)
            
            # Execute through harness pipeline
            success = harness.execute_task(harness_task)
            
            duration = time.time() - start_time
            
            if success:
                agent.tasks_completed += 1
                agent.status = "idle"
                self.orchestrator.complete_task(item.id, f"Completed by {persona.id}")
                
                return ExecutionResult(
                    success=True,
                    persona_id=persona.id,
                    task_id=item.id,
                    message=f"Task completed by {persona.name}",
                    files_changed=harness_task.target_files,
                    commit_sha=harness_task.commit_sha,
                    duration_seconds=duration,
                )
            else:
                agent.errors += 1
                agent.status = "error"
                self.orchestrator.fail_task(item.id, harness_task.last_error or "Execution failed")
                
                return ExecutionResult(
                    success=False,
                    persona_id=persona.id,
                    task_id=item.id,
                    message=f"Task failed: {harness_task.last_error}",
                    error=harness_task.last_error,
                    duration_seconds=duration,
                )
                
        except Exception as e:
            duration = time.time() - start_time
            agent.errors += 1
            agent.status = "error"
            
            return ExecutionResult(
                success=False,
                persona_id=persona.id,
                task_id=item.id,
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
            f"  Orchestrator items: {len(self.orchestrator.work_engine.list_items())}",
        ]
        return "\n".join(lines)
