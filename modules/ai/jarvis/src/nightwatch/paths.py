"""Shared path utilities for the Nightwatch harness."""

from __future__ import annotations

import os
from pathlib import Path


def find_repo_root() -> Path:
    """Find the repo root dynamically. Walks up from cwd looking for .git or flake.nix.
    
    Priority:
    1. JARVIS_PROJECT_ROOT env var
    2. Walk up from cwd
    3. Fallback to ~/projects/nixos-ai
    """
    env_root = os.environ.get("JARVIS_PROJECT_ROOT", "")
    current = Path(env_root) if env_root else Path.cwd()
    
    for _ in range(10):  # max depth
        if (current / ".git").exists() or (current / "flake.nix").exists():
            return current
        parent = current.parent
        if parent == current:
            break
        current = parent
    
    # Fallback: assume we're inside the repo
    return Path.home() / "projects" / "nixos-ai"


REPO_ROOT = find_repo_root()
