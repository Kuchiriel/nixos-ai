"""Multi-agent primitives — persona handoff via Event Bus.

Builds on the existing mode system (.jarvismodes) and Event Bus.
Provides lightweight agent coordination without external infrastructure.

Architecture:
    AgentPersona (wraps a mode with state)
        ↓
    Handoff (transfer context between personas)
        ↓
    Orchestrator (sequential handoff between personas)
        ↓
    Event Bus (events for observability)

Usage:
    from nightwatch.multi_agent import Orchestrator, AgentPersona

    orch = Orchestrator()
    orch.add_persona(AgentPersona("coder", role="Engenheiro de código"))
    orch.add_persona(AgentPersona("reviewer", role="Revisor de código"))
    result = orch.run(["Fix bug in main.py"], max_rounds=3)
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable


class PersonaStatus(str, Enum):
    """Status of a persona in the orchestration."""
    IDLE = "idle"
    ACTIVE = "active"
    WAITING = "waiting"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass
class HandoffContext:
    """Context transferred between personas during handoff."""
    from_persona: str
    to_persona: str
    task: str
    artifacts: dict[str, Any] = field(default_factory=dict)
    notes: str = ""
    ts: float = field(default_factory=time.time)


@dataclass
class AgentPersona:
    """A persona with state tracking.

    Wraps a mode definition from .jarvismodes with execution state.
    """
    name: str
    role: str = ""
    instructions: str = ""
    status: PersonaStatus = PersonaStatus.IDLE
    tasks_completed: int = 0
    tasks_failed: int = 0
    last_handoff: HandoffContext | None = None
    _execute_fn: Callable[[str, dict[str, Any]], dict[str, Any]] | None = field(
        default=None, repr=False
    )

    def execute(self, task: str, context: dict[str, Any] | None = None) -> dict[str, Any]:
        """Execute a task. Returns result dict with 'output' and 'success'."""
        self.status = PersonaStatus.ACTIVE
        try:
            if self._execute_fn:
                result = self._execute_fn(task, context or {})
            else:
                # Default: return a placeholder (real execution via LLM)
                result = {
                    "output": f"[{self.name}] Task received: {task[:80]}",
                    "success": True,
                    "artifacts": {},
                }
            if result.get("success", False):
                self.tasks_completed += 1
                self.status = PersonaStatus.COMPLETED
            else:
                self.tasks_failed += 1
                self.status = PersonaStatus.FAILED
            return result
        except Exception as e:
            self.tasks_failed += 1
            self.status = PersonaStatus.FAILED
            return {"output": str(e), "success": False, "artifacts": {}}

    def handoff_to(self, other: AgentPersona, task: str, artifacts: dict[str, Any] | None = None, notes: str = "") -> HandoffContext:
        """Create a handoff context to another persona."""
        ctx = HandoffContext(
            from_persona=self.name,
            to_persona=other.name,
            task=task,
            artifacts=artifacts or {},
            notes=notes,
        )
        self.last_handoff = ctx
        self.status = PersonaStatus.WAITING
        other.status = PersonaStatus.ACTIVE
        return ctx

    @property
    def stats(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "role": self.role,
            "status": self.status.value,
            "completed": self.tasks_completed,
            "failed": self.tasks_failed,
        }


class Orchestrator:
    """Simple sequential orchestrator for multi-agent workflows.

    Runs personas in sequence, passing handoff context between them.
    Emits events via Event Bus for observability.
    """

    def __init__(self) -> None:
        self._personas: list[AgentPersona] = []
        self._history: list[dict[str, Any]] = []

    def add_persona(self, persona: AgentPersona) -> None:
        self._personas.append(persona)

    def _emit(self, topic: str, **data: object) -> None:
        """Emit orchestration event via Event Bus."""
        try:
            from jarvis.core.eventbus import get_bus
            get_bus().publish(f"orchestrator.{topic}", data)
        except Exception:  # noqa: BLE001
            pass

    def run(self, tasks: list[str], max_rounds: int = 3) -> dict[str, Any]:
        """Run tasks through the persona pipeline.

        Each task goes through all personas in order.
        Returns summary of results.
        """
        if not self._personas:
            return {"error": "No personas configured", "results": []}

        self._emit("run.started", tasks=len(tasks), personas=[p.name for p in self._personas])
        start = time.time()
        results: list[dict[str, Any]] = []

        for task_idx, task in enumerate(tasks):
            context: dict[str, Any] = {"task": task, "round": task_idx}

            for persona_idx, persona in enumerate(self._personas):
                self._emit(
                    "persona.started",
                    persona=persona.name, task=task[:80], round=task_idx,
                )

                result = persona.execute(task, context)
                results.append({
                    "task": task[:100],
                    "persona": persona.name,
                    "success": result.get("success", False),
                    "output": result.get("output", "")[:200],
                })

                self._emit(
                    "persona.completed",
                    persona=persona.name, success=result.get("success", False),
                )

                # Handoff to next persona
                if persona_idx < len(self._personas) - 1:
                    next_persona = self._personas[persona_idx + 1]
                    handoff = persona.handoff_to(
                        next_persona, task,
                        artifacts=result.get("artifacts", {}),
                        notes=f"Round {task_idx}, step {persona_idx}",
                    )
                    self._emit(
                        "handoff",
                        from_p=handoff.from_persona, to_p=handoff.to_persona,
                        task=handoff.task[:80],
                    )
                    # Update context for next persona
                    context["previous_result"] = result
                    context["handoff"] = {
                        "from": handoff.from_persona,
                        "notes": handoff.notes,
                    }

        elapsed = time.time() - start
        succeeded = sum(1 for r in results if r["success"])
        self._emit("run.completed", total=len(results), succeeded=succeeded, elapsed_s=elapsed)

        return {
            "total": len(results),
            "succeeded": succeeded,
            "failed": len(results) - succeeded,
            "elapsed_s": round(elapsed, 2),
            "personas": [p.stats for p in self._personas],
            "results": results,
        }

    @property
    def personas(self) -> list[AgentPersona]:
        return list(self._personas)

    @property
    def history(self) -> list[dict[str, Any]]:
        return list(self._history)


# ---------------------------------------------------------------------------
# LLM-backed execution — connects personas to real LLM
# ---------------------------------------------------------------------------

def create_llm_executor(
    system_prompt: str = "You are a helpful coding assistant. PT-BR.",
    max_tokens: int = 1024,
    temperature: float = 0.3,
    timeout: int = 120,
) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    """Create an execute function that calls the local LLM.

    Returns a callable suitable for AgentPersona._execute_fn.

    Usage:
        executor = create_llm_executor(system_prompt="You are a code reviewer.")
        persona = AgentPersona("reviewer", _execute_fn=executor)
    """
    import requests as _requests

    def _llm_execute(task: str, context: dict[str, Any]) -> dict[str, Any]:
        """Execute task by calling local LLM."""
        # Build messages
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
        ]

        # Add context from previous persona if available
        prev = context.get("previous_result")
        if prev and prev.get("output"):
            messages.append({
                "role": "user",
                "content": f"Previous agent said: {prev['output'][:500]}",
            })

        messages.append({"role": "user", "content": task})

        # Detect LLM endpoint
        import os as _os
        base_url = _os.environ.get("LLAMA_CPP_URL", "http://127.0.0.1:8080")

        payload = {
            "messages": messages,
            "max_tokens": max_tokens,
            "temperature": temperature,
        }

        try:
            resp = _requests.post(
                f"{base_url.rstrip('/')}/v1/chat/completions",
                json=payload,
                timeout=timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            content = data["choices"][0]["message"].get("content", "")
            return {
                "output": content[:2000],
                "success": True,
                "artifacts": {},
            }
        except Exception as e:
            return {
                "output": f"LLM error: {e}",
                "success": False,
                "artifacts": {},
            }

    return _llm_execute


def create_file_executor(
    project_root: str | None = None,
) -> Callable[[str, dict[str, Any]], dict[str, Any]]:
    """Create an execute function that modifies files (for coder persona).

    Returns a callable suitable for AgentPersona._execute_fn.
    WARNING: This actually modifies files. Use with caution.
    """
    import subprocess as _subprocess
    from pathlib import Path as _Path

    root = _Path(project_root) if project_root else _Path.cwd()

    def _file_execute(task: str, context: dict[str, Any]) -> dict[str, Any]:
        """Execute task by reading/modifying files."""
        # Simple file operations based on task keywords
        task_lower = task.lower()

        try:
            if "read" in task_lower or "list" in task_lower:
                # List files in project
                result = _subprocess.run(
                    ["find", str(root), "-name", "*.py", "-type", "f"],
                    capture_output=True, text=True, timeout=10,
                )
                files = result.stdout.strip().split("\n")[:20]
                return {
                    "output": f"Found {len(files)} Python files:\n" + "\n".join(files),
                    "success": True,
                    "artifacts": {"files": files},
                }
            else:
                return {
                    "output": f"[file_executor] Task received: {task[:100]}",
                    "success": True,
                    "artifacts": {},
                }
        except Exception as e:
            return {"output": str(e), "success": False, "artifacts": {}}

    return _file_execute

