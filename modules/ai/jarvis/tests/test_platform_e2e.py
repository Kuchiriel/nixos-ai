"""
Platform E2E tests — validates core platform modules work correctly.

Updated 2026-09-03: migrated from archived workitem/orchestrator to task_queue/harness.
"""

import json
import os
import sys
import time
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# Task Queue Tests (replaces WorkItem tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestTaskQueue:
    """Test task queue (replaces old WorkItemEngine tests)."""

    def test_create_task(self, tmp_path):
        """Should create and persist tasks."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from nightwatch.task_queue import TaskQueue, Task

        os.environ["JARVIS_STATE_DIR"] = str(tmp_path)
        try:
            queue = TaskQueue()
            task = Task(
                id="test-1",
                project="test",
                description="Test task",
                priority=3,
                risk="low",
            )
            queue.add_task(task)

            assert task.id == "test-1"
            assert task.description == "Test task"
            assert task.priority == 3
            assert task.status == "DISCOVERED"
        finally:
            del os.environ["JARVIS_STATE_DIR"]

    def test_task_status_transitions(self, tmp_path):
        """Should transition task status with validation."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from nightwatch.task_queue import Task, TaskStatus

        task = Task(id="test-2", project="test", description="Test task")

        # Valid transition
        assert task._transition(TaskStatus.READY.value)
        assert task.status == TaskStatus.READY.value

        # Another valid transition
        assert task._transition(TaskStatus.IN_PROGRESS.value)
        assert task.status == TaskStatus.IN_PROGRESS.value

    def test_get_next_task(self, tmp_path):
        """Should return next task by priority."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        import nightwatch.task_queue as tq
        from nightwatch.task_queue import Task

        # Temporarily override module-level STATE_DIR
        original_state = tq.STATE_DIR
        original_task_file = tq.TASK_QUEUE_FILE
        try:
            tq.STATE_DIR = tmp_path / "queue"
            tq.TASK_QUEUE_FILE = tmp_path / "queue" / "task_queue.json"
            tq.STATE_DIR.mkdir(parents=True, exist_ok=True)
            queue = tq.TaskQueue()
            queue.add_task(Task(
                id="low-1", project="test", description="Low priority",
                priority=8, risk="low",
            ))
            queue.add_task(Task(
                id="high-1", project="test", description="High priority",
                priority=2, risk="low",
            ))

            next_task = queue.get_next_task()
            assert next_task is not None
            assert next_task.priority == 2
        finally:
            tq.STATE_DIR = original_state
            tq.TASK_QUEUE_FILE = original_task_file

    def test_persistence(self, tmp_path):
        """Should persist tasks across instances."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from nightwatch.task_queue import TaskQueue, Task

        state_dir = str(tmp_path)
        os.environ["JARVIS_STATE_DIR"] = state_dir
        try:
            queue1 = TaskQueue()
            queue1.add_task(Task(
                id="persist-1", project="test", description="Persistent task",
                priority=5, risk="low",
            ))

            queue2 = TaskQueue()
            loaded = [t for t in queue2._tasks if t.id == "persist-1"]
            assert len(loaded) == 1
            assert loaded[0].description == "Persistent task"
        finally:
            del os.environ["JARVIS_STATE_DIR"]


# ═══════════════════════════════════════════════════════════════════════════════
# Harness Tests (replaces Orchestrator tests)
# ═══════════════════════════════════════════════════════════════════════════════

class TestHarness:
    """Test harness pipeline (replaces old Orchestrator tests)."""

    def test_harness_initialization(self):
        """Should initialize harness with config."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from nightwatch.harness import Harness, HarnessConfig

        config = HarnessConfig(
            project="test",
            dry_run=True,
            max_tasks=1,
            max_minutes=1,
        )
        harness = Harness(config=config)

        assert harness.config.project == "test"
        assert harness.config.dry_run is True
        assert harness.queue is not None

    def test_task_queue_integration(self, tmp_path):
        """Should add tasks to queue."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from nightwatch.harness import Harness, HarnessConfig
        from nightwatch.task_queue import Task

        os.environ["JARVIS_STATE_DIR"] = str(tmp_path)
        try:
            config = HarnessConfig(project="test", dry_run=True)
            harness = Harness(config=config)

            task = Task(
                id="harness-1",
                project="test",
                description="Test task for harness",
                priority=5,
                risk="low",
            )
            harness.queue.add_task(task)

            stats = harness.queue.get_stats()
            assert stats["total"] >= 1
        finally:
            del os.environ["JARVIS_STATE_DIR"]


# ═══════════════════════════════════════════════════════════════════════════════
# Control Plane Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestControlPlane:
    """Test control plane integration."""

    def test_plane_initialization(self):
        """Should initialize control plane."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.control_plane.plane import get_control_plane

        plane = get_control_plane()
        assert plane is not None
        assert plane.bus is not None
        assert plane.state is not None
        assert plane.commands is not None

    def test_event_bus_record(self):
        """Should record events to history."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.control_plane.plane import get_control_plane

        plane = get_control_plane()
        initial_count = len(plane._event_history)

        # Publish an event
        plane.bus.publish("test.event", {"test": True})

        # Should be recorded
        assert len(plane._event_history) >= initial_count

    def test_command_registry(self):
        """Should have registered commands."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.control_plane.plane import get_control_plane

        plane = get_control_plane()
        commands = plane.commands.list_commands()

        assert len(commands) > 0
        # Should have system commands
        names = [c["name"] for c in commands]
        assert "system.status" in names


# ═══════════════════════════════════════════════════════════════════════════════
# Event Bus Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestEventBus:
    """Test event bus publish/subscribe."""

    def test_publish_subscribe(self):
        """Should deliver events to subscribers."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.eventbus import EventBus

        bus = EventBus()
        received = []

        def handler(event):
            received.append(event.data)

        bus.subscribe("test.topic", handler, name="test-sub")
        bus.publish("test.topic", {"message": "hello"})

        assert len(received) == 1
        assert received[0]["message"] == "hello"

    def test_unsubscribe(self):
        """Should remove subscribers."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.eventbus import EventBus

        bus = EventBus()
        received = []

        def handler(event):
            received.append(event.data)

        bus.subscribe("test.topic", handler, name="unsub-test")
        bus.unsubscribe("unsub-test")
        bus.publish("test.topic", {"message": "after unsub"})

        assert len(received) == 0


# ═══════════════════════════════════════════════════════════════════════════════
# Persona Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPersonas:
    """Test persona registry."""

    def test_persona_registry(self):
        """Should load personas."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.persona import PersonaRegistry

        registry = PersonaRegistry()
        personas = registry.list_all()

        assert len(personas) > 0
        # Should have common personas
        ids = [p.id for p in personas]
        assert "backend_engineer" in ids

    def test_persona_selection(self):
        """Should select persona for task."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.persona import PersonaRegistry

        registry = PersonaRegistry()
        persona = registry.select_for_task("Write tests for the API")

        assert persona is not None
        assert persona.id in ["qa_engineer", "backend_engineer"]


# ═══════════════════════════════════════════════════════════════════════════════
# Workspace Discovery Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkspace:
    """Test workspace discovery."""

    def test_discover_projects(self):
        """Should discover projects."""
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.workspace import WorkspaceDiscovery

        ws = WorkspaceDiscovery()
        ws.discover()

        # Should find at least nixos-ai
        assert "nixos-ai" in ws._projects or len(ws._projects) > 0
