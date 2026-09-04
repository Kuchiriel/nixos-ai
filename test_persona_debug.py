#!/usr/bin/env python3
"""Debug persona handover failures."""
import time
import sys

sys.path.insert(0, "modules/ai/jarvis/src")

from nightwatch.harness import Harness, HarnessConfig
from nightwatch.task_queue import Task, TaskStatus

config = HarnessConfig(
    project="Corretor",
    max_tasks=1,
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
harness = Harness(config=config)

t = Task(
    id="debug-1",
    project="Corretor",
    description="Add a comment above the train function",
    target_files=["corretor.py"],
    priority=1,
    risk="low",
    status=TaskStatus.READY.value,
)

print(f"Task created_at: {t.created_at}")
print(f"Task status: {t.status}")
print(f"Config task_timeout: {config.task_timeout}")
print(f"Config dry_run: {config.dry_run}")
print(f"Task target_files: {t.target_files}")

# Check protected paths
from nightwatch import safety
for f in t.target_files:
    prot = safety.is_path_protected(f)
    print(f"  Protected({f}): {prot}")

harness.queue.add_task(t)
print(f"Queue tasks: {len(harness.queue._tasks)}")

# Try execute
print("Executing...")
ok = harness.execute_task(t)
print(f"Result: {ok}, status: {t.status}, error: {t.last_error}")
