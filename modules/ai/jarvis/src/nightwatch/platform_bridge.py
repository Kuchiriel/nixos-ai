"""
Platform Bridge — connects nightwatch harness to the agent platform.

This module allows nightwatch to use:
- Workspace discovery for multi-project support
- Persona selection for task assignment
- Orchestrator for task decomposition
- Model policy for model routing

It does NOT replace the existing nightwatch harness.
It extends it with platform capabilities.
"""

import json
import os
from pathlib import Path
from typing import Optional


def discover_projects_for_nightwatch(workspace_root: str = None) -> list[dict]:
    """Discover projects using the workspace module.

    Returns a list of project dicts compatible with nightwatch's
    project configuration.
    """
    try:
        from jarvis.core.workspace import WorkspaceDiscovery
        ws = WorkspaceDiscovery(workspace_root)
        ws.discover()
        ws.save()

        projects = []
        for pid, info in ws._projects.items():
            projects.append({
                "name": pid,
                "path": str(ws.workspace_root / info.manifest.path),
                "type": info.manifest.type,
                "language": info.manifest.language,
                "has_git": info.has_git,
                "has_agents_md": info.has_agents_md,
                "file_count": info.file_count,
                "dependencies": ws._dependency_graph.get(pid, []),
            })

        return projects
    except Exception:
        return []


def select_persona_for_task(task_description: str) -> dict:
    """Select the best persona for a task using the persona registry.

    Returns a dict with persona info that nightwatch can use.
    """
    try:
        from jarvis.core.persona import PersonaRegistry
        reg = PersonaRegistry()
        persona = reg.select_for_task(task_description)
        return persona.to_dict()
    except Exception:
        return {"id": "backend_engineer", "name": "Backend Engineer"}


def decompose_task_for_nightwatch(
    task_description: str,
    project_id: str = "nixos-ai",
) -> list[dict]:
    """Decompose a task into subtasks using the orchestrator.

    Returns a list of work item dicts.
    """
    try:
        from jarvis.core.orchestrator import Orchestrator
        orch = Orchestrator()
        items = orch.decompose_task(task_description, project_id=project_id)
        return [item.to_dict() for item in items]
    except Exception:
        return []


def get_model_tier_for_stage(stage: str) -> dict:
    """Get the recommended model tier for a workflow stage.

    Returns tier info that can be used to select the right model.
    """
    try:
        from jarvis.core.model_policy import ModelPolicy
        policy = ModelPolicy()
        tier = policy.select_tier(stage)
        return tier.to_dict()
    except Exception:
        return {"tier": "medium", "model_name": "unknown"}


def get_affected_projects(changed_files: list[str]) -> list[str]:
    """Determine which projects are affected by file changes.

    Uses workspace dependency graph to find transitive impacts.
    """
    try:
        from jarvis.core.workspace import WorkspaceDiscovery
        ws = WorkspaceDiscovery()
        if not ws._projects:
            ws.discover()
        return ws.get_affected_projects(changed_files)
    except Exception:
        return []


def log_task_execution(
    task_id: str,
    persona: str,
    model_tier: str,
    project: str,
    status: str,
    duration_seconds: float = 0,
    tokens_used: int = 0,
    error: str = "",
    state_dir: str = None,
):
    """Log task execution for observability.

    Writes to a structured JSONL log that can be queried later.
    """
    if state_dir:
        log_dir = Path(state_dir)
    else:
        log_dir = Path(os.path.expanduser("~/.local/state/jarvis/orchestrator"))
    log_dir.mkdir(parents=True, exist_ok=True)
    log_file = log_dir / "task-execution.jsonl"

    entry = {
        "task_id": task_id,
        "persona": persona,
        "model_tier": model_tier,
        "project": project,
        "status": status,
        "duration_seconds": duration_seconds,
        "tokens_used": tokens_used,
        "error": error,
    }

    with open(log_file, "a") as f:
        f.write(json.dumps(entry, default=str) + "\n")


def get_execution_stats(state_dir: str = None) -> dict:
    """Get execution statistics from the task execution log."""
    if state_dir:
        log_file = Path(state_dir) / "task-execution.jsonl"
    else:
        log_file = Path(os.path.expanduser("~/.local/state/jarvis/orchestrator/task-execution.jsonl"))

    if not log_file.exists():
        return {"total": 0, "by_status": {}, "by_persona": {}, "by_project": {}}

    entries = []
    for line in log_file.read_text().splitlines():
        if line.strip():
            try:
                entries.append(json.loads(line))
            except Exception:
                continue

    by_status = {}
    by_persona = {}
    by_project = {}
    total_duration = 0

    for entry in entries:
        status = entry.get("status", "unknown")
        by_status[status] = by_status.get(status, 0) + 1

        persona = entry.get("persona", "unknown")
        by_persona[persona] = by_persona.get(persona, 0) + 1

        project = entry.get("project", "unknown")
        by_project[project] = by_project.get(project, 0) + 1

        total_duration += entry.get("duration_seconds", 0)

    return {
        "total": len(entries),
        "by_status": by_status,
        "by_persona": by_persona,
        "by_project": by_project,
        "total_duration_seconds": total_duration,
        "avg_duration_seconds": total_duration / len(entries) if entries else 0,
    }
