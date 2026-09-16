"""Browser tool do Agent (Playwright headless persistente).

Ações: open(url) → título+texto; click(selector) → estado;
fill(selector, text) → estado; press(key) → teclado; scroll(dy) → página;
extract(selector) → lista de textos; wait(selector) → espera elemento;
snapshot() → título+elementos.
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


def browser_press(selector: str, key: str) -> dict[str, Any]:
    """Tecla no teclado (mutação: harness pede aprovação antes).

    Foca num elemento (se passado) e envia a tecla (Enter, Tab, ArrowDown…).
    Útil para formulários que fill não dispara (onChange/onKeydown).
    """
    if not key:
        return {"ok": False, "error": "press precisa de key (ex.: Enter)"}
    try:
        page = _ensure()
        if selector:
            page.focus(selector, timeout=10000)
        page.keyboard.press(key)
        page.wait_for_timeout(300)
        out = _state(page)
        out["pressed"] = key
        return {"ok": True, **out}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def browser_scroll(dy: int = 600) -> dict[str, Any]:
    """Rola a página (leitura: revela conteúdo abaixo da dobra)."""
    try:
        page = _ensure()
        page.mouse.wheel(0, int(dy))
        page.wait_for_timeout(300)
        return {"ok": True, "scrolled": int(dy), **_state(page)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def browser_extract(selector: str) -> dict[str, Any]:
    """Extrai textos de todos os elementos que casam com o seletor (leitura).

    Mais cirúrgico que o texto do body: lista item-a-item (links, rows,
    cards) — o modelo lê a lista sem 1500 chars de ruído.
    """
    if not selector:
        return {"ok": False, "error": "extract precisa de selector"}
    try:
        page = _ensure()
        els = page.query_selector_all(selector)
        items = [(e.inner_text() or "").strip()[:200]
                 for e in els[:50] if (e.inner_text() or "").strip()]
        return {"ok": True, "selector": selector, "items": items,
                "total": len(items), "url": page.url}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def browser_wait(selector: str, timeout_ms: int = 10000) -> dict[str, Any]:
    """Espera elemento aparecer (leitura: sincroniza com SPA/carregamento)."""
    if not selector:
        return {"ok": False, "error": "wait precisa de selector"}
    try:
        page = _ensure()
        page.wait_for_selector(selector, timeout=int(timeout_ms))
        return {"ok": True, "appeared": selector, **_state(page)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


BROWSER_TOOL = {
    "type": "function",
    "function": {
        "name": "browser",
        "description": ("Navegador headless (leitura + interação). Ações: "
                        "open (url), click (selector), fill (selector, text), "
                        "press (selector?, key — teclado), scroll (dy), "
                        "extract (selector — lista de textos), wait "
                        "(selector — espera carregar). Use para verificar "
                        "sites locais e ler conteúdo web. click/fill/press "
                        "pedem aprovação; scroll/extract/wait são leitura."),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string",
                           "description": ("open, click, fill, press, scroll, "
                                           "extract ou wait")},
                "url": {"type": "string",
                        "description": "URL (para open)"},
                "selector": {"type": "string",
                             "description": "Seletor CSS (click/fill/press/extract/wait)"},
                "text": {"type": "string",
                         "description": "Texto (para fill)"},
                "key": {"type": "string",
                        "description": "Tecla (para press: Enter, Tab, ArrowDown)"},
                "dy": {"type": "integer",
                       "description": "Pixels de rolagem (para scroll, default 600)"},
            },
            "required": ["action"],
        },
    },
}


def handle_browser(args: dict[str, Any], approve: bool = False) -> str:
    """Despacha ação do browser. Mutações (click/fill/press) exigem approve."""
    import json
    action = (args.get("action") or "").lower()
    if action == "open":
        url = args.get("url", "")
        if not url:
            return "ERROR: open precisa de url"
        r = browser_open(url)
    elif action in ("click", "fill", "press"):
        if not approve:
            return (f"ERROR: browser {action} precisa de aprovação "
                    f"(rode com --approve ou confirme)")
        sel = args.get("selector", "")
        if action == "press":
            r = browser_press(sel, args.get("key", ""))
        elif not sel:
            return f"ERROR: {action} precisa de selector"
        elif action == "click":
            r = browser_click(sel)
        else:
            r = browser_fill(sel, args.get("text", ""))
    elif action == "scroll":
        r = browser_scroll(args.get("dy", 600))
    elif action == "extract":
        r = browser_extract(args.get("selector", ""))
    elif action == "wait":
        r = browser_wait(args.get("selector", ""),
                         args.get("timeout", 10000))
    else:
        return ("ERROR: action deve ser open, click, fill, press, "
                "scroll, extract ou wait")
    if not r.get("ok"):
        return f"ERROR: {r.get('error', 'browser falhou')}"
    out = {k: v for k, v in r.items() if k != "ok"}
    return json.dumps(out, ensure_ascii=False)[:3000]
