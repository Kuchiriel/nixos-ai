"""P5 validation: state machine transitions are enforced.

Verifies that:
- Valid transitions work
- Invalid transitions are rejected
- Terminal states can't transition out (except FAILED→READY for retry)
- update_task validates status changes
"""

import sys
from pathlib import Path

# Add jarvis to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from nightwatch.task_queue import Task, TaskStatus, TaskQueue, VALID_TRANSITIONS


class TestP5StateMachine:
    """Test that the state machine enforces valid transitions."""

    def test_valid_transitions_exist(self):
        """Every state has defined transitions."""
        for status in TaskStatus:
            assert status.value in VALID_TRANSITIONS, f"Missing transitions for {status.value}"

    def test_terminal_states_have_no_outgoing(self):
        """COMPLETED and ABANDONED have no outgoing transitions."""
        assert VALID_TRANSITIONS[TaskStatus.COMPLETED.value] == set()
        assert VALID_TRANSITIONS[TaskStatus.ABANDONED.value] == set()

    def test_failed_can_retry(self):
        """FAILED → READY is allowed (retry)."""
        assert TaskStatus.READY.value in VALID_TRANSITIONS[TaskStatus.FAILED.value]

    def test_discovered_to_ready(self):
        """DISCOVERED → READY is valid."""
        assert TaskStatus.READY.value in VALID_TRANSITIONS[TaskStatus.DISCOVERED.value]

    def test_in_progress_to_validating(self):
        """IN_PROGRESS → VALIDATING is valid."""
        assert TaskStatus.VALIDATING.value in VALID_TRANSITIONS[TaskStatus.IN_PROGRESS.value]

    def test_validating_to_review(self):
        """VALIDATING → REVIEW is valid."""
        assert TaskStatus.REVIEW.value in VALID_TRANSITIONS[TaskStatus.VALIDATING.value]

    def test_review_to_completed(self):
        """REVIEW → COMPLETED is valid."""
        assert TaskStatus.COMPLETED.value in VALID_TRANSITIONS[TaskStatus.REVIEW.value]

    def test_invalid_transition_rejected(self):
        """COMPLETED → IN_PROGRESS should be rejected."""
        task = Task(id="test-1", project="test", description="test")
        task._transition(TaskStatus.READY.value)
        task._transition(TaskStatus.IN_PROGRESS.value)
        task._transition(TaskStatus.VALIDATING.value)
        task._transition(TaskStatus.REVIEW.value)
        task.complete("sha123")
        assert task.status == TaskStatus.COMPLETED.value
        # Try invalid transition via _transition
        result = task._transition(TaskStatus.IN_PROGRESS.value)
        assert result is False
        assert task.status == TaskStatus.COMPLETED.value  # unchanged

    def test_invalid_transition_abandoned(self):
        """ABANDONED → anything should be rejected."""
        task = Task(id="test-2", project="test", description="test")
        task.abandon("not needed")
        assert task.status == TaskStatus.ABANDONED.value
        result = task._transition(TaskStatus.READY.value)
        assert result is False
        assert task.status == TaskStatus.ABANDONED.value

    def test_block_from_any_non_terminal(self):
        """BLOCKED can be reached from any non-terminal state."""
        for status in TaskStatus:
            if status.value in (TaskStatus.COMPLETED.value, TaskStatus.ABANDONED.value):
                continue
            task = Task(id=f"test-{status.value}", project="test", description="test")
            task.status = status.value
            task.block("test reason")
            # BLOCKED→BLOCKED is a no-op, not an error
            if status.value == TaskStatus.BLOCKED.value:
                assert task.status == TaskStatus.BLOCKED.value
            else:
                assert task.status == TaskStatus.BLOCKED.value

    def test_fail_increments_attempts(self):
        """fail() increments attempts and stays READY if under max."""
        task = Task(id="test-fail", project="test", description="test", max_attempts=3)
        task.fail("error 1")
        assert task.attempts == 1
        assert task.status == TaskStatus.READY.value
        task.fail("error 2")
        assert task.attempts == 2
        assert task.status == TaskStatus.READY.value

    def test_fail_reaches_max(self):
        """fail() transitions to FAILED when max_attempts reached."""
        task = Task(id="test-max", project="test", description="test", max_attempts=2)
        # Need to be in a valid state for fail() to work
        task._transition(TaskStatus.READY.value)
        task.fail("error 1")
        assert task.status == TaskStatus.READY.value  # attempts=1 < max=2
        task.fail("error 2")
        assert task.status == TaskStatus.FAILED.value  # attempts=2 >= max=2
        assert task.is_terminal

    def test_failed_to_ready_retry(self):
        """FAILED → READY is allowed for retry."""
        task = Task(id="test-retry", project="test", description="test")
        task.status = TaskStatus.FAILED.value
        result = task._transition(TaskStatus.READY.value)
        assert result is True
        assert task.status == TaskStatus.READY.value

    def test_update_task_validates_status(self):
        """update_task validates status transitions."""
        q = TaskQueue()
        q._tasks = []  # clear any loaded state
        task = Task(id="upd-1", project="test", description="test")
        q._tasks.append(task)
        
        # Valid transition: DISCOVERED → IN_PROGRESS
        q.update_task("upd-1", status=TaskStatus.IN_PROGRESS.value)
        assert task.status == TaskStatus.IN_PROGRESS.value
        
        # Invalid transition: IN_PROGRESS → COMPLETED (skipping VALIDATING/REVIEW)
        q.update_task("upd-1", status=TaskStatus.COMPLETED.value)
        # Should still be IN_PROGRESS (transition rejected)
        assert task.status == TaskStatus.IN_PROGRESS.value

    def test_full_valid_lifecycle(self):
        """Happy path: DISCOVERED → READY → IN_PROGRESS → VALIDATING → REVIEW → COMPLETED."""
        task = Task(id="lifecycle", project="test", description="test")
        assert task.status == TaskStatus.DISCOVERED.value
        
        task._transition(TaskStatus.READY.value)
        assert task.status == TaskStatus.READY.value
        
        task._transition(TaskStatus.IN_PROGRESS.value)
        assert task.status == TaskStatus.IN_PROGRESS.value
        
        task._transition(TaskStatus.VALIDATING.value)
        assert task.status == TaskStatus.VALIDATING.value
        
        task._transition(TaskStatus.REVIEW.value)
        assert task.status == TaskStatus.REVIEW.value
        
        task.complete("sha123")
        assert task.status == TaskStatus.COMPLETED.value
        assert task.is_terminal

    def test_recover_stuck_uses_transition(self):
        """recover_stuck_tasks uses _transition, not direct assignment."""
        q = TaskQueue()
        q._tasks = []
        task = Task(id="stuck", project="test", description="test")
        task.status = TaskStatus.IN_PROGRESS.value
        task.updated_at = 0  # very old
        q._tasks.append(task)
        
        recovered = q.recover_stuck_tasks(max_age_seconds=1)
        assert recovered == 1
        assert task.status == TaskStatus.READY.value
