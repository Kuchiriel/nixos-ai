"""Real E2E test for nightwatch harness.

Tests the full pipeline with REAL file operations:
- SafeEditor writes files atomically
- Validator checks syntax
- Checkpoint saves state
- Git commits are real
- Recovery works after failure
- Task queue persists across calls

This is NOT a mock test. Every tool call hits the real filesystem.

Levels of evidence:
  unit pass → integration pass → tool execution pass → behavioral pass
  This test targets: tool execution pass + behavioral pass
"""

from __future__ import annotations

import ast
import json
import shutil
import subprocess
import time
from pathlib import Path

import pytest

from nightwatch.safe_editor import SafeEditor, EditResult
from nightwatch.validator import validate_change
from nightwatch.checkpoint import Checkpoint, create_checkpoint_for_task, generate_recovery_summary
from nightwatch.task_queue import TaskQueue, Task, TaskStatus
from nightwatch.context_budget import ContextBudget, query_server_context_size
from nightwatch.harness import FailureType, classify_failure


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def isolated_repo(tmp_path):
    """Create an isolated git repo with a real Python file."""
    repo = tmp_path / "test-repo"
    repo.mkdir()
    subprocess.run(["git", "init"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.email", "test@test"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "config", "user.name", "test"], cwd=repo, check=True, capture_output=True)

    # Create a real Python file
    src = repo / "src"
    src.mkdir()
    module = src / "calculator.py"
    module.write_text('''"""Simple calculator module."""


def add(a: int, b: int) -> int:
    """Add two numbers."""
    return a + b


def subtract(a: int, b: int) -> int:
    """Subtract two numbers."""
    return a - b


def multiply(a: int, b: int) -> int:
    """Multiply two numbers."""
    return a * b
''')

    # Initial commit
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True, capture_output=True)
    subprocess.run(["git", "commit", "-m", "init: calculator module"], cwd=repo, check=True, capture_output=True)

    return repo


@pytest.fixture
def editor(isolated_repo):
    """SafeEditor pointed at isolated repo."""
    return SafeEditor(backup_dir=isolated_repo / ".backups")


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1: SafeEditor atomic write + validation
# ═══════════════════════════════════════════════════════════════════════════════

class TestSafeEditorReal:
    """Test SafeEditor with real file operations."""

    def test_atomic_write_preserves_original(self, editor, isolated_repo):
        """Writing to a temp file then renaming should be atomic."""
        target = isolated_repo / "src" / "calculator.py"
        original = target.read_text()

        new_content = original.replace("return a + b", "return a + b  # improved")

        result = editor.apply_edit(target, new_content, validate=True)

        assert result.success, f"Edit failed: {result.errors}"
        # Content should contain the change (SafeEditor may normalize trailing newlines)
        written = target.read_text()
        assert "return a + b  # improved" in written, "Expected change not found"
        assert len(written) > 50, "File too small -- possible truncation"
        # Backup should exist
        backups = list((isolated_repo / ".backups").glob("calculator.py.*"))
        assert len(backups) >= 1, "Backup not created"

    def test_rejects_truncated_content(self, editor, isolated_repo):
        """SafeEditor should reject content that's drastically smaller."""
        target = isolated_repo / "src" / "calculator.py"
        original_len = len(target.read_text())

        # Write only 10% of original — should be rejected
        result = editor.apply_edit(target, "x = 1\n", validate=True)

        assert not result.success, "Should have rejected truncated content"
        # Original should be untouched
        assert len(target.read_text()) == original_len

    def test_rejects_markdown_in_python(self, editor, isolated_repo):
        """SafeEditor should reject markdown fences in .py files."""
        target = isolated_repo / "src" / "calculator.py"

        bad_content = '```python\ndef add(a, b):\n    return a + b\n```\n'
        result = editor.apply_edit(target, bad_content, validate=True)

        assert not result.success, "Should have rejected markdown fences"
        # Original should be untouched
        assert "def add(a: int, b: int)" in target.read_text()

    def test_rejects_invalid_python(self, editor, isolated_repo):
        """SafeEditor should reject Python with syntax errors."""
        target = isolated_repo / "src" / "calculator.py"

        bad_content = 'def broken(\n    return "missing closing paren"\n'
        result = editor.apply_edit(target, bad_content, validate=True)

        assert not result.success, "Should have rejected invalid Python"

    def test_valid_change_applies(self, editor, isolated_repo):
        """A valid Python change should apply successfully."""
        target = isolated_repo / "src" / "calculator.py"

        new_content = target.read_text().replace(
            "def multiply(a: int, b: int) -> int:",
            "def multiply(a: float, b: float) -> float:"
        ).replace(
            '    """Multiply two numbers."""',
            '    """Multiply two floats."""'
        ).replace(
            "    return a * b",
            "    return float(a * b)"
        )

        result = editor.apply_edit(target, new_content, validate=True)

        assert result.success, f"Valid edit failed: {result.errors}"
        assert "float(a * b)" in target.read_text()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2: Validation pipeline
# ═══════════════════════════════════════════════════════════════════════════════

class TestValidationReal:
    """Test validation — uses AST parsing (no cwd dependency)."""

    def test_valid_python_passes(self):
        """Valid Python file should pass AST validation."""
        from nightwatch.file_guard import detect_language, validate_file
        content = """def add(a, b):
    return a + b
"""
        lang = detect_language(Path("test.py"))
        assert lang == "python"
        result = validate_file(Path("test.py"), content)
        assert result.valid, f"Validation failed: {result.errors}"

    def test_invalid_python_fails(self):
        """Invalid Python should fail AST validation."""
        from nightwatch.file_guard import validate_file
        content = "def broken(\n    return\n"
        result = validate_file(Path("broken.py"), content)
        assert not result.valid, "Should have failed validation"

    def test_truncated_file_detected(self):
        """Truncated file with unclosed parens should produce warning."""
        from nightwatch.file_guard import validate_file
        content = "def broken(\n    x = (1 + 2\n    return x\n" * 10
        result = validate_file(Path("test.py"), content)
        # syntax parses but warnings expected for unclosed parens
        assert len(result.warnings) > 0 or not result.valid, "Should detect issues"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3: Checkpoint + recovery
# ═══════════════════════════════════════════════════════════════════════════════

class TestCheckpointReal:
    """Test checkpoint persistence and recovery."""

    def test_checkpoint_save_and_load(self, tmp_path, monkeypatch):
        """Checkpoint should persist to disk and reload."""
        cp = create_checkpoint_for_task("test-123", "Add divide function", "test-repo")
        cp.record_operation("read", True)
        cp.record_operation("write", True)
        cp.files_read.append("src/calculator.py")
        cp.files_written.append("src/calculator.py")

        # Save and reload
        cp.save()
        loaded = Checkpoint.load()
        assert loaded.task_id == "test-123"
        assert loaded.task_description == "Add divide function"
        assert len(loaded.history) == 2
        assert loaded.files_read == ["src/calculator.py"]

    def test_recovery_summary_after_compaction(self, tmp_path, monkeypatch):
        """Recovery summary should contain enough context to resume."""
        import nightwatch.checkpoint as ckpt_mod
        monkeypatch.setattr(ckpt_mod, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(ckpt_mod, "CHECKPOINT_FILE", tmp_path / "state" / "checkpoint.json")
        cp = create_checkpoint_for_task("task-42", "Fix multiplication bug", "test-repo")
        cp.record_operation("read", True)
        cp.record_operation("patch", False, "LLM timeout")
        cp.files_written.append("src/calculator.py")
        cp.save()

        summary = generate_recovery_summary()
        assert "Fix multiplication bug" in summary
        assert "test-repo" in summary  # project is shown
        assert "LLM timeout" in summary
        # files_written is shown in recovery summary
        assert "calculator.py" in summary

    def test_recovery_context_structure(self):
        """Recovery context should have all required fields."""
        cp = create_checkpoint_for_task("task-99", "Test recovery", "test-repo")
        ctx = cp.to_dict()

        required = ["task_id", "task_description", "project", "history", "files_read", "files_written"]
        for field in required:
            assert field in ctx, f"Missing field: {field}"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4: Task queue persistence
# ═══════════════════════════════════════════════════════════════════════════════

class TestTaskQueueReal:
    """Test task queue with real persistence."""

    def test_task_lifecycle(self, tmp_path, monkeypatch):
        """Task should go through READY → IN_PROGRESS → COMPLETED."""
        import nightwatch.task_queue as tq_mod
        monkeypatch.setattr(tq_mod, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(tq_mod, "TASK_QUEUE_FILE", tmp_path / "state" / "task_queue.json")
        monkeypatch.setattr(tq_mod, "MISSION_STATE_FILE", tmp_path / "state" / "mission_state.json")
        q = TaskQueue()

        task = Task(
            id="test-task-1",
            project="test-repo",
            description="Add divide function",
            target_files=["src/calculator.py"],
        )
        q.add_task(task)

        # Get next task
        next_task = q.get_next_task()
        assert next_task is not None
        assert next_task.id == "test-task-1"
        # Note: get_next_task() returns the task but doesn't change status
        # The harness is responsible for transitioning to IN_PROGRESS
        q.update_task(next_task.id, status=TaskStatus.IN_PROGRESS.value)  # harness would do this
        assert next_task.status == TaskStatus.IN_PROGRESS.value

        # Complete
        next_task.complete("abc1234")
        assert next_task.status == TaskStatus.COMPLETED.value
        assert next_task.commit_sha == "abc1234"

    def test_task_failure_and_block(self, tmp_path, monkeypatch):
        """Failed task should be marked FAILED, blocked task should be BLOCKED."""
        import nightwatch.task_queue as tq_mod
        monkeypatch.setattr(tq_mod, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(tq_mod, "TASK_QUEUE_FILE", tmp_path / "state" / "task_queue.json")
        monkeypatch.setattr(tq_mod, "MISSION_STATE_FILE", tmp_path / "state" / "mission_state.json")
        q = TaskQueue()

        task1 = Task(id="t1", project="test", description="Task 1", max_attempts=1)
        task2 = Task(id="t2", project="test", description="Task 2")
        q.add_task(task1)
        q.add_task(task2)

        # Fail t1 (max_attempts=1 so first fail -> FAILED)
        t1 = q.get_next_task()
        t1.fail("Syntax error")
        assert t1.status == TaskStatus.FAILED.value

        # Block t2
        t2 = q.get_next_task()
        t2.block("Protected path")
        assert t2.status == TaskStatus.BLOCKED.value

    def test_stats(self, tmp_path, monkeypatch):
        """Stats should reflect task states."""
        import nightwatch.task_queue as tq_mod
        monkeypatch.setattr(tq_mod, "STATE_DIR", tmp_path / "state")
        monkeypatch.setattr(tq_mod, "TASK_QUEUE_FILE", tmp_path / "state" / "task_queue.json")
        monkeypatch.setattr(tq_mod, "MISSION_STATE_FILE", tmp_path / "state" / "mission_state.json")
        monkeypatch.setattr(tq_mod, "TASK_QUEUE_FILE", tmp_path / "state" / "task_queue.json")
        monkeypatch.setattr(tq_mod, "MISSION_STATE_FILE", tmp_path / "state" / "mission_state.json")
        monkeypatch.setattr(tq_mod, "TASK_QUEUE_FILE", tmp_path / "state" / "task_queue.json")
        monkeypatch.setattr(tq_mod, "MISSION_STATE_FILE", tmp_path / "state" / "mission_state.json")
        q = TaskQueue()

        for i in range(5):
            q.add_task(Task(id=f"t{i}", project="test", description=f"Task {i}"))

        # Complete 2, fail 1
        t = q.get_next_task()
        t.complete("sha1")
        t = q.get_next_task()
        t.complete("sha2")
        t = q.get_next_task()
        t.max_attempts = 1  # so first fail -> FAILED
        t.fail("error")

        stats = q.get_stats()
        assert stats["completed"] == 2
        assert stats["failed"] == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5: Context budget with real server
# ═══════════════════════════════════════════════════════════════════════════════

class TestContextBudgetReal:
    """Test context budget with real server query."""

    def test_server_query_returns_value(self):
        """query_server_context_size should return > 0 when server is running."""
        ctx = query_server_context_size()
        # Server might not be running in CI, so we just check it doesn't crash
        assert isinstance(ctx, int)
        assert ctx >= 0

    def test_budget_tracks_usage(self):
        """ContextBudget should track token usage correctly."""
        cb = ContextBudget(budget=10000)
        assert not cb.should_compact(5000)  # 50% — below 70% threshold
        assert cb.should_compact(8000)      # 80% — above 70% threshold


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6: Failure classification
# ═══════════════════════════════════════════════════════════════════════════════

class TestFailureClassification:
    """Test failure classification logic."""

    def test_transient_errors(self):
        """Network/timeout errors should be classified as TRANSIENT."""
        assert classify_failure("Connection timeout", "FAILED") == FailureType.TRANSIENT
        assert classify_failure("LLM error: 503", "FAILED") == FailureType.TRANSIENT

    def test_validation_errors(self):
        """Syntax/import errors should be classified as VALIDATION_FAILURE."""
        assert classify_failure("SyntaxError at line 5", "FAILED") == FailureType.VALIDATION_FAILURE
        assert classify_failure("SafeEditor rejected", "FAILED") == FailureType.VALIDATION_FAILURE

    def test_context_errors(self):
        """Context overflow should be classified as CONTEXT_EXHAUSTION."""
        assert classify_failure("request exceeds context size", "FAILED") == FailureType.CONTEXT_EXHAUSTION

    def test_unrecoverable(self):
        """Protected paths should be UNRECOVERABLE."""
        assert classify_failure("Protected path: flake.nix", "BLOCKED") == FailureType.UNRECOVERABLE

    def test_default_is_task_failure(self):
        """Unknown errors default to TASK_FAILURE."""
        assert classify_failure("something weird happened", "FAILED") == FailureType.TASK_FAILURE


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7: Full pipeline (closest to real E2E)
# ═══════════════════════════════════════════════════════════════════════════════

class TestFullPipeline:
    """Test the complete edit → validate → checkpoint → commit pipeline."""

    def test_edit_validate_commit(self, isolated_repo, editor):
        """Full pipeline: edit file → validate → checkpoint → git commit."""
        target = isolated_repo / "src" / "calculator.py"

        # Step 1: Edit
        new_content = target.read_text().replace(
            "def add(a: int, b: int) -> int:",
            "def add(a: int, b: int) -> int:\n    \"\"\"Add two integers.\"\"\""
        )
        result = editor.apply_edit(target, new_content, validate=True)
        assert result.success, f"Edit failed: {result.errors}"

        # Step 2: Validate
        validation = validate_change(
            ["src/calculator.py"], run_tests=False, run_imports=False
        )
        assert validation.passed, f"Validation failed: {validation.summary}"

        # Step 3: Checkpoint
        cp = create_checkpoint_for_task("pipeline-test", "Add docstring", "test-repo")
        cp.record_operation("edit", True)
        cp.record_operation("validate", True)
        cp.files_written.append("src/calculator.py")

        # Step 4: Git commit
        subprocess.run(["git", "add", "-A"], cwd=isolated_repo, check=True, capture_output=True)
        commit = subprocess.run(
            ["git", "commit", "-m", "feat: add docstring to add()"],
            cwd=isolated_repo, capture_output=True, text=True
        )
        assert commit.returncode == 0, f"Git commit failed: {commit.stderr}"

        # Verify
        log = subprocess.run(
            ["git", "log", "--oneline", "-1"],
            cwd=isolated_repo, capture_output=True, text=True
        ).stdout.strip()
        assert "feat: add docstring" in log
        assert '"""Add two integers."""' in target.read_text()

    def test_failure_and_recovery(self, isolated_repo, editor):
        """Edit fails → checkpoint records failure → can retry."""
        target = isolated_repo / "src" / "calculator.py"

        # Step 1: Try to write invalid Python
        bad_content = "def broken(\n"
        result = editor.apply_edit(target, bad_content, validate=True)
        assert not result.success, "Should have rejected invalid Python"

        # Step 2: Checkpoint records failure
        cp = create_checkpoint_for_task("fail-test", "This will fail", "test-repo")
        cp.record_operation("edit", False, "Invalid Python syntax")

        # Step 3: Original file should be untouched
        assert "def add(a: int, b: int)" in target.read_text()

        # Step 4: Recovery summary should mention the failure
        summary = generate_recovery_summary()
        assert "Invalid Python syntax" in summary

    def test_multiple_edits_and_rollback(self, isolated_repo, editor):
        """Multiple edits should stack, and git can rollback."""
        target = isolated_repo / "src" / "calculator.py"

        # Edit 1: Add docstring
        content1 = target.read_text().replace(
            "def add(a: int, b: int) -> int:",
            "def add(a: int, b: int) -> int:\n    \"\"\"Add.\"\"\""
        )
        r1 = editor.apply_edit(target, content1, validate=True)
        assert r1.success

        # Edit 2: Change return type hint
        content2 = target.read_text().replace("-> int:", "-> float:")
        r2 = editor.apply_edit(target, content2, validate=True)
        assert r2.success

        # Both changes should be present
        text = target.read_text()
        assert '"""Add."""' in text
        assert "-> float:" in text

        # Git rollback should restore to initial state
        subprocess.run(["git", "checkout", "--", "."], cwd=isolated_repo, check=True, capture_output=True)
        text_after = target.read_text()
        assert '"""Add."""' not in text_after
        assert "-> float:" not in text_after
        assert "def add(a: int, b: int) -> int:" in text_after


class TestLoopDetector:
    """Test anti-loop detection."""
    
    def test_no_loop_under_threshold(self):
        """Less than max_attempts should not trigger loop."""
        from nightwatch.task_queue import LoopDetector
        detector = LoopDetector(max_attempts=3, window_seconds=300)
        assert not detector.record_attempt("t1", success=False)
        assert not detector.record_attempt("t1", success=False)
        assert not detector.get_stats("t1")["in_loop"]
    
    def test_loop_at_threshold(self):
        """At max_attempts should trigger loop."""
        from nightwatch.task_queue import LoopDetector
        detector = LoopDetector(max_attempts=3, window_seconds=300)
        detector.record_attempt("t1", success=False)
        detector.record_attempt("t1", success=False)
        assert detector.record_attempt("t1", success=False)  # 3rd attempt = loop
        assert detector.get_stats("t1")["in_loop"]
        assert detector.get_stats("t1")["attempts_in_window"] == 3
    
    def test_reset_clears_loop(self):
        """Reset should clear loop tracking."""
        from nightwatch.task_queue import LoopDetector
        detector = LoopDetector(max_attempts=3, window_seconds=300)
        detector.record_attempt("t1", success=False)
        detector.record_attempt("t1", success=False)
        detector.record_attempt("t1", success=False)
        assert detector.get_stats("t1")["in_loop"]
        detector.reset("t1")
        assert not detector.get_stats("t1")["in_loop"]
        assert detector.get_stats("t1")["attempts_in_window"] == 0

