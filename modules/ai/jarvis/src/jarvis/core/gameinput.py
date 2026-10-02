"""gameinput — window focus, mouse e teclado no Hyprland (2026-10-02).

POR QUE ISTO EXISTE (e o que deu errado antes):

1. `hyprctl dispatch focuswindow title:OTClient` → "No such window found".
   O OTClient tem **class vazio** e o title real é "OTClient - Redemption";
   no Hyprland o seletor por title é regex exato. A forma que funciona é
   `address:0x…`, e o address só é único por janela.
2. Sem foco certo, a tecla vai para a janela errada. No dia 02/10 um `Enter`
   foi parar num dos dois terminais do opencode porque havia 3 janelas e o
   alvo nunca foi focalizado. Daí o chat do jogo nunca abriu.
3. Digitar sem o mouse sobre a janela é aposta: alguns clientes ignoram
   entrada de teclado sem foco de ponteiro.

O que este módulo faz, em ordem: acha a janela por substring do title → foca
pelo address → move o mouse para o centro → executa a ação (tecla/texto/
clique). Cada passo é verificável e o estado é reportável.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from typing import Any


def _hyprctl(*args: str, timeout: float = 5.0) -> str:
    if not shutil.which("hyprctl"):
        raise RuntimeError("hyprctl ausente (não é Hyprland?)")
    out = subprocess.run(["hyprctl", *args], capture_output=True, text=True,
                         timeout=timeout)
    return out.stdout or ""


def _clients() -> list[dict[str, Any]]:
    try:
        return json.loads(_hyprctl("clients", "-j") or "[]")
    except (ValueError, RuntimeError):
        return []


def find_window(title_match: str) -> dict[str, Any] | None:
    """Janela cujo title CONTEINS title_match. Address é a chave confiável."""
    hits = [c for c in _clients() if title_match.lower()
            in (c.get("title") or "").lower()]
    if not hits:
        return None
    # se houver varias com o mesmo trecho, a de maior area e a do jogo
    hits.sort(key=lambda c: (c.get("size", [0, 0])[0] * c.get("size", [0, 0])[1]),
                   reverse=True)
    return hits[0]


def window_state(title_match: str) -> dict[str, Any]:
    """Address, título, geometria e qual janela está focada AGORA."""
    w = find_window(title_match)
    try:
        active = json.loads(_hyprctl("activewindow", "-j") or "{}")
    except ValueError:
        active = {}
    return {
        "encontrada": bool(w),
        "address": (w or {}).get("address", ""),
        "title": (w or {}).get("title", ""),
        "at": (w or {}).get("at", []),
        "size": (w or {}).get("size", []),
        "foco_address": active.get("address", ""),
        "foco_title": active.get("title", ""),
        "foco_e_o_alvo": bool(w) and active.get("address") == w.get("address"),
    }


def _focus(title_match: str) -> dict[str, Any]:
    """Foca a janela pelo address e põe o mouse no centro dela."""
    w = find_window(title_match)
    if not w:
        return {"ok": False,
                "error": f"janela '{title_match}' nao encontrada",
                "janelas": [c.get("title", "")[:30] for c in _clients()]}
    addr = w.get("address", "")
    _hyprctl("dispatch", "focuswindow", f"address:{addr}")
    at, size = w.get("at", [0, 0]), w.get("size", [0, 0])
    cx = at[0] + size[0] // 2
    cy = at[1] + size[1] // 2
    _hyprctl("dispatch", "movecursor", str(cx), str(cy))
    st = window_state(title_match)
    return {"ok": bool(st.get("foco_e_o_alvo")), "address": addr,
            "title": w.get("title", ""), "mouse": [cx, cy],
            "geom": [at[0], at[1], size[0], size[1]],
            "foco_confirmado": st.get("foco_e_o_alvo"),
            "atencao": ("" if st.get("foco_e_o_alvo") else
                        "foco NAO confirmado — a tecla pode ir para outro "
                        f"programa (focada: {st.get('foco_title','')[:30]!r})")}


def _wtype() -> str | None:
    return shutil.which("wtype")


def send_key(key: str, title_match: str) -> dict[str, Any]:
    f = _focus(title_match)
    if not f.get("ok"):
        return f
    if not _wtype():
        return {"ok": False, "error": "wtype ausente (home-manager/home-packages.nix)",
                **f}
    subprocess.run([_wtype(), "-k", key], capture_output=True, timeout=10)
    return {"ok": True, "acao": f"key {key}", **f}


def send_text(text: str, title_match: str, submit: bool = False,
              enter: bool = False) -> dict[str, Any]:
    f = _focus(title_match)
    if not f.get("ok"):
        return f
    if not _wtype():
        return {"ok": False, "error": "wtype ausente", **f}
    subprocess.run([_wtype(), text], capture_output=True, timeout=20)
    if submit:
        subprocess.run([_wtype(), "-k", "Return"], capture_output=True, timeout=10)
    return {"ok": True, "acao": ("type+Enter" if submit else "type"),
            "texto": text[:60], **f}


def click(button: str = "left", title_match: str = "") -> dict[str, Any]:
    if not title_match:
        return {"ok": False, "error": "informe window_title (clicar em janela errada é perigoso)"}
    f = _focus(title_match)
    if not f.get("ok"):
        return f
    # ydotool só faz clique por código de botão
    btn = {"left": "0xC0", "right": "0xC1", "middle": "0xC2"}.get(button, "0xC0")
    yt = shutil.which("ydotool")
    if not yt:
        return {"ok": False, "error": "ydotool ausente", **f}
    subprocess.run([yt, "click", btn], capture_output=True, timeout=10)
    return {"ok": True, "acao": f"click {button}", **f}


def click_at(x: int, y: int, window_match: str = "OTClient") -> dict[str, Any]:
    """Clica em coordenada RELATIVA à janela (o que permite mirar num botão).

    Por que relativo e não absoluto: a janela se move (Hyprland, fullscreen),
    e mirar num botão do jogo por pixel absoluto erra a cada mudança de
    layout. Uso: leio a captura, identifico o alvo em coordenadas da janela e
    clico相对 — o offsets é calculado aqui a partir da geometria real.
    """
    w = find_window(window_match)
    if not w:
        return {"ok": False, "error": f"janela '{window_match}' nao encontrada"}
    addr = w.get("address", "")
    _hyprctl("dispatch", "focuswindow", f"address:{addr}")
    at = w.get("at", [0, 0])
    ax, ay = at[0] + x, at[1] + y
    _hyprctl("dispatch", "movecursor", str(ax), str(ay))
    yt = shutil.which("ydotool")
    if not yt:
        return {"ok": False, "error": "ydotool ausente", "abs": [ax, ay]}
    time.sleep(0.25)
    subprocess.run([yt, "click", "0xC0"], capture_output=True, timeout=10)
    return {"ok": True, "acao": f"click em relativo({x},{y})",
            "address": addr, "abs": [ax, ay]}


def handle(args: dict[str, Any]) -> str:
    """Entrada do MCP."""
    action = (args.get("action") or "state").lower()
    title = args.get("window_title") or "OTClient"
    try:
        if action == "state":
            r = window_state(title)
        elif action == "focus":
            r = _focus(title)
        elif action in ("key", "press"):
            r = send_key(args.get("key", "Return"), title)
        elif action == "type":
            r = send_text(args.get("text", ""), title,
                          submit=bool(args.get("submit")),
                          enter=bool(args.get("enter")))
        elif action == "click":
            if args.get("x") is not None and args.get("y") is not None:
                r = click_at(int(args["x"]), int(args["y"]),
                             args.get("window_title") or title)
            else:
                r = click(args.get("button", "left"), title)
        else:
            return (f"acao invalida: {action}. Use state|focus|key|type|click. "
                    "Teclas: Return, Escape, Tab, BackSpace, F1…")
        return json.dumps(r, ensure_ascii=False)
    except Exception as e:                      # nunca levanta no MCP
        return json.dumps({"ok": False, "error": f"{type(e).__name__}: {e}"},
                          ensure_ascii=False)


GAMEINPUT_TOOL = {
    "name": "jarvis_input",
    "description": (
        "Foca uma janela, move o mouse e envia tecla/texto no desktop "
        "(Hyprland). USE SEMPRE antes de digitar em qualquer janela: no "
        "Hyprland `focuswindow title:...` falha (class vazio) e a tecla vai "
        "para o programa errado. Actions: state (address + qual janela está "
        "focada), focus (foca + mouse no centro), key (ex: Return, Escape), "
        "type (texto, submit=true envia com Enter), click. SEMPRE exija "
        "window_title: sem ele a tecla pode ir para outro terminal."),
    "inputSchema": {
        "type": "object",
        "properties": {
            "action": {
                "type": "string",
                "enum": ["state", "focus", "key", "type", "click"],
                "description": "state=diagnóstico; focus=foca+mouse; key=tecla; type=texto; click=clique",
            },
            "window_title": {
                "type": "string",
                "description": "Trecho do title da janela alvo (ex: OTClient). OBRIGATÓRIO na prática.",
            },
            "key": {
                "type": "string",
                "description": "Tecla para action=key (wtype): Return, Escape, Tab, BackSpace, F1, Up…",
            },
            "text": {
                "type": "string",
                "description": "Texto para action=type.",
            },
            "submit": {
                "type": "boolean",
                "description": "Com action=type, envia Enter depois do texto.",
            },
            "x": {"type": "integer",
                  "description": "Coordenada X RELATIVA à janela (para action=click num botão)."},
            "y": {"type": "integer",
                  "description": "Coordenada Y RELATIVA à janela."},
            "button": {
                "type": "string",
                "enum": ["left", "right", "middle"],
                "description": "Botão para action=click.",
            },
        },
        "required": ["action"],
    },
}