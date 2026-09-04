"""Memory Bridge — Connect nightwatch progress.jsonl to episodic memory.

Reads past task outcomes from progress.jsonl and stores failures/lessons
in the Qdrant episodic memory so future sessions can recall them via RAG.

This is the critical link that makes the harness learn from mistakes:
progress.jsonl → memory_bridge → episodic_memory (Qdrant) → recall in future sessions
"""

from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any


# Progress log location (must match harness.py)
STATE_DIR = Path.home() / ".local/state/jarvis/nightwatch"
PROGRESS_LOG = STATE_DIR / "progress.jsonl"


def load_progress_entries(
    project: str | None = None,
    limit: int = 100,
    event_types: list[str] | None = None,
) -> list[dict[str, Any]]:
    """Load recent entries from progress.jsonl.
    
    Args:
        project: Filter by project name (None = all projects)
        limit: Max entries to load (most recent)
        event_types: Filter by event type (None = all types)
    
    Returns:
        List of progress entries, newest first.
    """
    if not PROGRESS_LOG.exists():
        return []
    
    entries = []
    try:
        with open(PROGRESS_LOG, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                
                # Filter by project if specified
                if project and entry.get("project") != project:
                    # Also check if project is nested in data
                    if entry.get("data", {}).get("project") != project:
                        continue
                
                # Filter by event type if specified
                if event_types and entry.get("event_type") not in event_types:
                    continue
                
                entries.append(entry)
    except Exception:
        return []
    
    # Return most recent entries
    entries.sort(key=lambda e: e.get("ts", 0), reverse=True)
    return entries[:limit]


def extract_lessons(entries: list[dict[str, Any]]) -> list[dict[str, str]]:
    """Extract actionable lessons from progress entries.
    
    Focuses on failures, validation errors, and review rejections
    — the things the harness should learn from.
    """
    lessons = []
    
    for entry in entries:
        event_type = entry.get("event_type", "")
        data = entry.get("data", entry)
        
        # Task failures
        if event_type == "task_failed" or event_type == "error":
            error = data.get("error", "")
            task_desc = data.get("description", data.get("task_id", ""))
            failure_type = data.get("failure_type", "")
            
            if error:
                lessons.append({
                    "task": task_desc[:200],
                    "error_pattern": error[:500],
                    "fix": f"Failure type: {failure_type}" if failure_type else "",
                    "kind": "failure",
                    "ts": str(entry.get("ts", "")),
                })
        
        # Validation failures
        elif event_type == "validation_failed":
            summary = data.get("summary", "")
            task_desc = data.get("description", data.get("task_id", ""))
            
            if summary:
                lessons.append({
                    "task": task_desc[:200],
                    "error_pattern": f"Validation failed: {summary[:500]}",
                    "fix": "Fix validation errors before committing",
                    "kind": "validation_failure",
                    "ts": str(entry.get("ts", "")),
                })
        
        # Review failures
        elif event_type == "review_failed":
            summary = data.get("summary", "")
            task_desc = data.get("description", data.get("task_id", ""))
            
            if summary:
                lessons.append({
                    "task": task_desc[:200],
                    "error_pattern": f"Review rejected: {summary[:500]}",
                    "fix": "Reviewer found issues — check acceptance criteria",
                    "kind": "review_failure",
                    "ts": str(entry.get("ts", "")),
                })
        
        # Loop detection
        elif event_type == "loop_detected":
            task_id = data.get("task_id", "")
            attempts = data.get("attempts", {})
            
            lessons.append({
                "task": task_id,
                "error_pattern": f"Loop detected: {attempts} attempts without progress",
                "fix": "Task is stuck — consider different approach or skip",
                "kind": "loop_detected",
                "ts": str(entry.get("ts", "")),
            })
        
        # Patch failures
        elif event_type == "patch_failed":
            error = data.get("error", "")
            task_id = data.get("task_id", "")
            
            if error:
                lessons.append({
                    "task": task_id,
                    "error_pattern": f"Patch failed: {error[:500]}",
                    "fix": "LLM patch didn't match file content — check context extraction",
                    "kind": "patch_failure",
                    "ts": str(entry.get("ts", "")),
                })
        
        # Successful completions (for positive reinforcement)
        elif event_type == "task_completed":
            task_desc = data.get("description", data.get("task_id", ""))
            commit = data.get("commit", "")
            files = data.get("files", [])
            
            if commit:
                lessons.append({
                    "task": task_desc[:200],
                    "error_pattern": f"Completed successfully with commit {commit[:8]}",
                    "fix": f"Changed files: {', '.join(files[:5])}" if files else "",
                    "kind": "success",
                    "ts": str(entry.get("ts", "")),
                })
    
    return lessons


def sync_to_episodic_memory(
    project: str | None = None,
    limit: int = 100,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Sync progress.jsonl failures to episodic memory.
    
    Reads recent failures from progress.jsonl and stores them as
    lessons in the Qdrant episodic memory. Future sessions can then
    recall these lessons via RAG when working on similar tasks.
    
    Returns:
        Summary dict with counts of synced entries.
    """
    from jarvis.core.memory import EpisodicMemory, KIND_LESSON, MemoryEvent
    
    # Load entries
    entries = load_progress_entries(
        project=project,
        limit=limit,
    )
    
    # Extract lessons
    lessons = extract_lessons(entries)
    
    if not lessons:
        return {"synced": 0, "total_entries": len(entries), "lessons": 0}
    
    # Store in episodic memory
    memory = EpisodicMemory()
    if not memory.is_available():
        return {"synced": 0, "error": "Episodic memory not available", "lessons": len(lessons)}
    
    synced = 0
    for lesson in lessons:
        if dry_run:
            synced += 1
            continue
        
        try:
            text = f"Task: {lesson['task']}. Error: {lesson['error_pattern']}. Fix: {lesson['fix']}"
            event = MemoryEvent(
                kind=KIND_LESSON,
                text=text,
                task=lesson["task"],
                error_pattern=lesson["error_pattern"],
                fix=lesson["fix"],
            )
            result = memory.remember(event)
            if result is not None:
                synced += 1
        except Exception:
            pass
    
    return {
        "synced": synced,
        "total_entries": len(entries),
        "lessons": len(lessons),
        "project": project,
    }


def recall_relevant_lessons(
    task_description: str,
    top_k: int = 5,
) -> list[dict[str, str]]:
    """Recall relevant lessons from episodic memory for a given task.
    
    This is called by the harness before executing a task, so it can
    learn from past failures on similar tasks.
    
    Args:
        task_description: What the task is about
        top_k: How many lessons to recall
    
    Returns:
        List of relevant lessons with task, error, and fix.
    """
    from jarvis.core.memory import EpisodicMemory
    
    memory = EpisodicMemory()
    if not memory.is_available():
        return []
    
    results = memory.recall(task_description, top_k=top_k)
    
    lessons = []
    for r in results:
        text = r.get("text", "")
        payload = r.get("payload", {})
        score = r.get("score", 0)
        
        if text and score > 0.3:  # Only relevant results
            lessons.append({
                "text": text,
                "error_pattern": payload.get("error_pattern", ""),
                "fix": payload.get("fix", ""),
                "score": score,
            })
    
    return lessons
