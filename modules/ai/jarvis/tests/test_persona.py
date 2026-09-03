"""Test persona system - selection, policies, and behavior."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jarvis.core.persona import PersonaRegistry, Persona, PersonaPolicy


class TestPersonaRegistry:
    """Test PersonaRegistry functionality."""

    def test_registry_loads_builtin_personas(self):
        """Registry should load all 10 built-in personas."""
        registry = PersonaRegistry()
        personas = registry.list_all()
        assert len(personas) == 10

    def test_get_persona_by_id(self):
        """Should retrieve persona by ID."""
        registry = PersonaRegistry()
        persona = registry.get("cto")
        assert persona is not None
        assert persona.id == "cto"
        assert persona.name == "CTO"

    def test_get_nonexistent_persona(self):
        """Should return None for nonexistent persona."""
        registry = PersonaRegistry()
        persona = registry.get("nonexistent")
        assert persona is None

    def test_list_by_tag(self):
        """Should filter personas by tag."""
        registry = PersonaRegistry()
        security_personas = registry.list_by_tag("security")
        assert len(security_personas) >= 1
        assert any(p.id == "security_engineer" for p in security_personas)

    def test_persona_has_policy(self):
        """Each persona should have a PersonaPolicy."""
        registry = PersonaRegistry()
        for persona in registry.list_all():
            assert isinstance(persona.policies, PersonaPolicy)

    def test_persona_has_tools(self):
        """Each persona should have tools list."""
        registry = PersonaRegistry()
        for persona in registry.list_all():
            assert isinstance(persona.tools, list)
            assert len(persona.tools) > 0


class TestPersonaSelection:
    """Test persona selection for tasks."""

    def setup_method(self):
        self.registry = PersonaRegistry()

    def test_security_task_selects_security_engineer(self):
        """Security tasks should select security_engineer."""
        persona = self.registry.select_for_task("Fix security vulnerability")
        assert persona.id == "security_engineer"

    def test_testing_task_selects_qa_engineer(self):
        """Testing tasks should select qa_engineer."""
        persona = self.registry.select_for_task("Add unit tests for API")
        assert persona.id == "qa_engineer"

    def test_documentation_task_selects_technical_writer(self):
        """Documentation tasks should select technical_writer."""
        persona = self.registry.select_for_task("Write documentation for README")
        assert persona.id == "technical_writer"

    def test_nixos_task_selects_nixos_engineer(self):
        """NixOS tasks should select nixos_engineer."""
        persona = self.registry.select_for_task("Configure systemd service")
        assert persona.id == "nixos_engineer"

    def test_architecture_task_selects_architect(self):
        """Architecture tasks should select architect."""
        persona = self.registry.select_for_task("Review architecture of microservice")
        assert persona.id == "architect"

    def test_deployment_task_selects_devops_engineer(self):
        """Deployment tasks should select devops_engineer."""
        persona = self.registry.select_for_task("Deploy to production")
        assert persona.id == "devops_engineer"

    def test_implementation_task_selects_backend_engineer(self):
        """Implementation tasks should select backend_engineer."""
        persona = self.registry.select_for_task("Implement REST API endpoint")
        assert persona.id == "backend_engineer"

    def test_research_task_selects_researcher(self):
        """Research tasks should select researcher."""
        persona = self.registry.select_for_task("Research best practices")
        assert persona.id == "researcher"

    def test_unknown_task_selects_backend_engineer(self):
        """Unknown tasks should default to backend_engineer."""
        persona = self.registry.select_for_task("random task with no keywords")
        assert persona.id == "backend_engineer"


class TestPersonaPolicies:
    """Test persona policies are correctly configured."""

    def test_cto_cannot_write(self):
        """CTO should not have write access."""
        registry = PersonaRegistry()
        cto = registry.get("cto")
        assert cto.policies.can_write is False

    def test_backend_engineer_can_write_and_commit(self):
        """Backend engineer should have write and commit access."""
        registry = PersonaRegistry()
        engineer = registry.get("backend_engineer")
        assert engineer.policies.can_write is True
        assert engineer.policies.can_commit is True

    def test_qa_engineer_cannot_write(self):
        """QA engineer should not have write access."""
        registry = PersonaRegistry()
        qa = registry.get("qa_engineer")
        assert qa.policies.can_write is False

    def test_devops_can_deploy(self):
        """DevOps engineer should have deploy access."""
        registry = PersonaRegistry()
        devops = registry.get("devops_engineer")
        assert devops.policies.can_deploy is True

    def test_researcher_requires_review(self):
        """Researcher should require review."""
        registry = PersonaRegistry()
        researcher = registry.get("researcher")
        assert researcher.policies.require_review is True


class TestPersonaSystemPrompts:
    """Test persona system prompt additions."""

    def test_cto_has_system_prompt(self):
        """CTO should have system prompt additions."""
        registry = PersonaRegistry()
        cto = registry.get("cto")
        assert len(cto.system_prompt_additions) > 0
        assert "CTO" in cto.system_prompt_additions

    def test_architect_has_system_prompt(self):
        """Architect should have system prompt additions."""
        registry = PersonaRegistry()
        architect = registry.get("architect")
        assert len(architect.system_prompt_additions) > 0
        assert "Architect" in architect.system_prompt_additions

    def test_backend_engineer_has_system_prompt(self):
        """Backend engineer should have system prompt additions."""
        registry = PersonaRegistry()
        engineer = registry.get("backend_engineer")
        assert len(engineer.system_prompt_additions) > 0
        assert "Backend Engineer" in engineer.system_prompt_additions
