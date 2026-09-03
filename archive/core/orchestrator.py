# PAUSADO — nightwatch/harness.py ja resolve isso (task_queue+safety+checkpoint).
# Ver decisao de consolidacao de 2026-08-31.
# Nao construir em cima disso sem revisar nightwatch/ primeiro.

"""
Orchestrator — Supervisor/subagent dispatch for multi-persona workflows.

Coordinates task decomposition, agent delegation, progress tracking,
and conflict resolution.

Based on Augment Code's Coordinator/Specialist/Verifier pattern
and OpenDev's dual-agent architecture.
"""

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from .persona import Persona, PersonaRegistry
from .workspace import WorkspaceDiscovery
from .workitem import WorkItem, WorkItemEngine, WorkItemStatus
from .model_policy import ModelPolicy
from .evidence import EvidenceCollector, TaskEvidence


@dataclass
class AgentInstance:
    """A running agent instance."""
    id: str
    persona: Persona
    project: str
    current_task: str = ""
    status: str = "idle"  # idle, working, waiting, error
    started_at: str = ""
    last_activity: str = ""
    tasks_completed: int = 0
    errors: int = 0

    def to_dict(self):
        return {
            "id": self.id,
            "persona": self.persona.id,
            "project": self.project,
            "current_task": self.current_task,
            "status": self.status,
            "started_at": self.started_at,
            "last_activity": self.last_activity,
            "tasks_completed": self.tasks_completed,
            "errors": self.errors,
        }


@dataclass
class WorkflowDefinition:
    """A declarative workflow."""
    id: str
    name: str
    description: str
    stages: list  # list of stage definitions
    persona_requirements: dict = field(default_factory=dict)  # stage -> persona tag
    max_parallel: int = 1
    timeout_minutes: int = 60

    def to_dict(self):
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "stages": self.stages,
            "persona_requirements": self.persona_requirements,
            "max_parallel": self.max_parallel,
            "timeout_minutes": self.timeout_minutes,
        }


# Built-in workflows
BUILTIN_WORKFLOWS = {
    "feature-development": WorkflowDefinition(
        id="feature-development",
        name="Feature Development",
        description="Full feature lifecycle: research → plan → implement → test → review → document",
        stages=[
            {"name": "research", "description": "Research the feature requirements and alternatives"},
            {"name": "planning", "description": "Create implementation plan with task decomposition"},
            {"name": "implementation", "description": "Implement the feature"},
            {"name": "testing", "description": "Write and run tests"},
            {"name": "review", "description": "Code review and quality check"},
            {"name": "documentation", "description": "Update docs and changelog"},
        ],
        persona_requirements={
            "research": "researcher",
            "planning": "architect",
            "implementation": "backend_engineer",
            "testing": "qa_engineer",
            "review": "architect",
            "documentation": "technical_writer",
        },
    ),
    "bugfix": WorkflowDefinition(
        id="bugfix",
        name="Bug Fix",
        description="Bug lifecycle: reproduce → diagnose → patch → regression test → review",
        stages=[
            {"name": "reproduce", "description": "Reproduce the bug"},
            {"name": "diagnose", "description": "Find root cause"},
            {"name": "patch", "description": "Implement fix"},
            {"name": "regression-test", "description": "Verify fix and check for regressions"},
            {"name": "review", "description": "Review the fix"},
        ],
        persona_requirements={
            "reproduce": "qa_engineer",
            "diagnose": "backend_engineer",
            "patch": "backend_engineer",
            "regression-test": "qa_engineer",
            "review": "architect",
        },
    ),
    "architecture-review": WorkflowDefinition(
        id="architecture-review",
        name="Architecture Review",
        description="Architecture review: audit → analyze → document → decide",
        stages=[
            {"name": "audit", "description": "Audit current architecture"},
            {"name": "analyze", "description": "Analyze gaps and improvements"},
            {"name": "document", "description": "Write findings and ADRs"},
            {"name": "decide", "description": "Make architectural decisions"},
        ],
        persona_requirements={
            "audit": "architect",
            "analyze": "researcher",
            "document": "technical_writer",
            "decide": "cto",
        },
    ),
    "overnight-maintenance": WorkflowDefinition(
        id="overnight-maintenance",
        name="Overnight Maintenance",
        description="Autonomous maintenance: discover → prioritize → fix → validate → commit",
        stages=[
            {"name": "discover", "description": "Discover tasks and issues"},
            {"name": "prioritize", "description": "Prioritize by impact and risk"},
            {"name": "fix", "description": "Implement fixes"},
            {"name": "validate", "description": "Run tests and validation"},
            {"name": "commit", "description": "Commit changes"},
        ],
        persona_requirements={
            "discover": "supervisor",
            "prioritize": "supervisor",
            "fix": "backend_engineer",
            "validate": "qa_engineer",
            "commit": "devops_engineer",
        },
        timeout_minutes=480,  # 8 hours
    ),
}


class Orchestrator:
    """Coordinates agents, tasks, and workflows."""

    def __init__(
        self,
        persona_registry: PersonaRegistry = None,
        workspace: WorkspaceDiscovery = None,
        work_engine: WorkItemEngine = None,
        model_policy: ModelPolicy = None,
        state_dir: str = None,
    ):
        self.personas = persona_registry or PersonaRegistry()
        self.workspace = workspace or WorkspaceDiscovery()
        if work_engine:
            self.work_engine = work_engine
        else:
            # Use state_dir if provided, otherwise default
            work_state = str(Path(state_dir) / "work") if state_dir else None
            self.work_engine = WorkItemEngine(work_state)
        self.model_policy = model_policy or ModelPolicy()
        evidence_state = str(Path(state_dir) / "evidence") if state_dir else None
        self.evidence = EvidenceCollector(evidence_state)
        self._workflows = dict(BUILTIN_WORKFLOWS)
        self._active_agents: dict[str, AgentInstance] = {}
        self._execution_log: list[dict] = []
        if state_dir:
            self._state_dir = Path(state_dir)
        else:
            self._state_dir = Path(os.path.expanduser("~/.local/state/jarvis/orchestrator"))
        self._state_dir.mkdir(parents=True, exist_ok=True)

    def decompose_task(
        self,
        task_description: str,
        project_id: str = None,
        workflow_id: str = None,
    ) -> list[WorkItem]:
        """Decompose a high-level task into work items.

        This creates work items based on the selected workflow's stages.
        The LLM should call this and then fill in specific details.
        """
        # Select workflow
        if workflow_id and workflow_id in self._workflows:
            workflow = self._workflows[workflow_id]
        else:
            workflow = self._select_workflow(task_description)

        items = []
        for stage in workflow.stages:
            # Select persona for this stage
            persona_tag = workflow.persona_requirements.get(stage["name"], "backend_engineer")
            persona = self.personas.select_for_task(stage["name"])

            # Select model tier for this stage
            model_tier = self.model_policy.select_tier(stage["name"])

            item = self.work_engine.create(
                project=project_id or "unknown",
                type="task",
                title=f"{stage['name']}: {task_description}",
                description=stage["description"],
                priority="medium",
                status="backlog",
                persona=persona.id,
                tags=[stage["name"], workflow.id, f"model:{model_tier.tier}"],
            )
            items.append(item)

        # Set up dependencies (stages depend on previous stages)
        for i in range(1, len(items)):
            items[i].dependencies = [items[i - 1].id]
            self.work_engine.update(items[i].id, dependencies=items[i].dependencies)

        self._log_event("decompose", {
            "task": task_description,
            "workflow": workflow.id,
            "items_created": len(items),
        })

        return items

    def _select_workflow(self, task_description: str) -> WorkflowDefinition:
        """Select the best workflow for a task."""
        desc_lower = task_description.lower()

        if any(w in desc_lower for w in ["bug", "fix", "error", "broken"]):
            return self._workflows["bugfix"]
        elif any(w in desc_lower for w in ["review", "audit", "architecture"]):
            return self._workflows["architecture-review"]
        elif any(w in desc_lower for w in ["overnight", "maintain", "clean"]):
            return self._workflows["overnight-maintenance"]
        else:
            return self._workflows["feature-development"]

    def select_persona(
        self,
        task_description: str,
        project_type: str = "",
    ) -> Persona:
        """Select the best persona for a task."""
        return self.personas.select_for_task(task_description, project_type)

    def assign_task(self, item_id: str, persona_id: str = None) -> Optional[AgentInstance]:
        """Assign a task to an agent with a persona."""
        item = self.work_engine.get(item_id)
        if not item:
            return None

        if not persona_id:
            persona = self.select_persona(item.title + " " + item.description)
        else:
            persona = self.personas.get(persona_id)

        if not persona:
            return None

        # Create agent instance
        agent_id = f"agent-{item.id}"
        agent = AgentInstance(
            id=agent_id,
            persona=persona,
            project=item.project,
            current_task=item_id,
            status="working",
            started_at=datetime.now(timezone.utc).isoformat(),
            last_activity=datetime.now(timezone.utc).isoformat(),
        )
        self._active_agents[agent_id] = agent

        # Update work item
        self.work_engine.transition(item_id, "in_progress", f"Assigned to {persona.name}")
        self.work_engine.update(item_id, persona=persona.id, agent=agent_id)

        self._log_event("assign", {
            "item": item_id,
            "persona": persona.id,
            "agent": agent_id,
        })

        return agent

    def complete_task(self, item_id: str, artifacts: list = None, commits: list = None):
        """Mark a task as complete with evidence collection."""
        item = self.work_engine.get(item_id)
        if not item:
            return

        if artifacts:
            for a in artifacts:
                item.add_artifact(a)
        if commits:
            for c in commits:
                item.add_commit(c)

        self.work_engine.transition(item_id, "done", "Task completed")

        # Collect evidence
        try:
            evidence = self.evidence.start_task(item_id, item.title, item.project)
            evidence.persona = item.persona
            evidence.model_tier = item.model_tier if hasattr(item, 'model_tier') else ""
            if artifacts:
                self.evidence.add_code_change(evidence, artifacts)
            if commits:
                self.evidence.add_validation(evidence, "git commit", f"Commit: {commits[-1]}", True)
            self.evidence.complete_task(evidence)
        except Exception:
            pass

        # Update agent
        for agent in self._active_agents.values():
            if agent.current_task == item_id:
                agent.status = "idle"
                agent.current_task = ""
                agent.tasks_completed += 1

        self._log_event("complete", {"item": item_id})

    def fail_task(self, item_id: str, error: str):
        """Mark a task as failed."""
        item = self.work_engine.get(item_id)
        if not item:
            return

        item.record_error(error)

        if item.attempts >= item.max_attempts:
            self.work_engine.transition(item_id, "blocked", f"Max attempts reached: {error}")
        else:
            self.work_engine.transition(item_id, "backlog", f"Failed (attempt {item.attempts}): {error}")

        # Update agent
        for agent in self._active_agents.values():
            if agent.current_task == item_id:
                agent.status = "error"
                agent.errors += 1

        self._log_event("fail", {"item": item_id, "error": error, "attempts": item.attempts})

    def get_next_action(self) -> Optional[dict]:
        """Get the next action to take (task + persona + agent)."""
        item = self.work_engine.get_next_task()
        if not item:
            return None

        persona = self.select_persona(item.title + " " + item.description)

        return {
            "item": item.to_dict(),
            "persona": persona.to_dict() if persona else None,
            "project_context": self.workspace.get_project_context(item.project),
        }

    def get_status(self) -> dict:
        """Get overall orchestration status."""
        return {
            "active_agents": len(self._active_agents),
            "agents": {aid: a.to_dict() for aid, a in self._active_agents.items()},
            "work_items": self.work_engine.get_burndown(),
            "wip": self.work_engine.check_wip_limits(),
            "recent_events": self._execution_log[-10:],
        }

    def _log_event(self, event_type: str, data: dict):
        """Log an orchestration event."""
        event = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **data,
        }
        self._execution_log.append(event)

        # Persist to disk
        log_file = self._state_dir / "events.jsonl"
        with open(log_file, "a") as f:
            f.write(json.dumps(event, default=str) + "\n")

    def save(self):
        """Save orchestrator state."""
        state = {
            "active_agents": {aid: a.to_dict() for aid, a in self._active_agents.items()},
            "execution_log": self._execution_log[-100:],  # keep last 100
        }
        with open(self._state_dir / "state.json", "w") as f:
            json.dump(state, f, indent=2, default=str)

    def load(self):
        """Load orchestrator state."""
        state_file = self._state_dir / "state.json"
        if state_file.exists():
            try:
                with open(state_file) as f:
                    state = json.load(f)
                # Restore execution log
                self._execution_log = state.get("execution_log", [])
            except Exception:
                pass

    def summary(self) -> str:
        """Human-readable summary."""
        status = self.get_status()
        lines = [
            f"Orchestrator Status:",
            f"  Active agents: {status['active_agents']}",
            f"  Work items: {status['work_items']['total']} total, "
            f"{status['work_items']['done']} done, "
            f"{status['work_items']['in_progress']} in progress",
        ]

        if status["wip"]["violations"]:
            lines.append("  ⚠️ WIP violations!")

        for aid, agent_info in status["agents"].items():
            lines.append(
                f"  Agent {aid}: {agent_info['persona']} "
                f"({agent_info['status']}) "
                f"task={agent_info['current_task']}"
            )

        return "\n".join(lines)
