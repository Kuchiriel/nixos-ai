"""Project resolution — "which project?" by evidence, not guesswork.

What this replaces: `persona_executor` derived a task's scope with
`os.listdir(project_path)` looking for `*.py` at the root. That is not
project discovery, it is an improvised file list. An objective mentioning
`modules/services/foo.nix` must find the REPO containing that path, not
some arbitrary `.py` in the root.

Strategy, in order of confidence:
1. Explicit project in the call (the owner typed it).
2. A path cited in the objective that exists inside exactly one discovered
   repo -> resolves unambiguously.
3. Exactly one candidate in the workspace -> use it.
4. Real ambiguity -> do NOT choose: return the candidates for the owner to
   decide (explicit fallback, required by the spec).
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any


def workspace_root() -> Path:
    """Resolve the workspace lazily.

    This used to be a module-level constant, which froze the value at import
    time: a later env change (systemd unit, test fixture, `jarvis space`)
    had no effect and resolution silently fell back to ~/projects. Resolving
    per call keeps the environment authoritative.
    """
    raw = os.environ.get("JARVIS_WORKSPACE_ROOT", "").strip()
    if raw:
        return Path(raw).expanduser()
    return Path.home() / "projects"


# Kept for backward compatibility with existing importers. Prefer
# `workspace_root()` in new code.
WORKSPACE = workspace_root()

# Repo markers: whatever has .git is a repo. Without .git it does not enter.
_MARKERS = (".git", "flake.nix", "package.json", "Cargo.toml", "go.mod",
            "pyproject.toml")


@dataclass(frozen=True)
class ResolvedProject:
    name: str
    root: Path
    confidence: str        # explicit | path | sole | ambiguous | default | unknown
    candidates: tuple[str, ...] = ()
    reason: str = ""

    @property
    def ok(self) -> bool:
        return self.confidence in ("explicit", "path", "sole")

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "root": str(self.root),
                "confidence": self.confidence, "reason": self.reason,
                "candidates": list(self.candidates)}


def discover_repos(workspace: Path | None = None) -> list[Path]:
    ws = workspace or workspace_root()
    if not ws.is_dir():
        return []
    out = []
    for item in sorted(ws.iterdir()):
        if item.is_dir() and any((item / m).exists() for m in _MARKERS):
            out.append(item)
    return out


_PATH_TOKEN_RE = re.compile(
    r"(?:[\w\-]+/)+[\w\-.]+\.(?:py|nix|md|json|ya?ml|toml|sh|lua|js|ts|c|cpp|h|rs)")


def resolve(objective: str = "", explicit: str | None = None,
            workspace: Path | None = None) -> ResolvedProject:
    """Resolve the project for an objective. Deterministic."""
    ws = workspace or workspace_root()
    repos = discover_repos(ws)
    if not repos:
        return ResolvedProject("", ws, "unknown", (), "no repos found in workspace")

    # 1. explicit — an explicit request that does not resolve is an ERROR,
    #    not a hint to start guessing (guessing would run the mission in the
    #    wrong repo, which is the worst possible outcome here).
    if explicit:
        for r in repos:
            if r.name == explicit:
                return ResolvedProject(r.name, r, "explicit")
        cand = (ws / explicit)
        if cand.is_dir():
            return ResolvedProject(cand.name, cand, "explicit")
        return ResolvedProject("", ws, "unknown", (),
                               f"project not found in workspace: {explicit}")

    # 2. path cited in the objective -> the repo that contains it
    for tok in _PATH_TOKEN_RE.findall(objective or ""):
        hits = [r for r in repos if (r / tok).exists()]
        if len(hits) == 1:
            return ResolvedProject(hits[0].name, hits[0], "path")
        if len(hits) > 1:
            return ResolvedProject("", ws, "ambiguous",
                                   tuple(h.name for h in hits))
    # basename-only token (e.g. "telegram.py") — only when unique
    for m in re.findall(r"[\w\-]+\.(?:py|nix|md|json|ya?ml|toml|sh|lua)",
                        objective or ""):
        owners = [r for r in repos if any(r.rglob(m))]
        if len(owners) == 1:
            return ResolvedProject(owners[0].name, owners[0], "path")

    # 3. project name cited literally
    for r in repos:
        if re.search(rf"\b{re.escape(r.name)}\b", objective or ""):
            return ResolvedProject(r.name, r, "path")

    # 4. single candidate
    if len(repos) == 1:
        return ResolvedProject(repos[0].name, repos[0], "sole")

    return ResolvedProject("", ws, "ambiguous", tuple(r.name for r in repos))


_STOP = {
    "arquivo", "arquivos", "projeto", "tarefa", "objetivo", "crie", "criar",
    "adicione", "implemente", "corrija", "refatore", "escreva", "codigo",
    "teste", "testes", "please", "deve", "deveria", "modulo", "pacote",
    "config", "configuracao", "equipe", "missao", "persona", "deploy",
    "commit", "create", "write", "file", "project", "task", "objective",
    "implement", "refactor", "code", "test", "tests", "add", "fix", "make",
    "should", "must", "module", "package", "team", "mission",
}

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
              "build", ".mypy_cache", ".pytest_cache", "result", "target",
              ".direnv", "archive", ".ruff_cache", "vendor"}


def scoped_files(root: Path, objective: str, limit: int = 20) -> list[str]:
    """Files RELEVANT to the objective inside the repo.

    This is not "list the .py files in the root": it is (a) paths cited
    literally in the objective, (b) if the objective cites a
    symbol/term, a basename search limited to the repo, skipping
    build/cache/vendor directories.
    """
    out: list[str] = []
    for tok in _PATH_TOKEN_RE.findall(objective or ""):
        if (root / tok).is_file() and tok not in out:
            out.append(tok)
    if not out:
        terms = {t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]{4,}", objective or "")
                 if t.lower() not in _STOP}
        if terms:
            for f in root.rglob("*"):
                if len(out) >= limit:
                    break
                if any(p in _SKIP_DIRS for p in f.parts):
                    continue
                if not f.is_file() or f.suffix not in (
                        ".py", ".nix", ".md", ".toml", ".json", ".sh", ".lua"):
                    continue
                if f.stem in terms:
                    rel = str(f.relative_to(root))
                    if rel not in out:
                        out.append(rel)
    return out[:limit]


def project_root_for(name: str, workspace: Path | None = None) -> Path:
    """Absolute root of a named project (validates that it is a repo)."""
    ws = workspace or workspace_root()
    for r in discover_repos(ws):
        if r.name == name:
            return r
    raise FileNotFoundError(f"project not found in workspace: {name}")


def is_known_project(name: str, workspace: Path | None = None) -> bool:
    try:
        project_root_for(name, workspace)
        return True
    except FileNotFoundError:
        return False


def known_projects(workspace: Path | None = None) -> list[str]:
    return [r.name for r in discover_repos(workspace)]


def summary(workspace: Path | None = None) -> list[dict[str, Any]]:
    """Inventory for the Telegram /projects command."""
    out = []
    for r in discover_repos(workspace):
        markers = [m for m in _MARKERS if (r / m).exists()]
        try:
            head = (r / ".git" / "HEAD").read_text(errors="replace").strip()
        except OSError:
            head = ""
        out.append({"name": r.name, "root": str(r), "markers": markers,
                    "is_repo": (r / ".git").exists(), "git_head": head[:40]})
    return out