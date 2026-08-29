"""E2E tests for long-run autonomy and multi-project isolation.

Tests:
- Multi-project task isolation
- Checkpoint/recovery across projects
- Context budget tracking
- Task dependency ordering
- Stuck task recovery
- Project switching
"""

from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import time
from pathlib import Path

import pytest


REPO_ROOT = Path.home() / "projects" / "nixos-ai"
STATE_DIR = Path.home() / ".local/state/jarvis/nightwatch"


@pytest.fixture
def temp_workspace(tmp_path):
    """Create a temporary workspace with two mock projects."""
    # Create project A
    proj_a = tmp_path / "project-a"
    proj_a.mkdir()
    (proj_a / ".git").mkdir()
    (proj_a / "main.py").write_text('def hello():\n    return "a"\n')
    (proj_a / "test_main.py").write_text('from main import hello\n\ndef test_hello():\n    assert hello() == "a"\n')
    
    # Create project B
    proj_b = tmp_path / "project-b"
    proj_b.mkdir()
    (proj_b / ".git").mkdir()
    (proj_b / "utils.py").write_text('def helper():\n    return "b"\n')
    (proj_b / "test_utils.py").write_text('from utils import helper\n\ndef test_helper():\n    assert helper() == "b"\n')
    
    return {"a": proj_a, "b": proj_b, "root": tmp_path}


class TestMultiProjectIsolation:
    """Test that projects are properly isolated."""
    
    def test_project_path_validation(self, temp_workspace):
        """Validate that paths are scoped to their project."""
        from nightwatch.project_isolation import validate_project_path, get_project_root
        from unittest.mock import patch
        
        # Mock get_project_root to return our temp paths
        def mock_get_root(name):
            if name == "project-a":
                return temp_workspace["a"]
            return None
        
        with patch("nightwatch.project_isolation.get_project_root", mock_get_root):
            # Path within project A should be valid for project A
            path_a = str(temp_workspace["a"] / "main.py")
            ok, msg = validate_project_path(path_a, "project-a")
            assert ok, f"Expected valid: {msg}"
            
            # Path from project B should be INVALID for project A
            path_b = str(temp_workspace["b"] / "utils.py")
            ok, msg = validate_project_path(path_b, "project-a")
            assert not ok, f"Expected invalid: {msg}"
    
    def test_project_registry(self, temp_workspace):
        """Test project registry tracks state per project."""
        from nightwatch.project_isolation import ProjectRegistry, ProjectConfig
        
        registry = ProjectRegistry()
        
        # Register two projects
        config_a = ProjectConfig(name="test-a", root=temp_workspace["a"])
        config_b = ProjectConfig(name="test-b", root=temp_workspace["b"])
        registry.register(config_a)
        registry.register(config_b)
        
        # Update state for each
        registry.update_state("test-a", tasks_completed=5, commits=["abc123"])
        registry.update_state("test-b", tasks_completed=3, commits=["def456"])
        
        # Verify isolation
        state_a = registry.get_state("test-a")
        state_b = registry.get_state("test-b")
        assert state_a is not None
        assert state_b is not None
        assert state_a.tasks_completed == 5
        assert state_b.tasks_completed == 3
        assert state_a.commits == ["abc123"]
        assert state_b.commits == ["def456"]
    
    def test_run_in_project(self, temp_workspace):
        """Test that commands run in the correct project directory."""
        from nightwatch.project_isolation import run_in_project
        
        result = run_in_project(
            ["pwd"],
            temp_workspace["a"],
        )
        assert temp_workspace["a"].name in result.stdout
    
    def test_discover_projects(self, temp_workspace):
        """Test auto-discovery of projects."""
        from nightwatch.project_isolation import discover_projects
        
        projects = discover_projects(temp_workspace["root"])
        names = {p.name for p in projects}
        assert "project-a" in names
        assert "project-b" in names


class TestCheckpointRecovery:
    """Test checkpoint and recovery mechanisms."""
    
    def test_checkpoint_save_load(self):
        """Test that checkpoints survive save/load cycle."""
        from nightwatch.checkpoint import Checkpoint
        
        cp = Checkpoint(
            task_id="test-123",
            task_description="Test recovery",
            project="test-project",
        )
        cp.record_operation("read_file", True)
        cp.record_operation("write_file", True)
        cp.record_llm_call(500)
        cp.record_tool_call()
        cp.set_recovery_state("files_read", ["a.py", "b.py"])
        
        # Save
        cp.save()
        
        # Load fresh
        cp2 = Checkpoint.load()
        assert cp2.task_id == "test-123"
        assert cp2.task_description == "Test recovery"
        assert cp2.total_llm_calls == 1
        assert cp2.total_tool_calls == 1
        assert cp2.get_recovery_state("files_read") == ["a.py", "b.py"]
        
        # Clean up
        cp.clear()
    
    def test_context_compaction_recording(self):
        """Test that context compaction events are recorded."""
        from nightwatch.checkpoint import Checkpoint
        
        cp = Checkpoint(task_id="ctx-test", task_description="Context test")
        cp.record_compaction(8000, 2000, reason="auto-compact")
        cp.record_compaction(6000, 1500, reason="manual")
        
        stats = cp.get_context_stats()
        assert stats["total_compactions"] == 2
        assert stats["compaction_events"] == 2
        assert stats["total_llm_calls"] == 0
        
        cp.clear()
    
    def test_stuck_task_recovery(self):
        """Test that stuck IN_PROGRESS tasks are recovered."""
        from nightwatch.task_queue import TaskQueue, Task, TaskStatus
        
        q = TaskQueue()
        
        # Add a task with unique description
        unique_desc = f"Stuck task {int(time.time())}"
        task = Task(
            id="stuck-test",
            project="test",
            description=unique_desc,
            status=TaskStatus.READY.value,
        )
        q.add_task(task)
        
        # Now mark it IN_PROGRESS
        q.update_task("stuck-test", status=TaskStatus.IN_PROGRESS.value)
        
        # Manually set updated_at to long ago
        for t in q._tasks:
            if t.id == "stuck-test":
                t.updated_at = time.time() - 7200  # 2 hours ago
        q._save()
        
        # Recover
        recovered = q.recover_stuck_tasks(max_age_seconds=3600)
        assert recovered >= 1
        
        # Verify task is now READY
        task = q.get_task("stuck-test")
        assert task is not None
        assert task.status == TaskStatus.READY.value


class TestContextBudget:
    """Test context budget tracking."""
    
    def test_budget_tracking(self):
        """Test that context budget tracks usage correctly."""
        from nightwatch.context_budget import ContextBudget
        
        budget = ContextBudget(budget=8192)
        
        # Record some snapshots
        budget.record_snapshot(1000, phase="discovery")
        budget.record_tool_call()
        budget.record_tool_call()
        budget.record_snapshot(3000, phase="execution")
        budget.record_tool_call()
        budget.record_tool_call()
        budget.record_tool_call()
        budget.record_snapshot(5000, phase="validation")
        budget.record_tool_call()
        budget.record_tool_call()
        budget.record_tool_call()
        
        stats = budget.get_stats()
        assert stats["snapshots"] == 3
        assert stats["total_tool_calls"] == 8
        assert stats["max_tokens"] == 5000
        
        # Should not compact yet
        assert not budget.should_compact(5000)
        
        # Should compact at 80%
        assert budget.should_compact(7000)
    
    def test_compaction_recording(self):
        """Test compaction events are tracked."""
        from nightwatch.context_budget import ContextBudget
        
        budget = ContextBudget(budget=8192)
        budget.record_snapshot(7500)
        budget.record_compaction(7500, 2000)
        
        stats = budget.get_stats()
        assert stats["total_compactions"] == 1
    
    def test_recommendation(self):
        """Test context management recommendations."""
        from nightwatch.context_budget import ContextBudget
        
        budget = ContextBudget(budget=8192)
        
        # Low usage
        rec = budget.get_recommendation(2000)
        assert rec["urgency"] == "low"
        assert rec["action"] == "continue"
        
        # Medium usage (60-80%)
        rec = budget.get_recommendation(5500)
        assert rec["urgency"] == "medium"
        assert rec["action"] == "monitor"
        
        # High usage (80-90%)
        rec = budget.get_recommendation(6800)
        assert rec["urgency"] == "high"
        assert rec["action"] == "compact"
        
        # Critical usage (>90%)
        rec = budget.get_recommendation(8000)
        assert rec["urgency"] == "critical"
        assert rec["action"] == "compact_aggressively"
    
    def test_serialization(self):
        """Test context budget can be serialized/deserialized."""
        from nightwatch.context_budget import ContextBudget
        
        budget = ContextBudget(budget=16384)
        budget.record_snapshot(5000, phase="test")
        budget.record_llm_call(500)
        
        data = budget.to_dict()
        budget2 = ContextBudget.from_dict(data)
        
        assert budget2.budget == 16384
        assert budget2.total_tokens_processed == 5500  # 5000 from snapshot + 500 from llm call
        assert budget2.total_llm_calls == 1


class TestTaskDependencies:
    """Test task dependency ordering across projects."""
    
    def test_dependency_ordering(self):
        """Test that tasks respect dependencies."""
        from nightwatch.task_queue import TaskQueue, Task, TaskStatus
        
        q = TaskQueue()
        
        # Create tasks with dependencies
        task_a = Task(
            id="dep-a", project="test", description="Task A",
            status=TaskStatus.READY.value, priority=1,
        )
        task_b = Task(
            id="dep-b", project="test", description="Task B",
            status=TaskStatus.READY.value, priority=1,
            dependencies=["dep-a"],  # B depends on A
        )
        task_c = Task(
            id="dep-c", project="test", description="Task C",
            status=TaskStatus.READY.value, priority=1,
        )
        
        q.add_task(task_b)  # Add B first
        q.add_task(task_a)  # Add A second
        q.add_task(task_c)  # Add C third
        
        # Next task should be A or C (not B, which depends on A)
        next_task = q.get_next_task()
        assert next_task is not None
        assert next_task.id != "dep-b"  # B should not be first


class TestMultiProjectE2E:
    """End-to-end test of multi-project execution."""
    
    def test_harness_discovers_multiple_projects(self):
        """Test that harness discovers and manages multiple projects."""
        from nightwatch.harness import Harness, HarnessConfig
        
        config = HarnessConfig(
            projects=["nixos-ai"],
            max_tasks=1,
            max_minutes=1,
            dry_run=True,
            telegram_notifications=False,
            use_llm_discovery=False,
        )
        harness = Harness(config=config)
        
        # Should discover nixos-ai
        assert "nixos-ai" in harness.config.projects
        
        # Should be able to discover tasks
        tasks = harness.discover_tasks()
        assert len(tasks) > 0
        
        # All tasks should be for the correct project
        for task in tasks:
            assert task.project in harness.config.projects
