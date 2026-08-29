"""HackMD API integration for knowledge persistence.

Allows the agent to:
- Create/update notes on HackMD
- Read notes from HackMD
- List notes and folders
- Sync local docs to HackMD

Requires: HMD_API_ACCESS_TOKEN environment variable or ~/.hackmd/config.json

API docs: https://hackmd.io/api
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

import requests


API_BASE = "https://api.hackmd.io/v1"


def _get_token() -> str | None:
    """Get HackMD API token from env or config file."""
    token = os.environ.get("HMD_API_ACCESS_TOKEN")
    if token:
        return token
    config_path = Path.home() / ".hackmd" / "config.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            return config.get("accessToken")
        except Exception:
            pass
    return None


def _headers() -> dict[str, str]:
    """Get API headers with auth."""
    token = _get_token()
    if not token:
        raise ValueError("HackMD token not configured. Set HMD_API_ACCESS_TOKEN or run: hackmd-cli login")
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


def list_notes(limit: int = 20) -> list[dict[str, Any]]:
    """List recent notes."""
    resp = requests.get(
        f"{API_BASE}/notes",
        headers=_headers(),
        params={"limit": limit, "sort": "updatedAt"},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def get_note(note_id: str) -> dict[str, Any]:
    """Get note content."""
    resp = requests.get(
        f"{API_BASE}/notes/{note_id}",
        headers=_headers(),
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def create_note(title: str, content: str, folder_id: str | None = None) -> dict[str, Any]:
    """Create a new note."""
    payload: dict[str, Any] = {"title": title, "content": content}
    if folder_id:
        payload["folderId"] = folder_id
    resp = requests.post(
        f"{API_BASE}/notes",
        headers=_headers(),
        json=payload,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def update_note(note_id: str, title: str | None = None, content: str | None = None) -> dict[str, Any]:
    """Update an existing note."""
    payload: dict[str, Any] = {}
    if title is not None:
        payload["title"] = title
    if content is not None:
        payload["content"] = content
    resp = requests.patch(
        f"{API_BASE}/notes/{note_id}",
        headers=_headers(),
        json=payload,
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()


def delete_note(note_id: str) -> bool:
    """Delete a note."""
    resp = requests.delete(
        f"{API_BASE}/notes/{note_id}",
        headers=_headers(),
        timeout=10,
    )
    return resp.status_code == 200


def sync_local_to_hackmd(local_path: str, title: str | None = None) -> dict[str, Any]:
    """Sync a local markdown file to HackMD.

    Creates if doesn't exist, updates if it does (by title match).
    """
    path = Path(local_path)
    if not path.exists():
        return {"error": f"File not found: {local_path}"}

    content = path.read_text(encoding="utf-8")
    note_title = title or path.stem

    # Check if note already exists (search by title)
    notes = list_notes(limit=50)
    existing = None
    for note in notes:
        if note.get("title") == note_title:
            existing = note
            break

    if existing:
        result = update_note(existing["noteId"], content=content)
        result["action"] = "updated"
    else:
        result = create_note(note_title, content)
        result["action"] = "created"

    return result


def create_nightwatch_report(report: str, cycle: int = 0) -> dict[str, Any]:
    """Create a nightwatch report note on HackMD."""
    title = f"Nightwatch Report — {__import__('datetime').datetime.now().strftime('%Y-%m-%d %H:%M')}"
    content = f"# {title}\n\nCycle: {cycle}\n\n---\n\n{report}"
    return create_note(title, content)


def create_knowledge_entry(title: str, content: str, tags: list[str] | None = None) -> dict[str, Any]:
    """Create a knowledge base entry on HackMD."""
    tag_line = ""
    if tags:
        tag_line = f"\n\nTags: {', '.join(tags)}"
    return create_note(title, content + tag_line)


# ═══ MCP Tool Schema ═══

HACKMD_TOOLS = [
    {
        "name": "jarvis_hackmd_list",
        "description": "List recent HackMD notes.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "limit": {"type": "integer", "description": "Max notes to return (default: 20)"}
            }
        }
    },
    {
        "name": "jarvis_hackmd_read",
        "description": "Read a HackMD note by ID.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "note_id": {"type": "string", "description": "HackMD note ID"}
            },
            "required": ["note_id"]
        }
    },
    {
        "name": "jarvis_hackmd_write",
        "description": "Create or update a HackMD note.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "title": {"type": "string", "description": "Note title"},
                "content": {"type": "string", "description": "Markdown content"},
                "note_id": {"type": "string", "description": "Update existing note (optional)"}
            },
            "required": ["title", "content"]
        }
    },
    {
        "name": "jarvis_hackmd_sync",
        "description": "Sync a local file to HackMD.",
        "inputSchema": {
            "type": "object",
            "properties": {
                "path": {"type": "string", "description": "Local file path"},
                "title": {"type": "string", "description": "Override title (optional)"}
            },
            "required": ["path"]
        }
    },
]
