"""Harness — Main orchestrator for the Nightwatch autonomous coding agent.

Integrates:
- TaskQueue (persistent state)
- Patcher (safe editing)
- FileGuard (structural validation)
- Validator (test pipeline)
- Evaluator (independent review)
- Checkpoint (recovery)
"""

from __future__ import annotations

import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from nightwatch.task_queue import TaskQueue, Task, TaskStatus, MissionState
from nightwatch.patcher import request_patch_from_llm, PatchResult
from nightwatch.validator import validate_change, ValidationReport
from nightwatch.evaluator import review_change, auto_review, ReviewResult
from nightwatch.checkpoint import Checkpoint, create_checkpoint_for_task, get_recovery_context


REPO_ROOT = Path.home() / "projects" / "nixos-ai"
STATE_DIR = Path.home() / ".local/state/jarvis/nightwatch"


@dataclass
class HarnessConfig:
    """Configuration for the harness."""
    project: str = "nixos-ai"
    max_tasks: int = 10
    max_minutes: int = 180
    max_retries: int = 3
    auto_approve: bool = True
    run_tests: bool = True
    run_imports: bool = True
    auto_review: bool = True
    telegram_notifications: bool = True


@dataclass
class HarnessResult:
    """Result of a harness run."""
    tasks_completed: int = 0
    tasks_failed: int = 0
    tasks_blocked: int = 0
    files_changed: list[str] = None
    commits: list[str] = None
    duration_seconds: float = 0.0
    errors: list[str] = None
    
    def __post_init__(self):
        if self.files_changed is None:
            self.files_changed = []
        if self.commits is None:
            self.commits = []
        if self.errors is None:
            self.errors = []


class Harness:
    """Main harness orchestrator."""
    
    def __init__(
        self,
        config: HarnessConfig | None = None,
        call_llm: Callable[[str, int], str] | None = None,
        send_telegram: Callable[[str], bool] | None = None,
    ):
        self.config = config or HarnessConfig()
        self.call_llm = call_llm or self._default_call_llm
        self.send_telegram = send_telegram or self._default_send_telegram
        self.queue = TaskQueue()
        self.checkpoint = Checkpoint.load()
        self.mission = self.queue.mission
    
    def _default_call_llm(self, prompt: str, max_tokens: int = 2048) -> str:
        """Default LLM caller."""
        import requests
        url = "http://127.0.0.1:8080/v1/chat/completions"
        payload = {
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": max_tokens,
            "temperature": 0.3,
            "chat_template_kwargs": {"enable_thinking": False},
        }
        try:
            resp = requests.post(url, json=payload, timeout=300)
            resp.raise_for_status()
            data = resp.json()
            msg = data["choices"][0]["message"]
            return msg.get("content", "") or msg.get("reasoning_content", "")
        except Exception as e:
            return f"ERROR: {e}"
    
    def _default_send_telegram(self, message: str) -> bool:
        """Default Telegram sender."""
        env_file = Path("/etc/jarvis-telegram.env")
        if not env_file.exists():
            return False
        try:
            env = {}
            for line in env_file.read_text().splitlines():
                if "=" in line:
                    key, _, value = line.partition("=")
                    env[key.strip()] = value.strip()
            
            import requests
            resp = requests.post(
                f"https://api.telegram.org/bot{env['JARVIS_TELEGRAM_TOKEN']}/sendMessage",
                json={
                    "chat_id": env["JARVIS_TELEGRAM_CHAT_ID"],
                    "text": message,
                    "parse_mode": "Markdown",
                },
                timeout=10,
            )
            return resp.status_code == 200
        except Exception:
            return False
    
    def notify(self, message: str) -> None:
        """Send notification if enabled."""
        if self.config.telegram_notifications:
            self.send_telegram(message)
    
    def discover_tasks(self) -> list[Task]:
        """Discover tasks using the LLM."""
        # Get codebase overview
        try:
            result = subprocess.run(
                ["find", str(REPO_ROOT / "modules/ai/jarvis/src"), "-name", "*.py", "-type", "f"],
                capture_output=True, text=True, timeout=10,
            )
            files = result.stdout.strip().split("\n")[:20]
        except Exception:
            files = []
        
        prompt = f"""Analyze this Python codebase and identify 3-5 improvement tasks.

Key files:
{chr(10).join(files[:15])}

For each task provide JSON:
{{
  "description": "what to do",
  "target_files": ["file.py"],
  "acceptance_criteria": "how to verify",
  "priority": 1-10,
  "risk": "low/medium/high"
}}

Focus on: error handling, code quality, security, missing tests, documentation.
Return JSON array."""

        response = self.call_llm(prompt, 1500)
        
        tasks = []
        try:
            start = response.find("[")
            end = response.rfind("]") + 1
            if start >= 0 and end > start:
                items = json.loads(response[start:end])
                for i, item in enumerate(items):
                    tasks.append(Task(
                        id=f"disc-{int(time.time())}-{i}",
                        project=self.config.project,
                        description=item.get("description", ""),
                        target_files=item.get("target_files", []),
                        acceptance_criteria=item.get("acceptance_criteria", ""),
                        priority=item.get("priority", 5),
                        risk=item.get("risk", "low"),
                        status=TaskStatus.READY.value,
                    ))
        except json.JSONDecodeError:
            pass
        
        return tasks
    
    def execute_task(self, task: Task) -> bool:
        """Execute a single task."""
        # Create checkpoint
        cp = create_checkpoint_for_task(task.id, task.description, self.config.project)
        
        # Notify start
        self.notify(f"🔄 *Task Started*\n{task.description[:100]}")
        
        # Mark in progress
        self.queue.update_task(task.id, status=TaskStatus.IN_PROGRESS.value)
        
        try:
            # Request patch from LLM
            patch_result = request_patch_from_llm(
                task_description=task.description,
                target_files=task.target_files,
                call_llm_fn=self.call_llm,
            )
            
            cp.record_operation("patch", patch_result.success, 
                               "; ".join(patch_result.errors) if patch_result.errors else "")
            
            if not patch_result.success:
                task.fail("; ".join(patch_result.errors))
                self.notify(f"❌ *Task Failed*\n{task.description[:50]}\nError: {patch_result.errors[0][:100]}")
                return False
            
            # Validate changes
            self.queue.update_task(task.id, status=TaskStatus.VALIDATING.value)
            validation = validate_change(
                patch_result.files_applied,
                run_tests=self.config.run_tests,
                run_imports=self.config.run_imports,
            )
            
            cp.record_operation("validate", validation.passed, validation.summary)
            
            if not validation.passed:
                # Revert changes
                self._revert_changes()
                task.fail(f"Validation failed: {validation.summary}")
                self.notify(f"❌ *Validation Failed*\n{validation.summary}")
                return False
            
            # Independent review
            if self.config.auto_review:
                self.queue.update_task(task.id, status=TaskStatus.REVIEW.value)
                test_output = "\n".join(s.output for s in validation.steps if s.name == "tests")
                review = review_change(
                    task_description=task.description,
                    acceptance_criteria=task.acceptance_criteria,
                    test_output=test_output,
                    call_llm_fn=self.call_llm,
                )
                
                if not review.passed:
                    self._revert_changes()
                    task.fail(f"Review failed: {review.summary}")
                    self.notify(f"❌ *Review Failed*\n{review.summary}")
                    return False
            
            # Commit
            commit_sha = self._commit(task)
            cp.record_operation("commit", commit_sha is not None)
            
            # Complete
            task.complete(commit_sha)
            self.mission.total_tasks_completed += 1
            if commit_sha:
                self.mission.total_commits += 1
            
            self.notify(f"✅ *Task Complete*\n{task.description[:50]}\nCommit: {commit_sha[:8] if commit_sha else 'N/A'}")
            
            return True
            
        except Exception as e:
            cp.record_operation("error", False, str(e))
            task.fail(str(e))
            self.notify(f"❌ *Task Error*\n{str(e)[:100]}")
            return False
    
    def _revert_changes(self) -> None:
        """Revert uncommitted changes."""
        try:
            subprocess.run(
                ["git", "checkout", "--", "."],
                capture_output=True, timeout=10,
                cwd=str(REPO_ROOT),
            )
            subprocess.run(
                ["git", "clean", "-fd"],
                capture_output=True, timeout=10,
                cwd=str(REPO_ROOT),
            )
        except Exception:
            pass
    
    def _commit(self, task: Task) -> str | None:
        """Commit changes with descriptive message."""
        try:
            subprocess.run(
                ["git", "add", "-A"],
                capture_output=True, timeout=10,
                cwd=str(REPO_ROOT),
            )
            
            msg = f"nightwatch({task.project}): {task.description[:80]}"
            if task.commit_sha:
                msg += f"\n\nTask ID: {task.id}"
            
            result = subprocess.run(
                ["git", "commit", "-m", msg],
                capture_output=True, text=True, timeout=30,
                cwd=str(REPO_ROOT),
            )
            
            if result.returncode == 0:
                sha = subprocess.run(
                    ["git", "rev-parse", "HEAD"],
                    capture_output=True, text=True, timeout=5,
                    cwd=str(REPO_ROOT),
                ).stdout.strip()
                return sha
        except Exception:
            pass
        return None
    
    def run(self) -> HarnessResult:
        """Run the harness."""
        start = time.time()
        result = HarnessResult()
        
        self.mission.active = True
        self.mission.started_at = time.time()
        
        self.notify(f"🌙 *Nightwatch Harness Started*\nProject: {self.config.project}")
        
        # Check for recovery context
        recovery = get_recovery_context()
        if recovery and recovery.get("task_id"):
            self.notify(f"♻️ *Recovering task*: {recovery['task_description'][:50]}")
        
        # Discover tasks
        self.notify("🔍 Discovering tasks...")
        new_tasks = self.discover_tasks()
        for task in new_tasks:
            self.queue.add_task(task)
        
        self.notify(f"📋 Found {len(new_tasks)} new tasks")
        
        # Execute tasks
        executed = 0
        while executed < self.config.max_tasks:
            if (time.time() - start) > self.config.max_minutes * 60:
                self.notify(f"⏰ Time limit reached ({self.config.max_minutes} min)")
                break
            
            task = self.queue.get_next_task()
            if not task:
                self.notify("✅ No more tasks available")
                break
            
            success = self.execute_task(task)
            
            if success:
                result.tasks_completed += 1
                result.files_changed.extend(task.target_files)
                if task.commit_sha:
                    result.commits.append(task.commit_sha)
            else:
                if task.status == TaskStatus.BLOCKED.value:
                    result.tasks_blocked += 1
                else:
                    result.tasks_failed += 1
            
            executed += 1
        
        # Summary
        elapsed = time.time() - start
        result.duration_seconds = elapsed
        
        self.mission.active = False
        self.mission.last_checkpoint = time.time()
        
        stats = self.queue.get_stats()
        summary = f"""🌙 *Nightwatch Complete*

📊 Results:
- Completed: {result.tasks_completed}
- Failed: {result.tasks_failed}
- Blocked: {result.tasks_blocked}
- Files changed: {len(result.files_changed)}
- Commits: {len(result.commits)}
- Duration: {int(elapsed // 60)}m {int(elapsed % 60)}s

📈 Queue: {stats['completed']} done, {stats['ready']} ready, {stats['blocked']} blocked"""
        
        self.notify(summary)
        
        return result
