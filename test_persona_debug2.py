#!/usr/bin/env python3
"""Debug task timeout issue."""
import time
import sys

sys.path.insert(0, "modules/ai/jarvis/src")

from nightwatch.harness import Harness, HarnessConfig
from nightwatch.task_queue import Task, TaskStatus

print("Creating config...")
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

print("Creating harness...")
harness = Harness(config=config)

print(f"Queue has {len(harness.queue._tasks)} tasks from disk")
for t in harness.queue._tasks[:3]:
    print(f"  {t.id}: created={t.created_at}, status={t.status}, age={time.time() - t.created_at:.0f}s")

now = time.time()
t = Task(
    id="debug-new",
    project="Corretor",
    description="Add a comment to the edits2 function",
    target_files=["corretor.py"],
    priority=1,
    risk="low",
    status=TaskStatus.READY.value,
)
print(f"\nNew task created_at: {t.created_at}")
print(f"Now: {now}")
print(f"Age: {now - t.created_at:.1f}s")

harness.queue.add_task(t)
print(f"Queue now has {len(harness.queue._tasks)} tasks")

# Find our task
for x in harness.queue._tasks:
    if x.id == "debug-new":
        print(f"Found task: {x.id}, age={time.time() - x.created_at:.1f}s, status={x.status}")
        print("Executing...")
        ok = harness.execute_task(x)
        print(f"Result: {ok}, status: {x.status}")
        break
