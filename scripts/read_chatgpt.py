#!/usr/bin/env python3
"""Read a ChatGPT shared conversation via Playwright.

Scrolls the ENTIRE conversation to force DOM hydration before extracting.
ChatGPT uses virtual scrolling — messages outside viewport are not in DOM.
"""
import json
import sys
from playwright.sync_api import sync_playwright

url = sys.argv[1]
max_chars = int(sys.argv[2]) if len(sys.argv) > 2 else 100000

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
        page.wait_for_timeout(5000)

        # ── Step 1: Scroll to TOP first (ChatGPT may start at bottom) ──
        page.evaluate("""() => {
            // Scroll to very top
            window.scrollTo(0, 0);
            document.documentElement.scrollTop = 0;
            document.body.scrollTop = 0;
            // Also try scrolling the main conversation container
            const main = document.querySelector('main') || document.querySelector('[class*="conversation"]') || document.documentElement;
            main.scrollTop = 0;
        }""")
        page.wait_for_timeout(2000)

        # ── Step 2: Scroll DOWN incrementally to force all messages into DOM ──
        # We scroll in small steps, waiting between each to let ChatGPT hydrate
        scroll_result = page.evaluate("""() => {
            return new Promise((resolve) => {
                let scrolls = 0;
                let lastHeight = 0;
                let sameCount = 0;
                const maxScrolls = 500;  // safety limit
                
                function doScroll() {
                    scrolls++;
                    window.scrollBy(0, 800);
                    document.documentElement.scrollTop += 800;
                    
                    // Also scroll any scrollable container
                    const containers = document.querySelectorAll('[class*="scroll"], [class*="conversation"], main, [role="main"]');
                    containers.forEach(c => { c.scrollTop += 800; });
                    
                    const currentHeight = document.documentElement.scrollHeight;
                    
                    if (currentHeight === lastHeight) {
                        sameCount++;
                    } else {
                        sameCount = 0;
                    }
                    lastHeight = currentHeight;
                    
                    // Stop if we've reached bottom 3 times or hit safety limit
                    if ((sameCount >= 3 && scrolls > 10) || scrolls >= maxScrolls) {
                        // Now scroll back to top to ensure all is loaded
                        window.scrollTo(0, 0);
                        document.documentElement.scrollTop = 0;
                        const containers2 = document.querySelectorAll('[class*="scroll"], [class*="conversation"], main, [role="main"]');
                        containers2.forEach(c => { c.scrollTop = 0; });
                        resolve({scrolls: scrolls, height: currentHeight});
                        return;
                    }
                    
                    setTimeout(doScroll, 150);
                }
                
                doScroll();
            });
        }""")
        print(f"Scroll done: {scroll_result}", file=sys.stderr)

        page.wait_for_timeout(3000)

        # ── Step 3: Scroll back to top ──
        page.evaluate("""() => {
            window.scrollTo(0, 0);
            document.documentElement.scrollTop = 0;
            document.body.scrollTop = 0;
            const main = document.querySelector('main') || document.documentElement;
            main.scrollTop = 0;
        }""")
        page.wait_for_timeout(2000)

        # ── Step 4: NOW extract all messages from the fully-hydrated DOM ──
        messages = page.evaluate("""() => {
            const msgs = [];
            
            // Primary: data-message-author-role (ChatGPT's own attribute)
            const containers = document.querySelectorAll('[data-message-author-role]');
            for (const c of containers) {
                const role = c.getAttribute('data-message-author-role');
                const text = c.innerText || c.textContent || '';
                if (text.trim()) {
                    msgs.push({role: role, text: text.trim()});
                }
            }
            
            // Fallback: try other selectors if primary yields nothing
            if (msgs.length === 0) {
                // Try article elements
                const articles = document.querySelectorAll('article[data-testid]');
                for (const a of articles) {
                    const role = a.querySelector('[data-message-author-role]')?.getAttribute('data-message-author-role') || 'unknown';
                    const text = a.innerText || a.textContent || '';
                    if (text.trim()) {
                        msgs.push({role: role, text: text.trim()});
                    }
                }
            }
            
            // Last resort: get entire body text
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
            "messages": messages[:100],
            "message_count": len(messages),
            "char_count": len(all_text),
            "truncated": len(all_text) > max_chars,
        }
        print(json.dumps(result))

    except Exception as e:
        print(json.dumps({"ok": False, "error": str(e)}))
    finally:
        browser.close()
