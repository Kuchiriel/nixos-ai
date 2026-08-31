"""E2E tests for the Agent Platform.

Tests the full pipeline:
- Workspace discovery
- Persona selection
- Work item creation and management
- Task decomposition via orchestrator
- Context assembly
- Model policy routing
- Platform bridge integration

No mocks — real tool calls through the full pipeline.
"""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from pathlib import Path

import pytest


# ═══════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.fixture
def isolated_workspace(tmp_path):
    """Create an isolated workspace with fake projects for testing."""
    workspace = tmp_path / "projects"
    workspace.mkdir()

    # Create project A (Python)
    proj_a = workspace / "project-a"
    proj_a.mkdir()
    (proj_a / "pyproject.toml").write_text('[project]\nname = "project-a"\n')
    (proj_a / "README.md").write_text("# Project A\nA test project.\n")
    (proj_a / "AGENTS.md").write_text("# AGENTS.md\nProject A instructions.\n")
    (proj_a / "src").mkdir()
    (proj_a / "src" / "__init__.py").write_text("")
    (proj_a / "src" / "main.py").write_text("def hello(): return 'world'\n")
    (proj_a / "tests").mkdir()
    (proj_a / "tests" / "test_main.py").write_text("def test_hello(): assert True\n")

    # Create project B (Nix)
    proj_b = workspace / "project-b"
    proj_b.mkdir()
    (proj_b / "flake.nix").write_text("{ description = \"Project B\"; }\n")
    (proj_b / "README.md").write_text("# Project B\nA nix project.\n")
    (proj_b / "default.nix").write_text("{ pkgs ? import <nixpkgs> {} }: pkgs.stdenv.mkDerivation {}\n")

    # Create project C (depends on A)
    proj_c = workspace / "project-c"
    proj_c.mkdir()
    (proj_c / "README.md").write_text("# Project C\nDepends on project-a.\n")
    (proj_c / "src").mkdir()
    (proj_c / "src" / "app.py").write_text("from project_a import hello\nprint(hello())\n")

    return workspace


# ═══════════════════════════════════════════════════════════════════════════════
# Workspace Discovery Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkspaceDiscovery:
    """Test workspace project discovery."""

    def test_discover_projects(self, isolated_workspace):
        """Should discover all projects in workspace."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.workspace import WorkspaceDiscovery

        ws = WorkspaceDiscovery(str(isolated_workspace))
        projects = ws.discover()

        assert len(projects) == 3
        assert "project-a" in projects
        assert "project-b" in projects
        assert "project-c" in projects

    def test_project_metadata(self, isolated_workspace):
        """Should detect project metadata correctly."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.workspace import WorkspaceDiscovery

        ws = WorkspaceDiscovery(str(isolated_workspace))
        ws.discover()

        proj_a = ws._projects["project-a"]
        assert proj_a.manifest.type == "python"
        assert proj_a.has_agents_md is True
        assert proj_a.has_readme is True
        assert "python" in proj_a.languages

    def test_dependency_graph(self, isolated_workspace):
        """Should build dependency graph from imports."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.workspace import WorkspaceDiscovery

        ws = WorkspaceDiscovery(str(isolated_workspace))
        ws.discover()

        # project-c imports from project-a
        deps = ws._dependency_graph.get("project-c", [])
        assert "project-a" in deps

    def test_affected_projects(self, isolated_workspace):
        """Should detect affected projects from file changes."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.workspace import WorkspaceDiscovery

        ws = WorkspaceDiscovery(str(isolated_workspace))
        ws.discover()

        affected = ws.get_affected_projects(["project-a/src/main.py"])
        assert "project-a" in affected

    def test_save_and_load(self, isolated_workspace):
        """Should persist and reload workspace state."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.workspace import WorkspaceDiscovery

        ws = WorkspaceDiscovery(str(isolated_workspace))
        ws.discover()
        save_path = str(isolated_workspace / "workspace.json")
        ws.save(save_path)

        # Load in new instance
        ws2 = WorkspaceDiscovery(str(isolated_workspace))
        assert ws2.load(save_path)
        assert len(ws2._projects) == 3

    def test_project_context(self, isolated_workspace):
        """Should return project context with AGENTS.md."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.workspace import WorkspaceDiscovery

        ws = WorkspaceDiscovery(str(isolated_workspace))
        ws.discover()

        ctx = ws.get_project_context("project-a")
        assert "manifest" in ctx
        assert "agents_md" in ctx
        assert "Project A instructions" in ctx["agents_md"]


# ═══════════════════════════════════════════════════════════════════════════════
# Persona Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPersonas:
    """Test persona registry."""

    def test_builtin_personas(self):
        """Should have 10 built-in personas."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.persona import PersonaRegistry

        reg = PersonaRegistry()
        personas = reg.list_all()
        assert len(personas) == 10

    def test_select_nixos_persona(self):
        """Should select NixOS engineer for nix tasks."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.persona import PersonaRegistry

        reg = PersonaRegistry()
        persona = reg.select_for_task("fix the nixos configuration")
        assert persona.id == "nixos_engineer"

    def test_select_qa_persona(self):
        """Should select QA engineer for test tasks."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.persona import PersonaRegistry

        reg = PersonaRegistry()
        persona = reg.select_for_task("write unit tests for the parser")
        assert persona.id == "qa_engineer"

    def test_select_researcher_persona(self):
        """Should select researcher for research tasks."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.persona import PersonaRegistry

        reg = PersonaRegistry()
        persona = reg.select_for_task("research best practices for monorepo")
        assert persona.id == "researcher"

    def test_persona_has_tools(self):
        """Personas should have tool lists."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.persona import PersonaRegistry

        reg = PersonaRegistry()
        for persona in reg.list_all():
            assert len(persona.tools) > 0


# ═══════════════════════════════════════════════════════════════════════════════
# Work Item Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestWorkItems:
    """Test work item engine."""

    def test_create_work_item(self, tmp_path):
        """Should create and persist work items."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.workitem import WorkItemEngine

        engine = WorkItemEngine(str(tmp_path / "work"))
        item = engine.create(project="test", title="Test task", priority="high")

        assert item.id
        assert item.title == "Test task"
        assert item.priority == "high"
        assert item.status == "backlog"

    def test_transition_status(self, tmp_path):
        """Should transition status with audit trail."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.workitem import WorkItemEngine

        engine = WorkItemEngine(str(tmp_path / "work"))
        item = engine.create(project="test", title="Test task")

        engine.transition(item.id, "in_progress", "Starting work")
        updated = engine.get(item.id)
        assert updated.status == "in_progress"
        assert len(updated.history) == 1
        assert updated.history[0]["from"] == "backlog"
        assert updated.history[0]["to"] == "in_progress"

    def test_get_next_task(self, tmp_path):
        """Should return next task by priority."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.workitem import WorkItemEngine

        engine = WorkItemEngine(str(tmp_path / "work"))
        engine.create(project="test", title="Low task", priority="low")
        engine.create(project="test", title="High task", priority="high")

        next_task = engine.get_next_task()
        assert next_task.title == "High task"

    def test_wip_limits(self, tmp_path):
        """Should track WIP limits."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.workitem import WorkItemEngine

        engine = WorkItemEngine(str(tmp_path / "work"))
        for i in range(5):
            item = engine.create(project="test", title=f"Task {i}")
            engine.transition(item.id, "in_progress")

        wip = engine.check_wip_limits()
        assert wip["counts"]["in_progress"] == 5
        # WIP limit is 3, so should have violation
        assert "in_progress" in wip["violations"]

    def test_persistence(self, tmp_path):
        """Should persist work items across instances."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.workitem import WorkItemEngine

        state_dir = str(tmp_path / "work")
        engine1 = WorkItemEngine(state_dir)
        item = engine1.create(project="test", title="Persistent task")

        engine2 = WorkItemEngine(state_dir)
        loaded = engine2.get(item.id)
        assert loaded is not None
        assert loaded.title == "Persistent task"


# ═══════════════════════════════════════════════════════════════════════════════
# Orchestrator Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestOrchestrator:
    """Test orchestrator task decomposition and dispatch."""

    def test_decompose_task(self, tmp_path):
        """Should decompose task into work items."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.orchestrator import Orchestrator

        orch = Orchestrator(state_dir=str(tmp_path / "orch"))
        items = orch.decompose_task("Fix the bug", project_id="test")

        assert len(items) > 0
        # Should have stages from bugfix workflow
        titles = [i.title for i in items]
        assert any("reproduce" in t for t in titles)
        assert any("diagnose" in t for t in titles)

    def test_select_workflow(self, tmp_path):
        """Should select appropriate workflow for task type."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.orchestrator import Orchestrator

        orch = Orchestrator(state_dir=str(tmp_path / "orch"))

        # Bug should use bugfix workflow
        items = orch.decompose_task("Fix the crash bug", project_id="test")
        assert any("bugfix" in str(i.tags) for i in items)

        # Feature should use feature-development workflow
        items = orch.decompose_task("Implement new feature X", project_id="test")
        assert any("feature-development" in str(i.tags) for i in items)

    def test_assign_task(self, tmp_path):
        """Should assign task to persona."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.orchestrator import Orchestrator

        orch = Orchestrator(state_dir=str(tmp_path / "orch"))
        items = orch.decompose_task("Fix bug", project_id="test")

        agent = orch.assign_task(items[0].id, "backend_engineer")
        assert agent is not None
        assert agent.persona.id == "backend_engineer"
        assert agent.status == "working"

    def test_model_tier_in_tags(self, tmp_path):
        """Should add model tier tags to work items."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.orchestrator import Orchestrator

        orch = Orchestrator(state_dir=str(tmp_path / "orch"))
        items = orch.decompose_task("Research best practices", project_id="test")

        # All items should have model tier tags
        for item in items:
            model_tags = [t for t in item.tags if t.startswith("model:")]
            assert len(model_tags) == 1

    def test_orchestration_status(self, tmp_path):
        """Should report orchestration status."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.orchestrator import Orchestrator

        orch = Orchestrator(state_dir=str(tmp_path / "orch"))
        status = orch.get_status()

        assert "active_agents" in status
        assert "work_items" in status
        assert "wip" in status


# ═══════════════════════════════════════════════════════════════════════════════
# Model Policy Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestModelPolicy:
    """Test model routing per workflow stage."""

    def test_select_tier(self):
        """Should select appropriate tier for stage."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.model_policy import ModelPolicy

        policy = ModelPolicy()

        # Cheap for classification
        tier = policy.select_tier("classify")
        assert tier.tier == "cheap"

        # Medium for implementation
        tier = policy.select_tier("implement")
        assert tier.tier == "medium"

    def test_vram_downgrade(self):
        """Should downgrade tier if VRAM insufficient."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.model_policy import ModelPolicy

        policy = ModelPolicy()

        # Strong model needs 20GB, but we only have 6GB
        tier = policy.select_tier("research", available_vram_gb=6.0)
        assert tier.vram_required_gb <= 6.0

    def test_unknown_stage_defaults_to_medium(self):
        """Unknown stages should default to medium."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.model_policy import ModelPolicy

        policy = ModelPolicy()
        tier = policy.select_tier("unknown_stage_xyz")
        assert tier.tier == "medium"


# ═══════════════════════════════════════════════════════════════════════════════
# Context Pipeline Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestContextPipeline:
    """Test context assembly."""

    def test_assemble_context(self, isolated_workspace):
        """Should assemble context from multiple sources."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.context import ContextPipeline

        ctx = ContextPipeline(str(isolated_workspace / "project-a"))
        context = ctx.assemble("fix the bug", project_id="project-a")

        # Should have some content
        assert len(context) > 0

    def test_compact_text(self):
        """Should compact text to fit token budget."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from jarvis.core.context import ContextPipeline

        ctx = ContextPipeline()
        # Use multi-line text (compact splits on newlines)
        long_text = "\n".join([f"line {i}: {'word ' * 20}" for i in range(500)])
        compacted = ctx.compact(long_text, target_tokens=100)

        assert len(compacted) < len(long_text)
        assert "omitted" in compacted


# ═══════════════════════════════════════════════════════════════════════════════
# Platform Bridge Tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestPlatformBridge:
    """Test nightwatch platform bridge."""

    def test_discover_projects_for_nightwatch(self, isolated_workspace):
        """Should discover projects compatible with nightwatch."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from nightwatch.platform_bridge import discover_projects_for_nightwatch

        # Override HOME to avoid hitting real workspace
        import os
        old_home = os.environ.get("HOME")
        os.environ["HOME"] = str(isolated_workspace.parent)
        try:
            projects = discover_projects_for_nightwatch(str(isolated_workspace))
            assert len(projects) == 3
            assert any(p["name"] == "project-a" for p in projects)
        finally:
            if old_home:
                os.environ["HOME"] = old_home

    def test_select_persona_for_task(self):
        """Should select persona via bridge."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from nightwatch.platform_bridge import select_persona_for_task

        persona = select_persona_for_task("fix the nixos configuration")
        assert persona["id"] == "nixos_engineer"

    def test_get_model_tier(self):
        """Should get model tier via bridge."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from nightwatch.platform_bridge import get_model_tier_for_stage

        tier = get_model_tier_for_stage("implement")
        assert "tier" in tier
        assert "model_name" in tier

    def test_log_and_stats(self, tmp_path):
        """Should log execution and return stats."""
        import sys
        sys.path.insert(0, str(Path(__file__).parent.parent / "src"))
        from nightwatch.platform_bridge import log_task_execution, get_execution_stats

        # Override log path for testing
        import nightwatch.platform_bridge as bridge
        original_log_dir = bridge.Path

        log_task_execution(
            task_id="test-001",
            persona="backend_engineer",
            model_tier="medium",
            project="test",
            status="completed",
            duration_seconds=42.0,
        )

        stats = get_execution_stats()
        assert stats["total"] >= 1
        assert "completed" in stats["by_status"]
