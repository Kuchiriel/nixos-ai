"""Nightwatch v2 — Vault Sync

Connects JARVIS vault (persistent notes) with:
- Obsidian (local vault)
- HackMD (cloud collaborative)

Triangle: Obsidian ↔ HackMD ↔ JARVIS vault
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any


VAULT_DIR = Path.home() / "projects/nixos-ai/docs/vault"
OBSIDIAN_VAULT = Path.home() / "vaults/nixos-ai"


def ensure_vault_dirs() -> None:
    """Ensure vault directories exist."""
    VAULT_DIR.mkdir(parents=True, exist_ok=True)
    OBSIDIAN_VAULT.mkdir(parents=True, exist_ok=True)


def sync_to_obsidian() -> list[str]:
    """Sync JARVIS vault notes to Obsidian vault.

    Copies markdown files with YAML frontmatter.
    """
    ensure_vault_dirs()
    written = []

    for note in VAULT_DIR.rglob("*.md"):
        dest = OBSIDIAN_VAULT / note.relative_to(VAULT_DIR)
        dest.parent.mkdir(parents=True, exist_ok=True)

        content = note.read_text(encoding="utf-8")

        # Add frontmatter if not present
        if not content.startswith("---"):
            tags = ["nixos-ai", "jarvis-vault"]
            if "nightwatch" in note.name.lower():
                tags.append("nightwatch")
            frontmatter = f"---\ntags: [{', '.join(tags)}]\nsynced: true\n---\n\n"
            content = frontmatter + content

        dest.write_text(content, encoding="utf-8")
        written.append(str(dest))

    return written


def sync_to_hackmd() -> list[dict[str, Any]]:
    """Sync vault notes to HackMD."""
    try:
        from jarvis.core.hackmd import create_note, list_notes
    except ImportError:
        return []

    ensure_vault_dirs()
    results = []

    # Get existing HackMD notes
    existing = {n.get("title"): n for n in list_notes(limit=100)}

    for note in VAULT_DIR.rglob("*.md"):
        title = note.stem
        content = note.read_text(encoding="utf-8")

        # Add vault tag
        if "---" not in content[:10]:
            content = f"---\ntags: [jarvis-vault]\n---\n\n{content}"

        try:
            if title in existing:
                # Update existing
                note_id = existing[title].get("noteId") or existing[title].get("id")
                if note_id:
                    from jarvis.core.hackmd import update_note
                    update_note(note_id, content=content)
                    results.append({"title": title, "action": "updated"})
            else:
                # Create new
                result = create_note(title, content)
                results.append({"title": title, "action": "created", "id": result.get("id")})
        except Exception as e:
            results.append({"title": title, "action": "error", "error": str(e)})

    return results


def read_from_obsidian(query: str) -> list[dict[str, str]]:
    """Search Obsidian vault using ripgrep."""
    if not OBSIDIAN_VAULT.exists():
        return []

    try:
        import subprocess
        result = subprocess.run(
            ["rg", "-l", "-i", query, str(OBSIDIAN_VAULT)],
            capture_output=True, text=True, timeout=10,
        )
        return [{"path": p, "name": Path(p).stem} for p in result.stdout.splitlines()]
    except Exception:
        return []


def vault_status() -> dict[str, Any]:
    """Get vault sync status."""
    ensure_vault_dirs()

    local_notes = list(VAULT_DIR.rglob("*.md"))
    obsidian_notes = list(OBSIDIAN_VAULT.rglob("*.md")) if OBSIDIAN_VAULT.exists() else []

    return {
        "local_vault": str(VAULT_DIR),
        "obsidian_vault": str(OBSIDIAN_VAULT),
        "local_count": len(local_notes),
        "obsidian_count": len(obsidian_notes),
        "last_sync": _get_last_sync_time(),
    }


def _get_last_sync_time() -> str | None:
    """Get last sync timestamp."""
    sync_file = VAULT_DIR / ".last_sync"
    if sync_file.exists():
        return sync_file.read_text().strip()
    return None


def _update_sync_time() -> None:
    """Update last sync timestamp."""
    import time
    sync_file = VAULT_DIR / ".last_sync"
    sync_file.write_text(time.strftime("%Y-%m-%dT%H:%M:%S"))
