#!/usr/bin/env python3
"""Read a ChatGPT shared conversation via Playwright."""
import json
import sys
from playwright.sync_api import sync_playwright

url = sys.argv[1]
max_chars = int(sys.argv[2]) if len(sys.argv) > 2 else 50000

with sync_playwright() as p:
    import shutil
    chromium_path = shutil.which("chromium") or "/etc/profiles/per-user/nixos/bin/chromium"
    browser = p.chromium.launch(
        headless=True,
        executable_path=chromium_path,
        args=["--no-sandbox"]
    )
    context = browser.new_context(
        user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36"
    )
    page = context.new_page()

    try:
        page.goto(url, wait_until="networkidle", timeout=60000)
        page.wait_for_timeout(8000)

        messages = page.evaluate("""() => {
            const msgs = [];
            const containers = document.querySelectorAll('[data-message-author-role]');
            for (const c of containers) {
                const role = c.getAttribute('data-message-author-role');
                const text = c.innerText || c.textContent || '';
                if (text.trim()) {
                    msgs.push({role: role, text: text.trim()});
                }
            }
            if (msgs.length === 0) {
                const body = document.body.innerText || '';
                return [{role: "unknown", text: body}];
            }
            return msgs;
        }""")

        all_text = "\n\n".join(
            "[" + m["role"] + "]\n" + m["text"] for m in messages
        )

        result = {
            "ok": True,
            "text": all_text[:max_chars],
            "messages": messages[:50],
            "message_count": len(messages),
            "char_count": len(all_text),
            "truncated": len(all_text) > max_chars,
        }
        print(json.dumps(result))

    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
    finally:
        browser.close()
