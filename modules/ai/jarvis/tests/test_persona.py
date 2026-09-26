"""Test persona system - selection, policies, and behavior."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from jarvis.core.persona import PersonaRegistry, Persona, PersonaPolicy


class TestPersonaRegistry:
    """Test PersonaRegistry functionality."""

    def test_registry_loads_builtin_personas(self):
        """Registry should load all 15 built-ins (12 + agent + marketing + uncensored)."""
        registry = PersonaRegistry()
        personas = registry.list_all()
        assert len(personas) == 15
        # 25/09: a persona do tier local sem filtro precisa existir e ser
        # OBRIGATORAMENTE enxuta (sem web_search/vision) — é o tier que o
        # dono usa pra não levar consulta pra fora nem carregar tool morto.
        unc = registry.get("uncensored")
        assert unc is not None
        assert "web" not in unc.tools
        assert "vision" not in unc.tools
        assert "execut" in unc.system_prompt_additions.lower() or "obede" in unc.system_prompt_additions.lower()

    def test_forensic_audio_auditor_present(self):
        """Forensic audio auditor: ferramentas e seleção por tarefa."""
        registry = PersonaRegistry()
        p = registry.get("forensic_audio_auditor")
        assert p is not None
        for t in ("read", "rag_search", "memory", "shell", "web_search"):
            assert t in p.tools
        sel = registry.select_for_task("speaker attribution audiobook cap22")
        assert sel.id == "forensic_audio_auditor"

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
        """Each persona should have tools list (jarvis: [] = all tools)."""
        registry = PersonaRegistry()
        for persona in registry.list_all():
            assert isinstance(persona.tools, list)
            if persona.id not in ("jarvis", "agent", "marketing"):
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

    def test_unknown_task_selects_jarvis(self):
        """Unknown tasks should default to jarvis (MCU assistant)."""
        persona = self.registry.select_for_task("random task with no keywords")
        assert persona.id == "jarvis"


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


class TestPolicyEnforcement:
    """filter_tools honra can_write/can_execute (policies não decorativas)."""

    def test_coordinator_loses_shell(self):
        from jarvis.core.persona import PersonaRegistry, filter_tools
        p = PersonaRegistry().get("cto")
        assert p is not None
        assert p.policies.can_write is False
        got = filter_tools(
            ["read_file", "write_file", "execute_shell", "web_search"], p)
        assert "read_file" in got
        assert "execute_shell" not in got  # shell escreve: cai com can_write=False
        assert "write_file" not in got

    def test_devops_keeps_shell(self):
        from jarvis.core.persona import PersonaRegistry, filter_tools
        p = PersonaRegistry().get("devops_engineer")
        got = filter_tools(["read_file", "execute_shell", "nix_eval"], p)
        assert "execute_shell" in got

    def test_execute_without_write_still_blocked(self):
        """can_execute=True + can_write=False: shell cai (implica escrita)."""
        from jarvis.core.persona import Persona, PersonaPolicy, filter_tools
        p = Persona(id="x", name="x", role="x", description="x",
                    tools=["read", "shell"],
                    policies=PersonaPolicy(can_read=True, can_write=False,
                                           can_execute=True))
        got = filter_tools(["read_file", "execute_shell"], p)
        assert got == ["read_file"]


class TestAgentPersona:
    def test_agent_persona_exists_with_voice_mode(self):
        from jarvis.core.persona import PersonaRegistry
        p = PersonaRegistry().get("agent")
        assert p is not None
        assert "voice" in p.tags
        assert "1-2" in p.system_prompt_additions or "SHORT" in p.system_prompt_additions

    def test_agent_uses_agent_persona_in_voice_mode(self, tmp_path) -> None:
        import json as jsonlib
        from jarvis.core.agent import Agent
        from jarvis.core.config import Config
        import sys
        sys.path.insert(0, "tests")
        from test_agent import FakeSession  # noqa

        seen = {}

        class Cap(FakeSession):
            def post(self, url, json=None, timeout=120, **kw):
                seen["sys"] = json["messages"][0]["content"]
                return super().post(url, json=json, timeout=timeout, **kw)

        Agent(Config(), session=Cap(), persona_id="agent").run("oi")
        assert "AGENT MODE" in seen["sys"]

    def test_agent_default_persona_unchanged(self, tmp_path) -> None:
        import json as jsonlib
        from jarvis.core.agent import Agent
        from jarvis.core.config import Config
        import sys
        sys.path.insert(0, "tests")
        from test_agent import FakeSession  # noqa

        seen = {}

        class Cap(FakeSession):
            def post(self, url, json=None, timeout=120, **kw):
                seen["sys"] = json["messages"][0]["content"]
                return super().post(url, json=json, timeout=timeout, **kw)

        Agent(Config(), session=Cap()).run("oi")
        assert "AGENT MODE" not in seen["sys"]
        assert "JARVIS" in seen["sys"]


class TestMarketingPersona:
    def test_marketing_persona_exists_with_price_table(self):
        from jarvis.core.persona import PersonaRegistry
        p = PersonaRegistry().get("marketing")
        assert p is not None
        assert "149,99" in p.system_prompt_additions
        assert "379,99" in p.system_prompt_additions
        assert "1.259,99" in p.system_prompt_additions
        assert "PROIBIDO" in p.system_prompt_additions
        assert p.policies.can_write is False
        assert p.policies.can_execute is False

    def test_marketing_uses_marketing_persona(self, tmp_path) -> None:
        from jarvis.core.agent import Agent
        from jarvis.core.config import Config
        import sys
        sys.path.insert(0, "tests")
        from test_agent import FakeSession  # noqa

        seen = {}

        class Cap(FakeSession):
            def post(self, url, json=None, timeout=120, **kw):
                seen["sys"] = json["messages"][0]["content"]
                return super().post(url, json=json, timeout=timeout, **kw)

        Agent(Config(), session=Cap(), persona_id="marketing").run("quanto custa?")
        assert "MARKETING MODE" in seen["sys"]
        assert "149,99" in seen["sys"]


def test_system_prompt_template_all_call_sites_pass_tools_catalog():
    """25/09: o REPL quebrou com KeyError 'tools_catalog' porque um
    call-site do .format() esqueceu o kwarg novo. F8: o mecanismo mudou —
    6 sites .format() viraram 1 helper (_build_system_prompt) sobre o
    Assembler. Este teste agora trava o NOVO mecanismo: zero .format() rest,
    e todo call-site do helper passa as 6 partes."""
    import pathlib
    import re

    src = pathlib.Path(__file__).resolve().parents[1] / "src/jarvis/cli/dev.py"
    text = src.read_text(encoding="utf-8")
    assert not re.search(r"SYSTEM_PROMPT_TEMPLATE\.format\(", text), (
        "call-site .format() residual — usar _build_system_prompt")
    starts = [m.start() for m in re.finditer(r"_build_system_prompt\(", text)
              if not text[max(0, m.start() - 4):m.start()].endswith("def ")]
    assert starts, "helper não encontrado"
    for i in starts:
        window = text[i:i + 700]
        for part in ("repo_map", "memory_ctx", "agent_ctx", "persona",
                     "_TOOL_DISCIPLINE", "_tools_catalog"):
            assert part in window, (
                f"call-site de _build_system_prompt sem {part} — "
                "prompt do REPL incompleto")
