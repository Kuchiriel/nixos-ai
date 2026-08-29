"""Multi-AI conversation reader.

Reads shared conversations from:
- ChatGPT (chatgpt.com/share/*)
- Gemini (gemini.google.com/share/*)
- Claude (claude.ai/share/*)

Uses Playwright for browser automation when available,
falls back to requests + HTML parsing.
"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any


def read_chatgpt_conversation(url: str, max_chars: int = 50000) -> str:
    """Read a shared ChatGPT conversation."""
    try:
        from jarvis.core.chatgpt_reader import handle_chatgpt_read
        return handle_chatgpt_read({"url": url, "max_chars": max_chars})
    except Exception as e:
        return f"ERROR: ChatGPT reader failed: {e}"


def read_gemini_conversation(url: str, max_chars: int = 50000) -> str:
    """Read a shared Gemini conversation.

    Gemini share URLs look like:
    https://gemini.google.com/share/xxxxx

    Uses Playwright to render the page and extract messages.
    """
    try:
        import subprocess
        # Try playwright first
        result = subprocess.run(
            ["npx", "-y", "@playwright/mcp", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return _read_with_playwright(url, max_chars, "gemini")
    except Exception:
        pass

    # Fallback: requests
    try:
        import requests
        resp = requests.get(url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        })
        resp.raise_for_status()
        return _extract_text_from_html(resp.text, max_chars, "gemini")
    except Exception as e:
        return f"ERROR: Gemini reader failed: {e}"


def read_claude_conversation(url: str, max_chars: int = 50000) -> str:
    """Read a shared Claude conversation.

    Claude share URLs look like:
    https://claude.ai/share/xxxxx

    Uses Playwright to render the page and extract messages.
    """
    try:
        import subprocess
        result = subprocess.run(
            ["npx", "-y", "@playwright/mcp", "--help"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return _read_with_playwright(url, max_chars, "claude")
    except Exception:
        pass

    # Fallback: requests
    try:
        import requests
        resp = requests.get(url, timeout=30, headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
        })
        resp.raise_for_status()
        return _extract_text_from_html(resp.text, max_chars, "claude")
    except Exception as e:
        return f"ERROR: Claude reader failed: {e}"


def read_ai_conversation(url: str, max_chars: int = 50000) -> str:
    """Auto-detect AI platform and read conversation.

    Supports:
    - chatgpt.com/share/* → ChatGPT reader
    - gemini.google.com/share/* → Gemini reader
    - claude.ai/share/* → Claude reader
    """
    url_lower = url.lower()

    if "chatgpt.com" in url_lower or "chat.openai.com" in url_lower:
        return read_chatgpt_conversation(url, max_chars)
    elif "gemini.google.com" in url_lower:
        return read_gemini_conversation(url, max_chars)
    elif "claude.ai" in url_lower:
        return read_claude_conversation(url, max_chars)
    else:
        return f"ERROR: Unknown AI platform in URL: {url}\nSupported: chatgpt.com, gemini.google.com, claude.ai"


def _read_with_playwright(url: str, max_chars: int, platform: str) -> str:
    """Read conversation using Playwright browser automation."""
    import subprocess
    import tempfile

    # Create a script that uses playwright to extract messages
    script = f'''
import asyncio
from playwright.async_api import async_playwright

async def main():
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        page = await browser.new_page()
        await page.goto("{url}", wait_until="networkidle", timeout=30000)
        await page.wait_for_timeout(3000)  # Wait for JS rendering

        # Extract text content
        content = await page.content()
        await browser.close()
        return content

content = asyncio.run(main())
print(content)
'''
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(script)
        script_path = f.name

    try:
        result = subprocess.run(
            ["python3", script_path],
            capture_output=True, text=True, timeout=60,
        )
        if result.returncode == 0 and result.stdout:
            return _extract_text_from_html(result.stdout, max_chars, platform)
        else:
            return f"ERROR: Playwright failed: {result.stderr[:500]}"
    except Exception as e:
        return f"ERROR: Playwright error: {e}"
    finally:
        os.unlink(script_path)


def _extract_text_from_html(html: str, max_chars: int, platform: str) -> str:
    """Extract conversation text from HTML content.

    Simple heuristic extraction — not perfect but works for most cases.
    """
    # Remove script and style tags
    html = re.sub(r'<script[^>]*>.*?</script>', '', html, flags=re.DOTALL | re.IGNORECASE)
    html = re.sub(r'<style[^>]*>.*?</style>', '', html, flags=re.DOTALL | re.IGNORECASE)

    # Extract text from common conversation containers
    # This is platform-specific and may need updating
    messages = []

    # Try to find message blocks
    # Common patterns: <div class="message">, <article>, <div role="article">
    patterns = [
        r'<(?:div|article|section)[^>]*class="[^"]*(?:message|turn|response|human|assistant)[^"]*"[^>]*>(.*?)</(?:div|article|section)>',
        r'<(?:div|p)[^>]*data-message[^>]*>(.*?)</(?:div|p)>',
    ]

    for pattern in patterns:
        matches = re.findall(pattern, html, re.DOTALL | re.IGNORECASE)
        if matches:
            for match in matches:
                # Clean HTML tags
                text = re.sub(r'<[^>]+>', ' ', match)
                text = re.sub(r'\s+', ' ', text).strip()
                if text and len(text) > 10:
                    messages.append(text)
            break

    if not messages:
        # Fallback: extract all text
        text = re.sub(r'<[^>]+>', ' ', html)
        text = re.sub(r'\s+', ' ', text).strip()
        # Take first max_chars
        text = text[:max_chars]
        return f"[{platform.upper()} CONVERSATION]\n{text}"

    output = f"[{platform.upper()} CONVERSATION — {len(messages)} messages]\n\n"
    for i, msg in enumerate(messages, 1):
        output += f"--- Message {i} ---\n{msg}\n\n"
        if len(output) > max_chars:
            output += f"\n... [truncated at {max_chars} chars]"
            break

    return output


# ═══ Tool Schema for MCP ═══

MULTI_AI_READER_TOOL = {
    "name": "jarvis_read_ai_conversation",
    "description": "Read a shared conversation from any AI platform (ChatGPT, Gemini, Claude). Auto-detects platform from URL.",
    "inputSchema": {
        "type": "object",
        "properties": {
            "url": {
                "type": "string",
                "description": "Share URL from ChatGPT, Gemini, or Claude"
            },
            "max_chars": {
                "type": "integer",
                "description": "Max characters to return (default: 50000)"
            }
        },
        "required": ["url"]
    }
}
