# PAUSADO — nightwatch/harness.py ja resolve isso (task_queue+safety+checkpoint).
# Ver decisao de consolidacao de 2026-08-31.
# Nao construir em cima disso sem revisar nightwatch/ primeiro.

"""
Subagent Architecture — isolated context, identity, persona, handoff.

Based on research:
- OpenDev dual-agent (planner + executor)
- Augment Code coordinator/specialist/verifier
- Self-Harness weakness mining

Subagents have:
- Isolated context (own messages, tools, memory)
- Identity (unique ID, persona assignment)
- Budget (token limit, time limit)
- Tools (subset of available tools)
- Checkpoint (can save/restore state)
- Result (output for handoff)
- Handoff protocol (pass context to next agent)
"""

import json
import os
import time
import uuid
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Any, Callable, Optional


@dataclass
class SubagentConfig:
    """Configuration for a subagent."""
    id: str = ""
    persona_id: str = ""
    project: str = ""
    task_description: str = ""
    tools: list = field(default_factory=list)
    token_budget: int = 8000
    time_budget_seconds: int = 300
    model_tier: str = "medium"
    parent_id: str = ""  # for hierarchical agents

    def __post_init__(self):
        if not self.id:
            self.id = str(uuid.uuid4())[:8]


@dataclass
class SubagentState:
    """Persistent state of a subagent."""
    config: SubagentConfig = field(default_factory=SubagentConfig)
    status: str = "pending"  # pending, running, completed, failed, blocked
    messages: list = field(default_factory=list)
    tools_used: list = field(default_factory=list)
    files_changed: list = field(default_factory=list)
    commits: list = field(default_factory=list)
    errors: list = field(default_factory=list)
    result: str = ""
    started_at: float = 0
    completed_at: float = 0
    tokens_used: int = 0

    def to_dict(self):
        return {
            "config": asdict(self.config),
            "status": self.status,
            "messages_count": len(self.messages),
            "tools_used": self.tools_used,
            "files_changed": self.files_changed,
            "commits": self.commits,
            "errors": self.errors[:5],
            "result": self.result[:500],
            "started_at": self.started_at,
            "completed_at": self.completed_at,
            "tokens_used": self.tokens_used,
        }


class Subagent:
    """An isolated agent instance with its own context."""

    def __init__(self, config: SubagentConfig = None):
        self.config = config or SubagentConfig()
        self.state = SubagentState(config=self.config)
        self._tools: dict[str, Callable] = {}
        self._checkpoint_dir = Path(os.path.expanduser(
            f"~/.local/state/jarvis/subagents/{self.config.id}"
        ))
        self._checkpoint_dir.mkdir(parents=True, exist_ok=True)

    def register_tool(self, name: str, fn: Callable) -> None:
        """Register a tool that this subagent can use."""
        self._tools[name] = fn

    def run(self, task: str) -> str:
        """Execute a task and return the result.

        This is the main execution loop for the subagent.
        """
        self.state.status = "running"
        self.state.started_at = time.time()
        self.state.messages.append({
            "role": "user",
            "content": task,
        })

        try:
            # For now, this is a simple implementation
            # In production, this would call the LLM with tool use
            result = self._execute(task)
            self.state.result = result
            self.state.status = "completed"
        except Exception as e:
            self.state.errors.append(str(e))
            self.state.status = "failed"
            self.state.result = f"Error: {e}"
        finally:
            self.state.completed_at = time.time()
            self._save_checkpoint()

        return self.state.result

    def _execute(self, task: str) -> str:
        """Execute a task using available tools.

        This is a simplified version - in production would use LLM loop.
        """
        # Try to use RAG for context
        try:
            from jarvis.core.rag import RAGEngine
            rag = RAGEngine()
            results = rag.search(task, top_k=3)
            context = "\n".join([f"- {r.get('path', '?')}: {r.get('text', '')[:100]}" for r in results])
        except Exception:
            context = "No RAG context available"

        # Try to use memory
        try:
            from jarvis.core.memory import EpisodicMemory
            mem = EpisodicMemory()
            memories = mem.recall(task, top_k=3)
            memory_text = "\n".join([f"- {m.get('content', '')[:100]}" for m in memories])
        except Exception:
            memory_text = "No memory available"

        result = f"""Task: {task}
Context: {context}
Memory: {memory_text}

Subagent {self.config.id} (persona: {self.config.persona_id}) processed this task.
"""
        return result

    def _save_checkpoint(self) -> None:
        """Save subagent state to disk."""
        state_file = self._checkpoint_dir / "state.json"
        with open(state_file, "w") as f:
            json.dump(self.state.to_dict(), f, indent=2, default=str)

    def _load_checkpoint(self) -> bool:
        """Load subagent state from disk."""
        state_file = self._checkpoint_dir / "state.json"
        if state_file.exists():
            try:
                with open(state_file) as f:
                    data = json.load(f)
                self.state.status = data.get("status", "pending")
                self.state.result = data.get("result", "")
                self.state.tools_used = data.get("tools_used", [])
                self.state.files_changed = data.get("files_changed", [])
                self.state.commits = data.get("commits", [])
                return True
            except Exception:
                return False
        return False

    def handoff_to(self, next_agent: "Subagent") -> None:
        """Pass context to another subagent."""
        next_agent.state.messages.extend(self.state.messages)
        next_agent.state.files_changed.extend(self.state.files_changed)
        next_agent.state.commits.extend(self.state.commits)

    def get_summary(self) -> dict:
        """Get a summary of the subagent's work."""
        return {
            "id": self.config.id,
            "persona": self.config.persona_id,
            "project": self.config.project,
            "status": self.state.status,
            "tools_used": len(self.state.tools_used),
            "files_changed": len(self.state.files_changed),
            "commits": len(self.state.commits),
            "errors": len(self.state.errors),
            "duration_seconds": self.state.completed_at - self.state.started_at if self.state.completed_at else 0,
        }


class SubagentOrchestrator:
    """Orchestrates multiple subagents for complex tasks."""

    def __init__(self, state_dir: str = None):
        if state_dir is None:
            state_dir = os.path.expanduser("~/.local/state/jarvis/subagents")
        self.state_dir = Path(state_dir)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self._agents: dict[str, Subagent] = {}

    def create_agent(self, config: SubagentConfig) -> Subagent:
        """Create a new subagent."""
        agent = Subagent(config)
        self._agents[config.id] = agent
        return agent

    def run_pipeline(self, tasks: list[dict]) -> list[dict]:
        """Run a pipeline of tasks with different subagents.

        Each task dict should have:
        - task: description
        - persona_id: which persona to use
        - project: which project
        """
        results = []

        for i, task_def in enumerate(tasks):
            config = SubagentConfig(
                persona_id=task_def.get("persona_id", "backend_engineer"),
                project=task_def.get("project", "nixos-ai"),
                task_description=task_def.get("task", ""),
            )

            agent = self.create_agent(config)

            # Handoff from previous agent if exists
            if i > 0 and results:
                prev_agent = self._agents.get(results[-1].get("id"))
                if prev_agent:
                    prev_agent.handoff_to(agent)

            result = agent.run(task_def.get("task", ""))
            results.append({
                "id": config.id,
                "task": task_def.get("task", ""),
                "result": result,
                "status": agent.state.status,
            })

        return results

    def run_parallel(self, tasks: list[dict]) -> list[dict]:
        """Run tasks in parallel with different subagents.

        Note: Currently sequential - parallel would need async/threading.
        """
        return self.run_pipeline(tasks)

    def get_all_summaries(self) -> list[dict]:
        """Get summaries of all subagents."""
        return [agent.get_summary() for agent in self._agents.values()]

    def save_all(self) -> None:
        """Save all subagent states."""
        for agent in self._agents.values():
            agent._save_checkpoint()

    def load_all(self) -> int:
        """Load all subagent states from disk."""
        count = 0
        for agent_dir in self.state_dir.iterdir():
            if agent_dir.is_dir():
                agent = Subagent(SubagentConfig(id=agent_dir.name))
                if agent._load_checkpoint():
                    self._agents[agent.config.id] = agent
                    count += 1
        return count
