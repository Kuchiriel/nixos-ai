"""Three-Agent Architecture — Planner → Generator → Evaluator.

Based on Anthropic's research (March 2026) on effective multi-agent patterns:
https://www.anthropic.com/engineering/harness-design-long-running-apps

Key insight: Context RESETS between agents, not compaction.
Each agent starts with fresh context + handoff artifact.

Architecture:
    Planner (fresh context)
        → decomposes goal into tasks
        → hands off task list to Generator
    
    Generator (fresh context per task)
        → implements each task
        → hands off diffs/patches to Evaluator
    
    Evaluator (fresh context)
        → reviews all changes
        → approves or rejects
        → hands off verdict to Planner for next iteration

This replaces the single-agent loop where one LLM does everything
with context accumulation that degrades quality.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable


@dataclass
class Plan:
    """Output of the Planner agent."""
    goal: str
    tasks: list[dict[str, Any]] = field(default_factory=list)
    context_summary: str = ""
    created_at: float = field(default_factory=time.time)


@dataclass
class TaskResult:
    """Output of the Generator agent for a single task."""
    task: dict[str, Any]
    success: bool
    patches: list[dict[str, Any]] = field(default_factory=list)
    files_changed: list[str] = field(default_factory=list)
    commit_sha: str = ""
    error: str = ""
    duration_seconds: float = 0.0


@dataclass
class Evaluation:
    """Output of the Evaluator agent."""
    approved: bool
    summary: str
    issues: list[str] = field(default_factory=list)
    recommendations: list[str] = field(default_factory=list)


class PlannerAgent:
    """Decomposes a high-level goal into executable tasks.
    
    Uses fresh context each time — no conversation history.
    Receives only the goal + project context + past lessons.
    """
    
    def __init__(self, call_llm: Callable[[str, int], str]):
        self.call_llm = call_llm
    
    def plan(self, goal: str, project: str, context: str = "") -> Plan:
        """Decompose goal into tasks using LLM.
        
        Args:
            goal: High-level objective
            project: Project name
            context: Optional context (file list, past lessons, etc.)
        
        Returns:
            Plan with ordered tasks
        """
        prompt = f"""You are a software engineering planner. Decompose this goal into specific, actionable tasks.

GOAL: {goal}
PROJECT: {project}
{f'CONTEXT: {context[:2000]}' if context else ''}

Rules:
- Each task must be specific enough to implement without further clarification
- Order tasks by dependency (foundational first)
- Each task should modify at most 2 files
- Include acceptance criteria for each task
- Max 8 tasks per iteration

Return JSON array:
[
  {{
    "id": "task-1",
    "description": "specific description of what to do",
    "target_files": ["file.py"],
    "acceptance_criteria": "how to verify this task is done",
    "priority": 1,
    "risk": "low"
  }}
]

If the goal is already achieved, return an empty array []."""
        
        response = self.call_llm(prompt, 2048)
        
        # Parse response
        tasks = []
        try:
            # Find JSON array in response
            start = response.find("[")
            end = response.rfind("]") + 1
            if start >= 0 and end > start:
                items = json.loads(response[start:end])
                for i, item in enumerate(items):
                    if isinstance(item, dict):
                        tasks.append({
                            "id": item.get("id", f"task-{i+1}"),
                            "description": item.get("description", ""),
                            "target_files": item.get("target_files", []),
                            "acceptance_criteria": item.get("acceptance_criteria", ""),
                            "priority": item.get("priority", i + 1),
                            "risk": item.get("risk", "low"),
                        })
        except (json.JSONDecodeError, ValueError):
            pass
        
        return Plan(
            goal=goal,
            tasks=tasks,
            context_summary=f"Project: {project}, Tasks planned: {len(tasks)}",
        )


class GeneratorAgent:
    """Implements a single task using the harness pipeline.
    
    Uses fresh context per task — only sees the task description
    and relevant file content, not the full conversation history.
    """
    
    def __init__(self, call_llm: Callable[[str, int], str]):
        self.call_llm = call_llm
    
    def execute(self, task: dict[str, Any], project: str) -> TaskResult:
        """Execute a single task through the harness.
        
        Args:
            task: Task dict with description, target_files, etc.
            project: Project name
        
        Returns:
            TaskResult with success/failure and details
        """
        from nightwatch.harness import Harness, HarnessConfig
        from nightwatch.task_queue import Task as QueueTask, TaskStatus
        
        start = time.time()
        
        # Create a fresh harness for this task (clean context)
        config = HarnessConfig(
            project=project,
            max_tasks=1,
            max_minutes=3,
            dry_run=False,
            use_llm_discovery=False,
            use_scripted_discovery=False,
            telegram_notifications=False,
            auto_review=True,
            run_tests=False,
            run_imports=False,
            max_retries=2,  # Give generator 2 chances
        )
        
        harness = Harness(config=config, call_llm=self.call_llm)
        
        # Create task
        queue_task = QueueTask(
            id=task.get("id", f"gen-{int(time.time())}"),
            project=project,
            description=task.get("description", ""),
            target_files=task.get("target_files", []),
            acceptance_criteria=task.get("acceptance_criteria", ""),
            priority=task.get("priority", 5),
            risk=task.get("risk", "low"),
            status=TaskStatus.READY.value,
        )
        harness.queue.add_task(queue_task)
        
        # Execute
        success = harness.execute_task(queue_task)
        
        elapsed = time.time() - start
        
        return TaskResult(
            task=task,
            success=success,
            files_changed=queue_task.target_files,
            commit_sha=queue_task.commit_sha or "",
            error=queue_task.last_error or "",
            duration_seconds=elapsed,
        )


class EvaluatorAgent:
    """Reviews all changes and decides if the goal is met.
    
    Uses fresh context — only sees the original goal, the tasks,
    and the results. No conversation history from planning or generation.
    """
    
    def __init__(self, call_llm: Callable[[str, int], str]):
        self.call_llm = call_llm
    
    def evaluate(
        self,
        goal: str,
        results: list[TaskResult],
        project: str,
    ) -> Evaluation:
        """Evaluate whether the goal has been achieved.
        
        Args:
            goal: Original goal
            results: Results from all generator tasks
            project: Project name
        
        Returns:
            Evaluation with approval/rejection and reasoning
        """
        # Build summary of what was done
        completed = [r for r in results if r.success]
        failed = [r for r in results if not r.success]
        
        summary_lines = []
        for r in completed:
            summary_lines.append(f"  ✅ {r.task.get('description', '?')[:80]}")
            if r.commit_sha:
                summary_lines.append(f"     Commit: {r.commit_sha[:8]}")
        for r in failed:
            summary_lines.append(f"  ❌ {r.task.get('description', '?')[:80]}")
            summary_lines.append(f"     Error: {r.error[:100]}")
        
        results_summary = "\n".join(summary_lines) if summary_lines else "  (no tasks executed)"
        
        prompt = f"""You are a software engineering evaluator. Review whether this goal has been achieved.

GOAL: {goal}
PROJECT: {project}

RESULTS:
{results_summary}

Completed: {len(completed)}/{len(results)}

Evaluate:
1. Has the goal been fully achieved?
2. Are there missing pieces?
3. Are the changes correct and complete?
4. Is anything broken?

Return JSON:
{{
  "approved": true/false,
  "summary": "brief explanation",
  "issues": ["issue 1", "issue 2"],
  "recommendations": ["recommendation 1"]
}}"""
        
        response = self.call_llm(prompt, 1024)
        
        # Parse response
        try:
            start = response.find("{")
            end = response.rfind("}") + 1
            if start >= 0 and end > start:
                result = json.loads(response[start:end])
                return Evaluation(
                    approved=result.get("approved", False),
                    summary=result.get("summary", ""),
                    issues=result.get("issues", []),
                    recommendations=result.get("recommendations", []),
                )
        except (json.JSONDecodeError, ValueError):
            pass
        
        # Fallback: approve if most tasks succeeded
        success_rate = len(completed) / max(len(results), 1)
        return Evaluation(
            approved=success_rate >= 0.7,
            summary=f"Evaluated {len(completed)}/{len(results)} tasks succeeded ({success_rate:.0%})",
            issues=[r.error for r in failed[:3]],
            recommendations=[],
        )


class ThreeAgentLoop:
    """Orchestrates the 3-agent loop: Plan → Generate → Evaluate → Repeat.
    
    Context resets between agents — each agent starts fresh.
    This prevents context degradation that plagues single-agent loops.
    """
    
    def __init__(self, call_llm: Callable[[str, int], str]):
        self.planner = PlannerAgent(call_llm)
        self.generator = GeneratorAgent(call_llm)
        self.evaluator = EvaluatorAgent(call_llm)
    
    def run(self, goal: str, project: str, max_iterations: int = 5) -> dict[str, Any]:
        """Run the 3-agent loop until goal is met or max iterations reached.
        
        Args:
            goal: High-level objective
            project: Project name
            max_iterations: Max plan→generate→evaluate cycles
        
        Returns:
            Summary dict with results
        """
        all_results: list[TaskResult] = []
        iterations = 0
        
        for iteration in range(max_iterations):
            print(f"\n{'='*60}")
            print(f"ITERATION {iteration + 1}/{max_iterations}")
            print(f"Goal: {goal}")
            print(f"{'='*60}")
            
            # Step 1: PLAN (fresh context)
            print("\n📋 Planning...")
            context = f"Previous results: {len(all_results)} tasks, {sum(1 for r in all_results if r.success)} succeeded"
            plan = self.planner.plan(goal, project, context)
            
            if not plan.tasks:
                print("No more tasks — checking if goal is met...")
                # Evaluate with empty results to check goal
                evaluation = self.evaluator.evaluate(goal, all_results, project)
                if evaluation.approved:
                    print(f"✅ GOAL MET: {evaluation.summary}")
                else:
                    print(f"❌ Goal not met: {evaluation.summary}")
                break
            
            print(f"Planned {len(plan.tasks)} tasks:")
            for t in plan.tasks:
                print(f"  - {t.get('description', '?')[:70]}")
            
            # Step 2: GENERATE (fresh context per task)
            print("\n🔧 Generating...")
            iteration_results = []
            for task in plan.tasks:
                print(f"\n  Executing: {task.get('description', '?')[:60]}...")
                result = self.generator.execute(task, project)
                iteration_results.append(result)
                all_results.append(result)
                
                status = "✅" if result.success else "❌"
                print(f"  {status} ({result.duration_seconds:.1f}s)")
                if result.error:
                    print(f"     Error: {result.error[:100]}")
            
            # Step 3: EVALUATE (fresh context)
            print("\n🔍 Evaluating...")
            evaluation = self.evaluator.evaluate(goal, all_results, project)
            
            if evaluation.approved:
                print(f"✅ GOAL MET: {evaluation.summary}")
                break
            else:
                print(f"❌ Not yet: {evaluation.summary}")
                if evaluation.issues:
                    print("Issues:")
                    for issue in evaluation.issues[:3]:
                        print(f"  - {issue[:80]}")
                print("Planning next iteration...")
            
            iterations = iteration + 1
        
        # Summary
        total = len(all_results)
        succeeded = sum(1 for r in all_results if r.success)
        total_time = sum(r.duration_seconds for r in all_results)
        
        return {
            "goal": goal,
            "project": project,
            "iterations": iterations + 1,
            "total_tasks": total,
            "succeeded": succeeded,
            "failed": total - succeeded,
            "total_time_seconds": total_time,
            "goal_met": evaluation.approved if 'evaluation' in dir() else False,
            "summary": evaluation.summary if 'evaluation' in dir() else "No evaluation",
        }
