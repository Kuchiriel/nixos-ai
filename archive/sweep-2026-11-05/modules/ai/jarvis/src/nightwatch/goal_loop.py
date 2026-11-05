"""GoalLoop — Autonomous goal-based execution.

Replaces LLM task discovery with a proven pattern:
1. Human gives a high-level goal
2. Planner decomposes into subtasks
3. Executor runs each subtask through the harness
4. Verifier checks if goal is met
5. Loop continues until done

This is the pattern used by Aider, OpenHands, and Codex for autonomous operation.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable


@dataclass
class GoalState:
    """Tracks the state of an autonomous goal execution."""
    goal: str
    project: str
    subtasks: list[dict] = field(default_factory=list)
    completed: list[str] = field(default_factory=list)
    failed: list[str] = field(default_factory=list)
    iteration: int = 0
    max_iterations: int = 10
    started_at: float = field(default_factory=time.time)
    goal_met: bool = False
    
    def to_dict(self) -> dict:
        return {
            "goal": self.goal,
            "project": self.project,
            "subtasks": self.subtasks,
            "completed": self.completed,
            "failed": self.failed,
            "iteration": self.iteration,
            "goal_met": self.goal_met,
        }


class GoalLoop:
    """Autonomous goal-based execution loop.
    
    Pattern (from Aider/OpenHands/Codex):
        goal → plan → execute → verify → plan more → ... → done
    
    Unlike LLM discovery (which asks "what tasks exist?"),
    this asks "how do I achieve this goal?" and iterates.
    """
    
    def __init__(
        self,
        project: str,
        call_llm: Callable[[str, int], str],
        send_telegram: Callable[[str], bool] | None = None,
    ):
        self.project = project
        self.call_llm = call_llm
        self.send_telegram = send_telegram or (lambda msg: False)
    
    def plan(self, state: GoalState) -> list[dict]:
        """Use LLM to decompose the goal into subtasks.
        
        Simple, direct prompt that works with small models.
        """
        completed = ", ".join(state.completed[-3:]) if state.completed else "none"
        failed = ", ".join(state.failed[-3:]) if state.failed else "none"
        
        prompt = f"""Goal: {state.goal}
Project: {self.project}
Already done: {completed}
Failed: {failed}

List 2-3 next specific changes to make. One per line, starting with action verb.
Example:
- Add error handling to the correct() function for empty input
- Add a CLI interface with argparse
- Write a basic test for the correct() function"""
        
        response = self.call_llm(prompt, 500)
        
        # Parse line-by-line (simpler than JSON for small models)
        subtasks = []
        for line in response.strip().split("\n"):
            line = line.strip()
            if line.startswith("-") or line.startswith("*"):
                desc = line.lstrip("- *.").strip()
                if len(desc) > 10:  # Skip trivial lines
                    subtasks.append({
                        "description": desc,
                        "target_files": [],
                        "priority": len(subtasks) + 1,
                        "persona": "backend_engineer",
                    })
        
        return subtasks[:5]  # Max 5 subtasks per iteration
    
    def verify(self, state: GoalState) -> tuple[bool, str]:
        """Use LLM to check if the goal has been achieved.
        
        Returns (goal_met, reason).
        """
        completed_summary = "\n".join(f"  ✅ {c}" for c in state.completed) if state.completed else "  (none yet)"
        failed_summary = "\n".join(f"  ❌ {f}" for f in state.failed) if state.failed else ""
        
        prompt = f"""You are verifying whether a software engineering goal has been achieved.

GOAL: {state.goal}
PROJECT: {self.project}

Completed subtasks:
{completed_summary}
{failed_summary}

Based on what has been completed, has the goal been achieved?
Consider: are there missing pieces? are the changes correct? is anything broken?

Reply with ONLY a JSON object:
{{"met": true/false, "reason": "brief explanation"}}
"""
        
        response = self.call_llm(prompt, 500)
        
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                result = json.loads(response[start:end])
                return result.get("met", False), result.get("reason", "")
        except (json.JSONDecodeError, ValueError):
            pass
        
        return False, "Could not parse verification response"
    
    def run(self, goal: str, max_iterations: int = 10) -> GoalState:
        """Run the goal loop autonomously.
        
        1. Plan subtasks
        2. Execute each subtask
        3. Verify goal
        4. If not met, plan more
        5. Repeat until done or max iterations
        """
        from nightwatch.harness import Harness, HarnessConfig
        from nightwatch.task_queue import Task, TaskStatus
        
        state = GoalState(goal=goal, project=self.project, max_iterations=max_iterations)
        
        for iteration in range(max_iterations):
            state.iteration = iteration
            print(f"\n{'='*60}")
            print(f"GOAL LOOP — Iteration {iteration + 1}/{max_iterations}")
            print(f"Goal: {goal}")
            print(f"Completed: {len(state.completed)}, Failed: {len(state.failed)}")
            print(f"{'='*60}")
            
            # Step 1: Plan
            print("\n📋 Planning...")
            subtasks = self.plan(state)
            
            if not subtasks:
                print("No more subtasks — checking if goal is met...")
                met, reason = self.verify(state)
                state.goal_met = met
                if met:
                    print(f"✅ GOAL MET: {reason}")
                else:
                    print(f"❌ Goal not met: {reason}")
                break
            
            print(f"Found {len(subtasks)} subtasks")
            for i, st in enumerate(subtasks):
                print(f"  {i+1}. {st.get('description', '?')[:80]}")
            
            # Step 2: Execute each subtask
            config = HarnessConfig(
                project=self.project,
                max_tasks=len(subtasks),
                max_minutes=5,
                dry_run=False,
                use_llm_discovery=False,
                use_scripted_discovery=False,
                telegram_notifications=False,
                auto_review=True,
                run_tests=False,
                run_imports=False,
                max_retries=1,
            )
            harness = Harness(config=config, call_llm=self.call_llm, send_telegram=self.send_telegram)
            
            for st in subtasks:
                desc = st.get("description", "")
                target_files = st.get("target_files", [f for f in st.get("target_files", []) if f])
                
                if not target_files:
                    # Auto-detect target files from description
                    target_files = self._detect_target_files(desc)
                
                task = Task(
                    id=f"goal-{iteration}-{len(state.completed)}",
                    project=self.project,
                    description=desc,
                    target_files=target_files,
                    priority=st.get("priority", 5),
                    risk="low",
                    status=TaskStatus.READY.value,
                )
                harness.queue.add_task(task)
                
                print(f"\n🔧 Executing: {desc[:60]}...")
                success = harness.execute_task(task)
                
                if success:
                    state.completed.append(desc)
                    print(f"  ✅ Completed")
                else:
                    state.failed.append(f"{desc} — {task.last_error or 'unknown'}")
                    print(f"  ❌ Failed: {task.last_error or 'unknown'}")
            
            # Step 3: Verify
            print("\n🔍 Verifying goal...")
            met, reason = self.verify(state)
            state.goal_met = met
            
            if met:
                print(f"✅ GOAL MET: {reason}")
                break
            else:
                print(f"❌ Not yet: {reason}")
                print("Planning next iteration...")
        
        # Summary
        elapsed = time.time() - state.started_at
        print(f"\n{'='*60}")
        print(f"GOAL LOOP COMPLETE")
        print(f"Goal met: {state.goal_met}")
        print(f"Iterations: {state.iteration + 1}")
        print(f"Completed: {len(state.completed)}")
        print(f"Failed: {len(state.failed)}")
        print(f"Duration: {elapsed:.1f}s")
        print(f"{'='*60}")
        
        return state
    
    def _detect_target_files(self, description: str) -> list[str]:
        """Auto-detect target files from task description."""
        import os
        env_root = os.environ.get("JARVIS_PROJECT_ROOT")
        project_root = Path(env_root) if env_root and Path(env_root).exists() else Path.home() / "projects" / self.project
        
        # Find all Python files
        try:
            import subprocess
            result = subprocess.run(
                ["find", str(project_root), "-name", "*.py", "-type", "f",
                 "-not", "-path", "*/__pycache__/*"],
                capture_output=True, text=True, timeout=10,
            )
            files = [f.strip() for f in result.stdout.strip().split("\n") if f.strip()]
        except Exception:
            return []
        
        # Match description against file names
        desc_lower = description.lower()
        matched = []
        for f in files:
            fname = Path(f).name.lower()
            # Check if any word from the filename is in the description
            stem = Path(f).stem.lower()
            if stem in desc_lower or any(w in desc_lower for w in stem.split("_") if len(w) > 3):
                # Return relative path
                try:
                    rel = str(Path(f).relative_to(project_root))
                    matched.append(rel)
                except ValueError:
                    matched.append(str(f))
        
        # Fallback: return all Python files (LLM will pick the right one)
        if not matched:
            matched = [str(Path(f).relative_to(project_root)) for f in files[:5]
                       if Path(f).suffix == ".py"]
        
        return matched
