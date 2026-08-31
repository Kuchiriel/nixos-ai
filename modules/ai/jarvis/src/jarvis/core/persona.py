"""
Persona registry for multi-role agent support.

Personas are data, not code. Users can create new personas
by adding YAML files without modifying Python.

Based on Augment Code's Coordinator/Specialist/Verifier pattern.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class PersonaPolicy:
    """What this persona is allowed to do."""
    can_read: bool = True
    can_write: bool = False
    can_execute: bool = False
    can_commit: bool = False
    can_deploy: bool = False
    max_files_per_task: int = 10
    require_validation: bool = True
    require_review: bool = False


@dataclass
class Persona:
    """A role/persona that an agent can assume."""
    id: str
    name: str
    role: str  # short role description
    description: str  # what this persona does
    responsibilities: list = field(default_factory=list)
    tools: list = field(default_factory=list)  # allowed tool IDs
    policies: PersonaPolicy = field(default_factory=PersonaPolicy)
    system_prompt_additions: str = ""  # extra instructions for this persona
    model_preference: str = ""  # preferred model tier
    tags: list = field(default_factory=list)

    def to_dict(self):
        d = asdict(self)
        return d


# Built-in personas (can be overridden by user YAML files)
BUILTIN_PERSONAS = {
    "cto": Persona(
        id="cto",
        name="CTO",
        role="Chief Technology Officer",
        description="Makes high-level technical decisions, reviews architecture, prioritizes work",
        responsibilities=[
            "architecture decisions",
            "technology selection",
            "priority setting",
            "team coordination",
            "risk assessment",
        ],
        tools=["read", "rag_search", "memory", "shell", "git_status"],
        policies=PersonaPolicy(can_read=True, can_write=False, require_review=False),
        model_preference="strong",
        tags=["leadership", "architecture"],
    ),
    "architect": Persona(
        id="architect",
        name="Architect",
        role="Software Architect",
        description="Designs system architecture, creates ADRs, reviews structural decisions",
        responsibilities=[
            "system design",
            "ADR creation",
            "dependency analysis",
            "pattern selection",
            "technical debt assessment",
        ],
        tools=["read", "rag_search", "memory", "shell", "git_status", "write"],
        policies=PersonaPolicy(can_read=True, can_write=True, require_validation=True),
        model_preference="strong",
        tags=["architecture", "design"],
    ),
    "backend_engineer": Persona(
        id="backend_engineer",
        name="Backend Engineer",
        role="Backend Developer",
        description="Implements backend logic, APIs, services, and infrastructure",
        responsibilities=[
            "implementation",
            "API development",
            "database work",
            "service integration",
            "performance optimization",
        ],
        tools=["read", "write", "shell", "git", "test", "rag_search", "memory"],
        policies=PersonaPolicy(
            can_read=True, can_write=True, can_execute=True,
            can_commit=True, require_validation=True,
        ),
        model_preference="medium",
        tags=["backend", "implementation"],
    ),
    "nixos_engineer": Persona(
        id="nixos_engineer",
        name="NixOS Engineer",
        role="NixOS/Infrastructure Engineer",
        description="Manages NixOS configuration, services, packages, and system infrastructure",
        responsibilities=[
            "NixOS configuration",
            "service management",
            "package development",
            "system hardening",
            "flake management",
        ],
        tools=["read", "write", "shell", "nix_eval", "nix_build", "git"],
        policies=PersonaPolicy(
            can_read=True, can_write=True, can_execute=True,
            can_commit=True, can_deploy=False,
            require_validation=True,
        ),
        model_preference="medium",
        tags=["nixos", "infrastructure", "devops"],
    ),
    "qa_engineer": Persona(
        id="qa_engineer",
        name="QA Engineer",
        role="Quality Assurance Engineer",
        description="Writes tests, validates changes, checks for regressions",
        responsibilities=[
            "test writing",
            "regression testing",
            "code review",
            "validation",
            "quality gates",
        ],
        tools=["read", "shell", "test", "git_status", "rag_search"],
        policies=PersonaPolicy(
            can_read=True, can_write=False, can_execute=True,
            require_validation=False,
        ),
        model_preference="medium",
        tags=["testing", "quality"],
    ),
    "security_engineer": Persona(
        id="security_engineer",
        name="Security Engineer",
        role="Security Engineer",
        description="Reviews code for vulnerabilities, enforces security policies",
        responsibilities=[
            "security review",
            "vulnerability assessment",
            "policy enforcement",
            "access control",
            "audit",
        ],
        tools=["read", "shell", "rag_search", "memory", "git_status"],
        policies=PersonaPolicy(
            can_read=True, can_write=False, can_execute=True,
            require_validation=False,
        ),
        model_preference="strong",
        tags=["security", "audit"],
    ),
    "researcher": Persona(
        id="researcher",
        name="Researcher",
        role="Technical Researcher",
        description="Researches technologies, evaluates alternatives, writes findings",
        responsibilities=[
            "web research",
            "technology evaluation",
            "comparison analysis",
            "documentation",
            "ADR preparation",
        ],
        tools=["read", "web_search", "read_url", "rag_search", "memory", "write"],
        policies=PersonaPolicy(
            can_read=True, can_write=True,
            require_validation=False, require_review=True,
        ),
        model_preference="strong",
        tags=["research", "analysis"],
    ),
    "technical_writer": Persona(
        id="technical_writer",
        name="Technical Writer",
        role="Technical Writer",
        description="Writes documentation, READMEs, ADRs, and guides",
        responsibilities=[
            "documentation",
            "README updates",
            "ADR writing",
            "guide creation",
            "changelog management",
        ],
        tools=["read", "write", "rag_search", "memory"],
        policies=PersonaPolicy(
            can_read=True, can_write=True,
            require_validation=False,
        ),
        model_preference="cheap",
        tags=["documentation"],
    ),
    "supervisor": Persona(
        id="supervisor",
        name="Supervisor",
        role="Agent Supervisor",
        description="Coordinates other agents, manages task decomposition and delegation",
        responsibilities=[
            "task decomposition",
            "agent delegation",
            "progress tracking",
            "conflict resolution",
            "quality oversight",
        ],
        tools=["read", "rag_search", "memory", "shell", "git_status", "workitem"],
        policies=PersonaPolicy(
            can_read=True, can_write=False,
            require_validation=False,
        ),
        model_preference="strong",
        tags=["coordination", "management"],
    ),
    "devops_engineer": Persona(
        id="devops_engineer",
        name="DevOps Engineer",
        role="DevOps/SRE Engineer",
        description="Manages CI/CD, monitoring, deployment, and system reliability",
        responsibilities=[
            "CI/CD management",
            "monitoring setup",
            "deployment automation",
            "incident response",
            "system reliability",
        ],
        tools=["read", "write", "shell", "git", "nix_build", "systemctl"],
        policies=PersonaPolicy(
            can_read=True, can_write=True, can_execute=True,
            can_commit=True, can_deploy=True,
            require_validation=True,
        ),
        model_preference="medium",
        tags=["devops", "sre"],
    ),
}


class PersonaRegistry:
    """Manages available personas."""

    def __init__(self, personas_dir: str = None):
        self._personas: dict[str, Persona] = {}
        self._personas_dir = personas_dir

        # Load built-in personas
        for pid, persona in BUILTIN_PERSONAS.items():
            self._personas[pid] = persona

        # Load user personas from directory
        if personas_dir:
            self._load_from_dir(personas_dir)

    def _load_from_dir(self, personas_dir: str):
        """Load persona definitions from YAML/JSON files."""
        pdir = Path(personas_dir)
        if not pdir.exists():
            return

        for f in pdir.glob("*.json"):
            try:
                with open(f) as fh:
                    data = json.load(fh)
                persona = Persona(
                    id=data.get("id", f.stem),
                    name=data.get("name", f.stem),
                    role=data.get("role", ""),
                    description=data.get("description", ""),
                    responsibilities=data.get("responsibilities", []),
                    tools=data.get("tools", []),
                    policies=PersonaPolicy(**data.get("policies", {})),
                    system_prompt_additions=data.get("system_prompt_additions", ""),
                    model_preference=data.get("model_preference", ""),
                    tags=data.get("tags", []),
                )
                self._personas[persona.id] = persona
            except Exception:
                continue

    def get(self, persona_id: str) -> Optional[Persona]:
        """Get a persona by ID."""
        return self._personas.get(persona_id)

    def list_all(self) -> list[Persona]:
        """List all available personas."""
        return list(self._personas.values())

    def list_by_tag(self, tag: str) -> list[Persona]:
        """List personas with a specific tag."""
        return [p for p in self._personas.values() if tag in p.tags]

    def select_for_task(self, task_type: str, project_type: str = "") -> Persona:
        """Select the best persona for a task type."""
        # Simple heuristic selection
        task_lower = task_type.lower()

        if any(w in task_lower for w in ["security", "vulnerability", "audit"]):
            return self.get("security_engineer")
        elif any(w in task_lower for w in ["nix", "nixos", "flake", "systemd"]):
            return self.get("nixos_engineer")
        elif any(w in task_lower for w in ["test", "qa", "validate", "regression"]):
            return self.get("qa_engineer")
        elif any(w in task_lower for w in ["doc", "readme", "adr", "guide"]):
            return self.get("technical_writer")
        elif any(w in task_lower for w in ["research", "compare", "evaluate", "analyze"]):
            return self.get("researcher")
        elif any(w in task_lower for w in ["review", "architect", "design", "decide"]):
            return self.get("architect")
        elif any(w in task_lower for w in ["deploy", "ci", "cd", "monitor", "incident"]):
            return self.get("devops_engineer")
        elif any(w in task_lower for w in ["implement", "build", "create", "fix", "code"]):
            return self.get("backend_engineer")
        else:
            return self.get("backend_engineer")  # default

    def save_registry(self, path: str = None):
        """Save the registry to disk."""
        if path is None:
            path = os.path.expanduser("~/.local/state/jarvis/personas.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)

        data = {
            pid: p.to_dict() for pid, p in self._personas.items()
        }

        with open(path, "w") as f:
            json.dump(data, f, indent=2, default=str)

    def summary(self) -> str:
        """Human-readable summary."""
        lines = [f"Personas: {len(self._personas)}"]
        for pid, p in sorted(self._personas.items()):
            tools = len(p.tools)
            lines.append(
                f"  {pid}: {p.name} ({p.role}) "
                f"[{tools} tools] "
                f"tags={p.tags}"
            )
        return "\n".join(lines)
