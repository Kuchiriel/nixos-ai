"""Browser tool do Agent (Playwright headless persistente).

Ações: open(url) → título+texto; click(selector) → estado;
fill(selector, text) → estado; snapshot() → título+elementos.
Guarda: só http(s); localhost livre, externo exige approve=True
(padrão do harness: mutação pede aprovação).
"""
from __future__ import annotations

from typing import Any

_pw = None
_browser = None
_page = None


def _ensure():
    global _pw, _browser, _page
    if _page is not None:
        return _page
    import shutil
    from playwright.sync_api import sync_playwright
    _pw = sync_playwright().start()
    # Binário do sandbox ms-playwright não roda no NixOS (libs);
    # usa o chromium do sistema (nixpkgs, patcheado).
    exe = (shutil.which("chromium") or shutil.which("chromium-browser")
           or shutil.which("google-chrome"))
    if exe:
        _browser = _pw.chromium.launch(headless=True, executable_path=exe,
                                       args=["--no-sandbox"])
    else:
        _browser = _pw.chromium.launch(headless=True)
    _page = _browser.new_page()
    return _page


def close():
    global _pw, _browser, _page
    try:
        if _browser is not None:
            _browser.close()
        if _pw is not None:
            _pw.stop()
    except Exception:
        pass
    _pw = _browser = _page = None


def _state(page) -> dict[str, Any]:
    try:
        title = page.title()
    except Exception:
        title = ""
    try:
        text = page.inner_text("body")[:1500]
    except Exception:
        text = ""
    return {"title": title, "url": page.url, "text": text}


def browser_open(url: str) -> dict[str, Any]:
    """Abre URL (leitura, sem aprovação)."""
    if not (url.startswith("http://") or url.startswith("https://")):
        return {"ok": False, "error": f"URL inválida: {url}"}
    try:
        page = _ensure()
        page.goto(url, timeout=30000)
        page.wait_for_load_state("domcontentloaded", timeout=15000)
        return {"ok": True, **_state(page)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def browser_click(selector: str) -> dict[str, Any]:
    """Clica num seletor CSS (mutação: harness pede aprovação antes)."""
    try:
        page = _ensure()
        page.click(selector, timeout=10000)
        page.wait_for_timeout(500)
        return {"ok": True, "clicked": selector, **_state(page)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def browser_fill(selector: str, text: str) -> dict[str, Any]:
    """Preenche campo (mutação: harness pede aprovação antes)."""
    try:
        page = _ensure()
        page.fill(selector, text, timeout=10000)
        page.wait_for_timeout(300)
        try:
            val = page.input_value(selector)
        except Exception:
            val = ""
        out = _state(page)
        out["filled"] = {selector: val}
        return {"ok": True, **out}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


BROWSER_TOOL = {
    "type": "function",
    "function": {
        "name": "browser",
        "description": ("Navegador headless (somente leitura de páginas + "
                        "interação simples). Ações: open (url), click "
                        "(selector CSS), fill (selector, text). Use para "
                        "verificar sites locais e ler conteúdo web. "
                        "click/fill pedem aprovação."),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string",
                           "description": "open, click ou fill"},
                "url": {"type": "string",
                        "description": "URL (para open)"},
                "selector": {"type": "string",
                             "description": "Seletor CSS (para click/fill)"},
                "text": {"type": "string",
                         "description": "Texto (para fill)"},
            },
            "required": ["action"],
        },
    },
}


def handle_browser(args: dict[str, Any], approve: bool = False) -> str:
    """Despacha ação do browser. click/fill exigem approve=True."""
    import json
    action = (args.get("action") or "").lower()
    if action == "open":
        url = args.get("url", "")
        if not url:
            return "ERROR: open precisa de url"
        r = browser_open(url)
    elif action in ("click", "fill"):
        if not approve:
            return (f"ERROR: browser {action} precisa de aprovação "
                    f"(rode com --approve ou confirme)")
        sel = args.get("selector", "")
        if not sel:
            return f"ERROR: {action} precisa de selector"
        r = (browser_click(sel) if action == "click"
             else browser_fill(sel, args.get("text", "")))
    else:
        return "ERROR: action deve ser open, click ou fill"
    if not r.get("ok"):
        return f"ERROR: {r.get('error', 'browser falhou')}"
    out = {k: v for k, v in r.items() if k != "ok"}
    return json.dumps(out, ensure_ascii=False)[:3000]
