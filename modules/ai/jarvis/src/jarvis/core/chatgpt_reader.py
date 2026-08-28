"""Read ChatGPT shared conversation links via Playwright headless browser.

ChatGPT shared conversations are JavaScript SPAs that require a real browser
to render. This module uses Playwright to:
1. Open the shared link
2. Wait for conversation to render
3. Extract all text content
4. Return structured conversation data
"""

from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any


def read_chatgpt_share(url: str, max_chars: int = 50000) -> dict[str, Any]:
    """Read a ChatGPT shared conversation link.

    Args:
        url: ChatGPT share URL (https://chatgpt.com/share/...)
        max_chars: Maximum characters to return

    Returns:
        {"ok": True, "text": "...", "messages": [...], "char_count": N}
        or {"ok": False, "error": "..."}
    """
    if not url.startswith("https://chatgpt.com/share/"):
        return {"ok": False, "error": f"Not a ChatGPT share URL: {url}"}

    # Use the standalone script (avoids shell escaping issues)
    script_path = Path(__file__).parent.parent.parent.parent / "scripts" / "read_chatgpt.py"
    if not script_path.exists():
        # Fallback: look in project root
        script_path = Path(os.environ.get("JARVIS_PROJECT_ROOT", "/home/nixos/projects/nixos-ai")) / "scripts" / "read_chatgpt.py"

    try:
        result = subprocess.run(
            ["nix-shell", "-p", "playwright", "chromium",
             "python3Packages.playwright", "--run",
             f"python3 {script_path} {json.dumps(url)} {max_chars}"],
            capture_output=True, text=True, timeout=120,
        )

        if result.returncode != 0:
            return {"ok": False, "error": f"Playwright failed: {result.stderr[:500]}"}

        output = result.stdout.strip()
        for line in output.split("\n"):
            line = line.strip()
            if line.startswith("{"):
                try:
                    return json.loads(line)
                except json.JSONDecodeError:
                    continue

        return {"ok": False, "error": f"No JSON in output: {output[:300]}"}

    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "Playwright timeout (120s)"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


# ═══ Tool definition ═══

CHATGPT_READER_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "jarvis_read_chatgpt",
        "description": "Read a shared ChatGPT conversation. Extracts all messages from the shared link using a headless browser.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "ChatGPT share URL (https://chatgpt.com/share/...)"
                },
                "max_chars": {
                    "type": "integer",
                    "description": "Max characters to return (default: 50000)"
                }
            },
            "required": ["url"]
        }
    }
}


def handle_chatgpt_read(args: dict[str, Any]) -> str:
    """Handler for jarvis_read_chatgpt tool."""
    url = args.get("url", "")
    max_chars = args.get("max_chars", 50000)

    if not url:
        return "ERROR: URL is required"

    result = read_chatgpt_share(url, max_chars)

    if result["ok"]:
        parts = []
        parts.append(f"Conversation: {result['message_count']} messages, {result['char_count']} chars")
        if result.get("truncated"):
            parts.append(f"(truncated to {max_chars} chars)")
        parts.append("")
        parts.append(result["text"])
        return "\n".join(parts)
    else:
        return f"ERROR: {result['error']}"
