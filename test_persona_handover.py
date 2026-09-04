#!/usr/bin/env python3
"""Test persona handover: different personas on same project."""
import time
import sys

sys.path.insert(0, "modules/ai/jarvis/src")

from nightwatch.harness import Harness, HarnessConfig
from nightwatch.task_queue import Task, TaskStatus

config = HarnessConfig(
    project="Corretor",
    max_tasks=4,
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

# Clean all old tasks that block the queue
old_count = len(harness.queue._tasks)
harness.queue._tasks = []
if old_count > 0:
    harness.queue._save()
    print(f"Cleaned {old_count} old tasks from queue")

# Each persona targets a DIFFERENT function to avoid conflicts
task_specs = [
    ("architect", "Add a docstring to the edits2() function explaining what it does", 1),
    ("backend_engineer", "Add error handling to the known_edits2() function for empty input", 2),
    ("qa_engineer", "Add a test function that verifies vocabulary_size() returns an integer", 3),
    ("technical_writer", "Add a comment above the spelltest() function explaining its purpose", 4),
]

for persona, desc, pri in task_specs:
    t = Task(
        id="ho-" + persona,
        project="Corretor",
        description=desc,
        target_files=["corretor.py"],
        priority=pri,
        risk="low",
        status=TaskStatus.READY.value,
    )
    harness.queue.add_task(t)

print("=== PERSONA HANDOVER TEST ===")
results = []
for persona, desc, pri in task_specs:
    task_id = "ho-" + persona
    t = None
    for x in harness.queue._tasks:
        if x.id == task_id:
            t = x
            break
    if t is None:
        print(f"  {persona:20s} SKIP   task not found")
        continue
    s = time.time()
    ok = harness.execute_task(t)
    e = time.time() - s
    status_char = "PASS" if ok else "FAIL"
    print(f"  {persona:20s} {status_char:4s} {e:5.1f}s  {t.status}")
    if t.last_error:
        print(f"    error: {t.last_error[:120]}")
    results.append((persona, ok, e, t.status))

print()
passed = sum(1 for _, ok, _, _ in results if ok)
total = len(results)
print(f"Result: {passed}/{total} personas completed successfully")
