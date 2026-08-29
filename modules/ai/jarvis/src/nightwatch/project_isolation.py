"""ProjectIsolation — Isolates state between multiple projects.

Ensures that when working on project A, the harness never:
- Reads files from project B
- Executes git commands in project B
- Mixes task queues between projects
- Confuses file paths between projects

Each project gets its own:
- Task queue (filtered by project)
- Checkpoint (per-project state)
- Git operations (per-repo)
- Memory/lessons (per-project)
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


WORKSPACE_ROOT = Path.home() / "projects"
STATE_ROOT = Path.home() / ".local/state/jarvis"


@dataclass
class ProjectConfig:
    """Configuration for a single project."""
    name: str
    root: Path
    language: str = "python"  # python, nix, shell, mixed
    test_command: str = ""  # e.g. "pytest -x -q"
    lint_command: str = ""  # e.g. "ruff check"
    build_command: str = ""  # e.g. "nix build"
    protected_paths: list[str] = field(default_factory=list)
    max_file_size: int = 100_000  # bytes
    
    def validate(self) -> tuple[bool, list[str]]:
        """Validate project configuration."""
        errors = []
        if not self.root.exists():
            errors.append(f"Project root does not exist: {self.root}")
        if not (self.root / ".git").exists():
            errors.append(f"Not a git repository: {self.root}")
        return len(errors) == 0, errors


@dataclass
class ProjectState:
    """Persistent state for a single project."""
    name: str
    root: str
    last_active: float = field(default_factory=time.time)
    tasks_completed: int = 0
    tasks_failed: int = 0
    commits: list[str] = field(default_factory=list)
    branch: str = "main"
    last_error: str = ""
    context_tokens_used: int = 0
    
    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "root": self.root,
            "last_active": self.last_active,
            "tasks_completed": self.tasks_completed,
            "tasks_failed": self.tasks_failed,
            "commits": self.commits[-20:],  # Keep last 20
            "branch": self.branch,
            "last_error": self.last_error,
            "context_tokens_used": self.context_tokens_used,
        }
    
    @classmethod
    def from_dict(cls, data: dict) -> ProjectState:
        return cls(**{k: v for k, v in data.items() if k in cls.__dataclass_fields__})


class ProjectRegistry:
    """Registry of all known projects with their state."""
    
    STATE_FILE = STATE_ROOT / "projects.json"
    
    def __init__(self):
        STATE_ROOT.mkdir(parents=True, exist_ok=True)
        self._projects: dict[str, ProjectState] = {}
        self._configs: dict[str, ProjectConfig] = {}
        self._load()
    
    def _load(self) -> None:
        if self.STATE_FILE.exists():
            try:
                data = json.loads(self.STATE_FILE.read_text(encoding="utf-8"))
                for name, state_data in data.items():
                    self._projects[name] = ProjectState.from_dict(state_data)
            except Exception:
                pass
    
    def _save(self) -> None:
        self.STATE_FILE.write_text(
            json.dumps(
                {name: p.to_dict() for name, p in self._projects.items()},
                indent=2, ensure_ascii=False,
            ),
            encoding="utf-8",
        )
    
    def register(self, config: ProjectConfig) -> None:
        """Register a project."""
        self._configs[config.name] = config
        if config.name not in self._projects:
            self._projects[config.name] = ProjectState(
                name=config.name,
                root=str(config.root),
            )
            self._save()
    
    def get_state(self, name: str) -> ProjectState | None:
        return self._projects.get(name)
    
    def update_state(self, name: str, **kwargs: Any) -> None:
        if name in self._projects:
            for key, value in kwargs.items():
                if hasattr(self._projects[name], key):
                    setattr(self._projects[name], key, value)
            self._projects[name].last_active = time.time()
            self._save()
    
    def get_all_states(self) -> dict[str, ProjectState]:
        return dict(self._projects)


def discover_projects(workspace: Path | None = None) -> list[ProjectConfig]:
    """Auto-discover projects in the workspace."""
    workspace = workspace or WORKSPACE_ROOT
    projects = []
    
    if not workspace.exists():
        return projects
    
    for item in workspace.iterdir():
        if item.is_dir() and (item / ".git").exists():
            # Detect language
            language = "mixed"
            if (item / "*.py").exists() or any(item.glob("*.py")):
                language = "python"
            if (item / "flake.nix").exists() or (item / "*.nix").exists():
                if language == "python":
                    language = "mixed"
                else:
                    language = "nix"
            
            # Detect test command
            test_command = ""
            if (item / "pytest.ini").exists() or (item / "pyproject.toml").exists():
                test_command = "pytest -x -q"
            elif (item / "Makefile").exists():
                test_command = "make test"
            
            projects.append(ProjectConfig(
                name=item.name,
                root=item,
                language=language,
                test_command=test_command,
            ))
    
    return projects


def get_project_root(project_name: str) -> Path | None:
    """Get the root directory for a project by name."""
    candidates = [
        WORKSPACE_ROOT / project_name,
        Path.home() / project_name,
    ]
    for candidate in candidates:
        if candidate.exists() and (candidate / ".git").exists():
            return candidate
    return None


def validate_project_path(path: str, expected_project: str) -> tuple[bool, str]:
    """Validate that a path belongs to the expected project.
    
    Prevents cross-project contamination.
    """
    try:
        full = Path(path).resolve()
        project_root = get_project_root(expected_project)
        if not project_root:
            return False, f"Project {expected_project} not found"
        
        # Check if path is within project root
        try:
            full.relative_to(project_root.resolve())
            return True, "ok"
        except ValueError:
            return False, f"Path {path} is outside project {expected_project}"
    except Exception as e:
        return False, str(e)


def run_in_project(
    cmd: list[str],
    project_root: Path,
    timeout: int = 60,
    capture_output: bool = True,
) -> subprocess.CompletedProcess:
    """Run a command within a specific project directory.
    
    Never runs in a different project's directory.
    """
    return subprocess.run(
        cmd,
        capture_output=capture_output,
        text=True,
        timeout=timeout,
        cwd=str(project_root),
    )
