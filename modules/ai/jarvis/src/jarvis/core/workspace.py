"""
Workspace discovery for monorepo/multi-project support.

Discovers projects in a workspace root, reads their manifests,
builds dependency graphs, and determines which projects are affected
by a change.

Based on Nx "Three Walls" (Read, Write, Memory) and OpenDev's
workspace discovery approach.
"""

import json
import os
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Optional


@dataclass
class ProjectManifest:
    """Declarative project definition."""
    id: str
    name: str
    path: str  # relative to workspace root
    type: str = "unknown"  # python, nix, node, rust, mixed
    language: str = ""
    build_cmd: str = ""
    test_cmd: str = ""
    lint_cmd: str = ""
    deploy_cmd: str = ""
    owners: list = field(default_factory=list)
    dependencies: list = field(default_factory=list)  # other project IDs
    documentation: str = ""
    agents: list = field(default_factory=list)  # persona IDs that work here
    tags: list = field(default_factory=list)
    auto_detected: bool = False

    def to_dict(self):
        return asdict(self)


@dataclass
class ProjectInfo:
    """Runtime project information (beyond manifest)."""
    manifest: ProjectManifest
    languages: dict = field(default_factory=dict)  # lang -> file_count
    file_count: int = 0
    total_lines: int = 0
    has_tests: bool = False
    has_git: bool = False
    git_branch: str = ""
    last_modified: str = ""
    has_agents_md: bool = False
    has_readme: bool = False

    def to_dict(self):
        return {
            "manifest": self.manifest.to_dict(),
            "languages": self.languages,
            "file_count": self.file_count,
            "total_lines": self.total_lines,
            "has_tests": self.has_tests,
            "has_git": self.has_git,
            "git_branch": self.git_branch,
            "has_agents_md": self.has_agents_md,
            "has_readme": self.has_readme,
        }


# Language detection by extension
LANG_MAP = {
    ".py": "python", ".nix": "nix", ".js": "javascript",
    ".ts": "typescript", ".rs": "rust", ".go": "go",
    ".sh": "shell", ".bash": "shell",
    ".json": "json", ".yaml": "yaml", ".yml": "yaml",
    ".toml": "toml", ".md": "markdown", ".html": "html",
    ".css": "css", ".svelte": "svelte", ".vue": "vue",
    ".c": "c", ".cpp": "cpp", ".h": "c_header",
}

# Files that indicate project type
TYPE_INDICATORS = {
    "python": ["setup.py", "pyproject.toml", "requirements.txt", "__init__.py"],
    "nix": ["flake.nix", "default.nix", "shell.nix"],
    "node": ["package.json", "yarn.lock", "pnpm-lock.yaml"],
    "rust": ["Cargo.toml", "Cargo.lock"],
    "go": ["go.mod", "go.sum"],
}

# Directories to skip during discovery
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".nix-profile",
    "result", "result-2", "result-3", ".direnv", "dist",
    "build", ".cache", ".venv", "venv", "egg-info",
    ".mypy_cache", ".ruff_cache", ".pytest_cache",
}


class WorkspaceDiscovery:
    """Discovers and manages projects in a workspace."""

    def __init__(self, workspace_root: str = None):
        if workspace_root is None:
            workspace_root = os.path.expanduser("~/projects")
        self.workspace_root = Path(workspace_root)
        self._projects: dict[str, ProjectInfo] = {}
        self._dependency_graph: dict[str, list[str]] = {}

    def discover(self) -> dict[str, ProjectInfo]:
        """Discover all projects in the workspace."""
        self._projects.clear()

        for entry in sorted(self.workspace_root.iterdir()):
            if not entry.is_dir() or entry.name.startswith(".") or entry.name in SKIP_DIRS:
                continue
            if (entry / ".git").exists() or self._looks_like_project(entry):
                manifest = self._auto_detect_manifest(entry)
                info = self._analyze_project(entry, manifest)
                self._projects[manifest.id] = info

        self._build_dependency_graph()
        return self._projects

    def _looks_like_project(self, path: Path) -> bool:
        """Check if a directory looks like a project."""
        indicators = [
            "README.md", "AGENTS.md", "pyproject.toml", "setup.py",
            "package.json", "Cargo.toml", "go.mod", "flake.nix",
            "Makefile", "CMakeLists.txt",
        ]
        return any((path / ind).exists() for ind in indicators)

    def _auto_detect_manifest(self, project_path: Path) -> ProjectManifest:
        """Auto-detect project manifest from structure."""
        project_id = project_path.name
        rel_path = str(project_path.relative_to(self.workspace_root))

        # Detect project type
        proj_type = "unknown"
        languages = {}
        for type_name, files in TYPE_INDICATORS.items():
            for f in files:
                if (project_path / f).exists():
                    proj_type = type_name if proj_type == "unknown" else f"{proj_type}+{type_name}"
                    break

        # Detect language breakdown
        for ext, lang in LANG_MAP.items():
            count = sum(1 for _ in project_path.rglob(f"*{ext}")
                       if not any(skip in str(_.relative_to(project_path))
                                 for skip in SKIP_DIRS))
            if count > 0:
                languages[lang] = count

        # Detect test command
        test_cmd = ""
        if (project_path / "pyproject.toml").exists():
            test_cmd = "python -m pytest"
        elif (project_path / "Makefile").exists():
            test_cmd = "make test"
        elif (project_path / "flake.nix").exists():
            test_cmd = "nix flake check"

        # Detect build command
        build_cmd = ""
        if (project_path / "pyproject.toml").exists():
            build_cmd = "python -m build"
        elif (project_path / "Makefile").exists():
            build_cmd = "make"
        elif (project_path / "flake.nix").exists():
            build_cmd = "nix build"

        # Read dependencies from AGENTS.md or README
        deps = []
        agents_md = project_path / "AGENTS.md"
        if agents_md.exists():
            content = agents_md.read_text(errors="ignore")
            # Simple dependency extraction (look for "depends on" patterns)
            # This is a heuristic, not a parser

        return ProjectManifest(
            id=project_id,
            name=project_id.replace("-", " ").replace("_", " ").title(),
            path=rel_path,
            type=proj_type,
            language=", ".join(sorted(languages.keys())[:3]),
            build_cmd=build_cmd,
            test_cmd=test_cmd,
            auto_detected=True,
            tags=list(languages.keys()),
        )

    def _analyze_project(self, project_path: Path, manifest: ProjectManifest) -> ProjectInfo:
        """Analyze a project for additional information."""
        file_count = 0
        total_lines = 0
        lang_counts = {}

        for ext, lang in LANG_MAP.items():
            for f in project_path.rglob(f"*{ext}"):
                rel = str(f.relative_to(project_path))
                if not any(skip in rel for skip in SKIP_DIRS):
                    file_count += 1
                    lang_counts[lang] = lang_counts.get(lang, 0) + 1
                    try:
                        total_lines += len(f.read_text(errors="ignore").splitlines())
                    except Exception:
                        pass

        # Check git
        has_git = (project_path / ".git").exists()
        git_branch = ""
        if has_git:
            try:
                import subprocess
                result = subprocess.run(
                    ["git", "branch", "--show-current"],
                    cwd=str(project_path),
                    capture_output=True, text=True, timeout=5,
                )
                git_branch = result.stdout.strip()
            except Exception:
                pass

        return ProjectInfo(
            manifest=manifest,
            languages=lang_counts,
            file_count=file_count,
            total_lines=total_lines,
            has_git=has_git,
            git_branch=git_branch,
            has_agents_md=(project_path / "AGENTS.md").exists(),
            has_readme=(project_path / "README.md").exists(),
        )

    def _build_dependency_graph(self):
        """Build a dependency graph from manifests and imports."""
        self._dependency_graph = {pid: [] for pid in self._projects}

        for pid, info in self._projects.items():
            # Check if this project imports from others
            project_path = self.workspace_root / info.manifest.path
            for py_file in project_path.rglob("*.py"):
                try:
                    content = py_file.read_text(errors="ignore")
                    for other_id, other_info in self._projects.items():
                        if other_id == pid:
                            continue
                        # Check if any file from other project is imported
                        other_name = other_id.replace("-", "_").replace(" ", "_")
                        if other_name in content:
                            if other_id not in self._dependency_graph[pid]:
                                self._dependency_graph[pid].append(other_id)
                except Exception:
                    pass

    def get_affected_projects(self, changed_files: list[str]) -> list[str]:
        """Determine which projects are affected by file changes."""
        affected = set()
        for f in changed_files:
            f_path = Path(f)
            for pid, info in self._projects.items():
                proj_path = Path(info.manifest.path)
                try:
                    f_path.relative_to(proj_path)
                    affected.add(pid)
                except ValueError:
                    continue

                # Also check transitive dependencies
                for dep_id in self._dependency_graph.get(pid, []):
                    if dep_id in affected:
                        affected.add(pid)

        return list(affected)

    def get_project_context(self, project_id: str) -> dict:
        """Get the context needed to work on a specific project."""
        if project_id not in self._projects:
            return {"error": f"Project {project_id} not found"}

        info = self._projects[project_id]
        project_path = self.workspace_root / info.manifest.path

        context = {
            "manifest": info.manifest.to_dict(),
            "languages": info.languages,
            "file_count": info.file_count,
            "total_lines": info.total_lines,
            "has_tests": info.has_tests,
            "has_git": info.has_git,
            "git_branch": info.git_branch,
            "dependencies": self._dependency_graph.get(project_id, []),
            "dependents": [
                pid for pid, deps in self._dependency_graph.items()
                if project_id in deps
            ],
        }

        # Read AGENTS.md if exists
        agents_md = project_path / "AGENTS.md"
        if agents_md.exists():
            try:
                context["agents_md"] = agents_md.read_text(errors="ignore")[:3000]
            except Exception:
                pass

        return context

    def save(self, path: str = None):
        """Save workspace state to disk."""
        if path is None:
            path = os.path.expanduser("~/.local/state/jarvis/workspace.json")
        os.makedirs(os.path.dirname(path), exist_ok=True)

        state = {
            "workspace_root": str(self.workspace_root),
            "projects": {
                pid: info.to_dict()
                for pid, info in self._projects.items()
            },
            "dependency_graph": self._dependency_graph,
        }

        with open(path, "w") as f:
            json.dump(state, f, indent=2, default=str)

    def load(self, path: str = None) -> bool:
        """Load workspace state from disk."""
        if path is None:
            path = os.path.expanduser("~/.local/state/jarvis/workspace.json")

        if not os.path.exists(path):
            return False

        try:
            with open(path) as f:
                state = json.load(f)

            self.workspace_root = Path(state["workspace_root"])
            for pid, info_dict in state.get("projects", {}).items():
                manifest = ProjectManifest(**info_dict["manifest"])
                info = ProjectInfo(
                    manifest=manifest,
                    languages=info_dict.get("languages", {}),
                    file_count=info_dict.get("file_count", 0),
                    total_lines=info_dict.get("total_lines", 0),
                    has_git=info_dict.get("has_git", False),
                    git_branch=info_dict.get("git_branch", ""),
                    has_agents_md=info_dict.get("has_agents_md", False),
                    has_readme=info_dict.get("has_readme", False),
                )
                self._projects[pid] = info

            self._dependency_graph = state.get("dependency_graph", {})
            return True
        except Exception:
            return False

    def summary(self) -> str:
        """Human-readable workspace summary."""
        lines = [
            f"Workspace: {self.workspace_root}",
            f"Projects: {len(self._projects)}",
            "",
        ]

        for pid, info in sorted(self._projects.items()):
            langs = ", ".join(sorted(info.languages.keys())[:3])
            deps = self._dependency_graph.get(pid, [])
            lines.append(
                f"  {pid}: {info.file_count} files, "
                f"{info.total_lines} lines, "
                f"[{langs}] "
                f"{'✓git' if info.has_git else '✗git'} "
                f"{'✓agents.md' if info.has_agents_md else ''} "
                f"deps={deps}"
            )

        return "\n".join(lines)


def discover_workspace(root: str = None) -> WorkspaceDiscovery:
    """Convenience function to discover and return workspace."""
    ws = WorkspaceDiscovery(root)
    ws.discover()
    ws.save()
    return ws
