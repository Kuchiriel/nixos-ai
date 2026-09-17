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
_cdp_url = ""


def cdp_attach(url: str = "http://127.0.0.1:9222") -> dict[str, Any]:
    """Anexa ao browser JÁ RODANDO (sessão logada do dono) via CDP.

    Diferente do headless próprio (sem login), aqui o page é o do
    usuário — Colab logado, cookies, abas. Uma chamada, reutilizado
    nas seguintes (sessão persistente no módulo).
    """
    global _pw, _page, _cdp_url
    try:
        if _pw is None:
            from playwright.sync_api import sync_playwright
            _pw = sync_playwright().start()
        b = _pw.chromium.connect_over_cdp(url)
        ctx = b.contexts[0] if b.contexts else b.new_context()
        _page = ctx.pages[0] if ctx.pages else ctx.new_page()
        _cdp_url = url
        return {"ok": True, "title": _page.title()[:80],
                "url": _page.url[:120]}
    except Exception as e:
        return {"ok": False, "error": str(e)[:200]}


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


# ── Layer 2: interação resiliente (lições Colab 17/09) ──
# Primitivas que sobrevivem a shadow DOM, menus que fecham e rects
# zerados. O LLM entende por nome; o harness resolve o COMO.

_LEAF_JS = """(text) => {
  const els = Array.from(document.querySelectorAll('*')).filter(function(e) {
    return e.children.length === 0 && (e.innerText || '').trim() === text;
  });
  if (!els.length) return null;
  const r = els[0].getBoundingClientRect();
  return [r.x + r.width / 2, r.y + r.height / 2];
}"""


def browser_click_text(text: str) -> dict[str, Any]:
    """Clica elemento pelo TEXTO visível exato (mutação: pede aprovação).

    Resolve menus/itens sem depender de seletor CSS — o que o LLM vê
    ("Alterar o tipo") é o que clica. Retorna erro claro se ausente.
    """
    if not text:
        return {"ok": False, "error": "click_text precisa de text"}
    try:
        page = _ensure()
        box = page.evaluate(_LEAF_JS, text)
        if not box or not box[0]:
            return {"ok": False,
                    "error": f"texto não encontrado ou sem área: {text[:60]}"}
        page.mouse.click(box[0], box[1])
        page.wait_for_timeout(500)
        return {"ok": True, "clicked_text": text[:60], **_state(page)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def browser_menu_flow(items: list) -> dict[str, Any]:
    """Navega menu + item(ns) NUMA sessão (mutação: pede aprovação).

    Menus fecham entre calls separadas — aqui abrir e clicar acontecem
    sem soltar o DOM. items: ["Ambiente de execução",
    "Alterar o tipo de ambiente de execução"].
    """
    if not items or len(items) < 1:
        return {"ok": False, "error": "menu precisa de items (lista)"}
    try:
        page = _ensure()
        import time as _t
        for i, label in enumerate(items):
            box = page.evaluate(_LEAF_JS, label)
            if box and box[0]:
                page.mouse.click(box[0], box[1])
            else:
                # fallback: seta+Enter (navegação por teclado)
                page.keyboard.press("ArrowDown")
            _t.sleep(1.5)
            if i < len(items) - 1:
                # re-localiza o próximo item (menu pode ter re-renderizado)
                continue
        page.wait_for_timeout(1000)
        return {"ok": True, "menu": " → ".join(items)[:100],
                **_state(page)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def browser_shadow_click(host_sel: str, inner_sel: str) -> dict[str, Any]:
    """Clica dentro de shadow DOM (mutação: pede aprovação).

    Componentes web (Colab: colab-connect-button#connect-icon) escondem
    o botão real no shadow root — seletor CSS normal nunca alcança.
    """
    if not host_sel or not inner_sel:
        return {"ok": False,
                "error": "shadow precisa de host_sel + inner_sel"}
    try:
        page = _ensure()
        r = page.evaluate("""([h, s]) => {
          const host = document.querySelector(h);
          if (!host || !host.shadowRoot) return 'no-host';
          const btn = host.shadowRoot.querySelector(s);
          if (!btn) return 'no-inner';
          btn.click();
          return 'clicked';
        }""", [host_sel, inner_sel])
        page.wait_for_timeout(500)
        if r != "clicked":
            return {"ok": False, "error": f"shadow: {r}"}
        return {"ok": True, "shadow": f"{host_sel} {inner_sel}",
                **_state(page)}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


def browser_wait_text(text: str, timeout_ms: int = 30000) -> dict[str, Any]:
    """Espera TEXTO aparecer na página (leitura: polling, sem seletor).

    Para fluxos longos (alocação de runtime, treino) onde o seletor é
    desconhecido mas o texto-alvo é ("Conectado", "RAM", "100%").
    """
    if not text:
        return {"ok": False, "error": "wait_text precisa de text"}
    try:
        page = _ensure()
        import time as _t
        end = _t.monotonic() + int(timeout_ms) / 1000
        while _t.monotonic() < end:
            try:
                body = page.inner_text("body")
            except Exception:
                body = ""
            if text.lower() in body.lower():
                return {"ok": True, "found": text[:60], **_state(page)}
            _t.sleep(2)
        return {"ok": False, "error": f"texto não apareceu em {timeout_ms}ms: {text[:60]}"}
    except Exception as e:
        return {"ok": False, "error": str(e)[:300]}


BROWSER_TOOL = {
    "type": "function",
    "function": {
        "name": "browser",
        "description": ("Navegador (próprio ou do dono via attach) — "
                        "leitura + interação. Ações: "
                        "open (url), click (selector), fill (selector, text), "
                        "press (selector?, key), scroll (dy), "
                        "extract (selector), wait (selector), "
                        "attach (cdp_url — dirige o browser LOGADO do dono), "
                        "click_text (text — clica pelo texto visível), "
                        "menu (items — navega menu+item numa sessão), "
                        "shadow (host_sel+inner_sel — dentro de shadow DOM), "
                        "wait_text (text — espera texto aparecer). "
                        "click/fill/press/click_text/menu/shadow pedem "
                        "aprovação; resto é leitura."),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {"type": "string",
                           "description": ("open, click, fill, press, scroll, "
                                           "extract, wait, attach, click_text, "
                                           "menu, shadow ou wait_text")},
                "url": {"type": "string",
                        "description": "URL (para open; cdp_url p/ attach)"},
                "selector": {"type": "string",
                             "description": "Seletor CSS (click/fill/press/extract/wait; host p/ shadow)"},
                "text": {"type": "string",
                         "description": "Texto (fill; click_text; wait_text; inner p/ shadow)"},
                "key": {"type": "string",
                        "description": "Tecla (para press: Enter, Tab, ArrowDown)"},
                "dy": {"type": "integer",
                       "description": "Pixels de rolagem (para scroll, default 600)"},
                "items": {"type": "array",
                          "description": "Lista p/ menu (ex.: ['Arquivo', 'Salvar'])",
                          "items": {"type": "string"}},
                "timeout": {"type": "integer",
                            "description": "Ms p/ wait/wait_text (default 10000/30000)"},
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
    elif action in ("click", "fill", "press", "click_text", "menu",
                      "shadow"):
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
    elif action == "attach":
        r = cdp_attach(args.get("url") or "http://127.0.0.1:9222")
    elif action == "click_text":
        r = browser_click_text(args.get("text", ""))
    elif action == "menu":
        items = args.get("items", [])
        if isinstance(items, str):
            items = [items]
        r = browser_menu_flow(items)
    elif action == "shadow":
        r = browser_shadow_click(args.get("selector", ""),
                                 args.get("text", ""))
    elif action == "wait_text":
        r = browser_wait_text(args.get("text", ""),
                              args.get("timeout", 30000))
    else:
        return ("ERROR: action deve ser open, click, fill, press, "
                "scroll, extract, wait, attach, click_text, menu, "
                "shadow ou wait_text")
    if not r.get("ok"):
        return f"ERROR: {r.get('error', 'browser falhou')}"
    out = {k: v for k, v in r.items() if k != "ok"}
    return json.dumps(out, ensure_ascii=False)[:3000]
