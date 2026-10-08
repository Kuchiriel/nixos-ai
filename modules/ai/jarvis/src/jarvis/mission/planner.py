"""Planner — turns an objective into tasks with dependencies and personas.

Two layers, in this order (the first only applies if the second fails):

1. **LLM** (`decompose_with_llm`): asks for JSON tasks with depends_on,
   persona, and acceptance criteria. This is the good path — the model
   understands the objective.
2. **Deterministic** (`decompose_heuristic`): never fails. An objective with
   a cited path -> one task with a verifiable criterion. A generic
   objective -> ONE explanation task (the chat runtime resolves it). It
   does not invent 5 tasks to look "multi-task".

This matters because the alternative (always calling the LLM) drops the
mission whenever the model is down — and the rule is: simple objective =
simple task; multiple tasks only when there is real separable work.

On persona: selection uses `PersonaRegistry.select_for_task` (the canonical
mechanism, not a second heuristic), and the plan carries the persona so the
runner APPLIES it (prompt + model + tools) and records what was really used.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from jarvis.mission.models import AcceptanceCriterion, Mission, MissionTask
from jarvis.mission.projects import ResolvedProject, scoped_files
from jarvis.mission.verify import criteria_from_description


_LLM_SYSTEM = """You are a software task planner. Decompose the objective into
concrete, verifiable tasks. Reply with ONLY a JSON array, no prose.

Each task object:
  "title": short imperative title (<=70 chars)
  "description": what to do, concrete, mentioning exact paths when known
  "persona_id": one of ["backend_engineer","nixos_engineer","qa_engineer",
                        "security_engineer","researcher","architect",
                        "technical_writer","devops_engineer","jarvis"]
  "dependencies": array of indexes (0-based) of tasks that must finish first
  "priority": 1..10 (1 = highest)
  "acceptance": array of criteria:
      {"kind":"file_exists","target":"path","description":""}
      {"kind":"content_contains","target":"path","description":"needle"}
      {"kind":"test_passes","target":"","description":""}
      {"kind":"command_ok","target":"cmd","description":""}

RULES:
- 2 to 6 tasks. If there is no real sub-work, return a single task.
- Only cite paths that appear in the project listing given to you.
- Acceptance criteria MUST be checkable from the machine's point of view.
  Never restate the objective as a criterion.
- Dependencies must reference EARLIER indexes only (no cycles).
"""


def _parse_llm_json(text: str) -> list[dict[str, Any]]:
    """Extract the JSON array from the text. Tolerates ```json fences and prose."""
    t = (text or "").strip()
    if t.startswith("```"):
        t = re.sub(r"^```[a-zA-Z]*\n?", "", t)
        t = re.sub(r"```$", "", t).strip()
    start = t.find("[")
    if start < 0:
        return []
    depth = 0
    in_str = False
    esc = False
    for i in range(start, len(t)):
        c = t[i]
        if in_str:
            if esc:
                esc = False
            elif c == "\\":
                esc = True
            elif c == '"':
                in_str = False
            continue
        if c == '"':
            in_str = True
        elif c == "[":
            depth += 1
        elif c == "]":
            depth -= 1
            if depth == 0:
                try:
                    data = json.loads(t[start:i + 1])
                except json.JSONDecodeError:
                    return []
                if isinstance(data, list):
                    return [d for d in data if isinstance(d, dict)]
                return []
    return []


def _persona_for(description: str) -> str:
    try:
        from jarvis.core.persona import PersonaRegistry
        reg = PersonaRegistry()
        p = reg.select_for_task(description)
        return p.id if p else "jarvis"
    except Exception:
        return "jarvis"


_VALID_PERSONAS = {
    "backend_engineer", "nixos_engineer", "qa_engineer", "security_engineer",
    "researcher", "architect", "technical_writer", "devops_engineer",
    "jarvis", "cto", "supervisor", "forensic_audio_auditor", "agent",
    "uncensored", "marketing",
}


def _sanitize_persona(pid: Any, description: str) -> str:
    pid = str(pid or "").strip()
    if pid in _VALID_PERSONAS:
        return pid
    return _persona_for(description)


def decompose_heuristic(objective: str, project: ResolvedProject) -> list[MissionTask]:
    """Minimal, honest plan for an objective with no possible decomposition."""
    root = project.root
    files = scoped_files(root, objective) if project.ok else []
    crit = criteria_from_description(objective, expect_changes=bool(files))
    desc = objective.strip()
    if files:
        desc += "\n\nFiles in scope (derived from the objective):\n" + \
                "\n".join(f"  {f}" for f in files)
    return [MissionTask(
        id="t1",
        title=objective.strip()[:70] or "execute objective",
        project=project.name,
        project_root=str(root) if project.ok else "",
        description=desc,
        persona_id=_persona_for(objective),
        target_files=files,
        acceptance=crit,
        priority=5,
    )]


def decompose_with_llm(
    objective: str,
    project: ResolvedProject,
    *,
    chat: Callable[[list[dict], int], str] | None = None,
    known_files: list[str] | None = None,
    max_tasks: int = 6,
) -> list[MissionTask] | None:
    """Ask the LLM to decompose. None when unavailable/malformed.

    The caller then falls back to the heuristic.
    """
    if chat is None:
        return None
    files = known_files if known_files is not None else (
        scoped_files(project.root, objective) if project.ok else [])
    listing = "\n".join(f"  {f}" for f in files[:40]) or "  (no files identified)"
    prompt = (f"PROJECT: {project.name} ({project.root})\n\n"
              f"RELEVANT FILES IN THE PROJECT (cite these paths):\n{listing}\n\n"
              f"OBJECTIVE:\n{objective}\n\n"
              f"JSON array of tasks:")
    try:
        raw = chat([{"role": "system", "content": _LLM_SYSTEM},
                    {"role": "user", "content": prompt}], 2000)
    except Exception:
        return None
    items = _parse_llm_json(raw or "")
    if not items:
        return None
    items = items[:max_tasks]

    tasks: list[MissionTask] = []
    for i, it in enumerate(items):
        title = str(it.get("title") or f"task {i + 1}").strip()[:70]
        desc = str(it.get("description") or title).strip()
        pid = _sanitize_persona(it.get("persona_id"), desc)
        deps: list[str] = []
        for d in it.get("dependencies") or []:
            try:
                di = int(d)
            except (TypeError, ValueError):
                continue
            if 0 <= di < i and tasks and tasks[di].id not in deps:
                deps.append(tasks[di].id)
        acc: list[AcceptanceCriterion] = []
        for c in (it.get("acceptance") or []):
            if not isinstance(c, dict):
                continue
            kind = str(c.get("kind", "")).strip()
            if kind not in ("file_exists", "file_absent", "content_contains",
                            "test_passes", "command_ok", "diff_present",
                            "evidence_present"):
                continue
            tgt = str(c.get("target", "")).strip()
            needle = str(c.get("description", "")).strip()
            if kind in ("file_exists", "file_absent", "content_contains") and not tgt:
                continue
            if kind == "command_ok" and not tgt:
                tgt = "true"
            acc.append(AcceptanceCriterion(kind=kind, target=tgt,
                                           description=needle))
        # A task with no criterion is a task with no contract — it does not
        # enter as "verified".
        if not acc:
            acc = criteria_from_description(desc, expect_changes=bool(files))
        try:
            pri = max(1, min(10, int(it.get("priority", 5))))
        except (TypeError, ValueError):
            pri = 5
        tasks.append(MissionTask(
            id=f"t{i + 1}", title=title, project=project.name,
            project_root=str(project.root) if project.ok else "",
            description=desc, persona_id=pid, dependencies=deps,
            acceptance=acc, priority=pri,
            target_files=[f for f in files if f and f in desc],
        ))
    return tasks or None


def build_mission(
    objective: str,
    project: ResolvedProject,
    *,
    chat: Callable[[list[dict], int], str] | None = None,
    requested_by: str = "",
    telegram_chat_id: int | None = None,
    use_llm: bool = True,
) -> Mission:
    """Create the mission (ready to persist; does not execute)."""
    m = Mission(
        id=Mission.new_id(),
        objective=objective.strip(),
        project=project.name,
        project_root=str(project.root) if project.ok else "",
        requested_by=requested_by,
        telegram_chat_id=telegram_chat_id,
    )
    tasks = None
    if use_llm and chat is not None:
        tasks = decompose_with_llm(objective, project, chat=chat)
    if not tasks:
        tasks = decompose_heuristic(objective, project)
    m.tasks = tasks
    m.refresh_blocked()
    return m