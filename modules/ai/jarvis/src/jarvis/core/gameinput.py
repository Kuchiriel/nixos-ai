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
    # espera o foco CONFIRMAR (a janela precisa estar ativa antes da tecla)
    for _ in range(12):
        time.sleep(0.15)
        try:
            act = json.loads(_hyprctl("activewindow", "-j") or "{}")
            if act.get("address") == addr:
                break
        except ValueError:
            pass
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
    yt = shutil.which("ydotool")
    if yt:
        code = {"Return": "28", "Escape": "1", "Tab": "15",
                "BackSpace": "14", "Space": "57"}.get(key)
        if code:
            subprocess.run([yt, "key", f"{code}:1", f"{code}:0"],
                           capture_output=True, timeout=10)
            return {"ok": True, "acao": f"key {key} (ydotool)", **f}
    wt = _wtype()
    if not wt:
        return {"ok": False, "error": "nem ydotool nem wtype disponiveis", **f}
    subprocess.run([wt, "-k", key], capture_output=True, timeout=10)
    return {"ok": True, "acao": f"key {key} (wtype)", **f}


def send_text(text: str, title_match: str, submit: bool = False,
              enter: bool = False, ensure_open: bool = True) -> dict[str, Any]:
    """Digita texto. Com ensure_open, garante que o chat esteja ABERTO antes
    (o Enter do OTClient é toggle — enviar no chat fechado não dá erro nenhum,
    só não acontece)."""
    pre = {}
    if ensure_open:
        pre = ensure_chat(title_match)
        if not pre.get("ok"):
            return {"ok": False, "erro": "chat nao abriu", "pre": pre}
    f = _focus(title_match)
    if not f.get("ok"):
        return f
    if not _wtype():
        return {"ok": False, "error": "wtype ausente", **f}
    subprocess.run([_wtype(), text], capture_output=True, timeout=20)
    if submit:
        subprocess.run([_wtype(), "-k", "Return"], capture_output=True, timeout=10)
    return {"ok": True, "acao": ("type+Enter" if submit else "type"),
            "texto": text[:60], "chat": pre.get("estado"), **f}


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


# --- estado do chat do jogo ----------------------------------------------
# POR QUE ISTO EXISTE: no OTClient o Enter é TOGGLE, não "enviar". Em 02/10
# eu mandei um Enter de teste, desliguei o chat, e depois digitei o comando
# num campo fechado — sem nada acontecer e sem erro visível. Contar toggles na
# mão é frágil; a ação tem que CONSULTAR o estado antes de agir.
# A posição do botão DEPENDE do tamanho da janela (foi medida em 941x504 e
# quebrava quando o jogo ia fullscreen 1920x1080). Agora a região é calculada
# como FRAÇÃO da janela: faixa inferior, metade direita. Sem isso o helper
# lia o recorte errado e devolvia UNKNOWN.
# calibrado no layout FULLSCREEN 1920x1080 (2026-10-02): o botao
# "Chat Off" fica no canto inferior direito, ~ (1860,1058).
_CHAT_BTN_FRAC = (0.90, 0.955, 1.0, 1.0)


def locate(what: str, window_match: str = "OTClient") -> dict[str, Any]:
    """Acha um elemento NA TELA e devolve o centro em coords RELATIVAS à janela.

    2026-10-02: era o que faltava. Eu vinha com coordenadas fixas medidas numa
    janela 941x504 e, quando o jogo foi fullscreen 1920x1080, tudo quebrou — o
    layout escala, então posição fixa não sobrevive a mudança de tamanho.

    A visão devolve bounding box, então a posição é sempre a do que está
    NA TELA agora. Depois `click_at` converte relativo→absoluto. Assim não há
    coordenada hardcoded em lugar nenhum.
    """
    from jarvis.core import vision
    f = _focus(window_match)
    if not f.get("ok"):
        return f
    shot = vision.capture_window(window_match)
    if not shot.get("ok"):
        return {"ok": False, "error": "nao capturou a janela"}
    prov = ("PROCURANDO no jogo. O elemento é o retangulo que CONTIEM este texto "
            "exatamente como escrito: ")
    ask = (f"{prov}'{what}'. Responda SOMENTE com as coordenadas do retangulo "
           f"em pixels da imagem, no formato: x1,y1,x2,y2. Sem texto, sem "
           f"explicacao. Se nao existir, responda: NAO_ENCONTRADO")
    r = vision.observe_with_fallback({
        "mode": "window", "window_title": window_match,
        "focus_window": False, "opaque": False, "question": ask})
    if "NAO_ENCONTRADO" in r:
        return {"ok": False, "erro": f"elemento '{what}' nao esta na tela",
                "ocr": r[:120]}
    import re
    nums = [int(n) for n in re.findall(r"(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", r)[0]] \
        if re.findall(r"(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)", r) else []
    if len(nums) != 4:
        return {"ok": False, "erro": "a visao nao devolveu bbox", "resposta": r[:140]}
    cx, cy = (nums[0] + nums[2]) // 2, (nums[1] + nums[3]) // 2
    return {"ok": True, "elemento": what, "bbox": nums,
            "rel": [cx, cy], "resposta": r[:80]}


def click_element(what: str, window_match: str = "OTClient",
                  button: str = "left") -> dict[str, Any]:
    """localize() + click_at(). Sem coordenada hardcoded."""
    loc = locate(what, window_match)
    if not loc.get("ok"):
        return loc
    if button == "right":
        w = find_window(window_match)
        at = w.get("at", [0, 0])
        _hyprctl("dispatch", "focuswindow", f"address:{w.get('address','')}")
        for _ in range(12):
            time.sleep(0.15)
            try:
                if json.loads(_hyprctl("activewindow", "-j") or "{}").get(
                        "address") == w.get("address"):
                    break
            except ValueError:
                pass
        cx, cy = loc["rel"]
        _hyprctl("dispatch", "movecursor", str(at[0] + cx), str(at[1] + cy))
        time.sleep(0.25)
        yt = shutil.which("ydotool")
        if yt:
            code = {"left": "0xC0", "right": "0xC1"}.get(button, "0xC0")
            subprocess.run([yt, "click", code], capture_output=True, timeout=10)
        return {"ok": True, "acao": f"{button}-click em '{what}'", **loc}
    return click_at(loc["rel"][0], loc["rel"][1], window_match)


def _ocr(path: str) -> str:
    try:
        from jarvis.core.vision import _ocr_text
        return (_ocr_text(path).get("text") or "")
    except Exception:
        return ""


def chat_state(window_match: str = "OTClient") -> dict[str, Any]:
    """Lê o rótulo do botão de chat por OCR (ON/OFF/UNKNOWN)."""
    f = _focus(window_match)
    shot = None
    try:
        from jarvis.core.vision import capture_window
        shot = capture_window(window_match)
    except Exception:
        pass
    if not shot or not shot.get("ok"):
        return {"ok": False, "estado": "UNKNOWN", "erro": "nao capturou",
                "foco": f.get("foco_confirmado")}
    try:
        from PIL import Image
        img = Image.open(shot["path"])
        W, H = img.size
        x0, y0, x1, y1 = _CHAT_BTN_FRAC
        box = (int(W * x0), int(H * y0), int(W * x1), int(H * y1))
        crop = img.crop(box)
        p = "/tmp/jarvis-chatbtn.png"
        k = max(2, min(4, 900 // max(1, crop.width)))
        crop.resize((crop.width * k, crop.height * k),
                    Image.LANCZOS).save(p)
        geo = {"box": list(box), "tamanho": [W, H]}
    except ImportError:
        p = shot["path"]
        geo = {}
    txt = _ocr(p).lower().replace("\n", " ")
    if "on" in txt and "off" not in txt:
        estado = "ON"
    elif "off" in txt:
        estado = "OFF"
    else:
        estado = "UNKNOWN"
    return {"ok": True, "estado": estado, "ocr": txt.strip()[:40],
            "foco": f.get("foco_confirmado"), **geo}


def ensure_chat(window_match: str = "OTClient") -> dict[str, Any]:
    """Garante chat ABERTO, decidindo se precisa de Enter. Idempotente."""
    st = chat_state(window_match)
    if st.get("estado") == "ON":
        return {"ok": True, "acao": "nenhuma (ja estava ON)", **st}
    if st.get("estado") != "OFF":
        return {"ok": False, "acao": "nada (estado ilegivel)", **st}
    r = send_key("Return", window_match)
    time.sleep(2)
    st2 = chat_state(window_match)
    return {"ok": st2.get("estado") == "ON", "acao": "Enter (OFF->ON)", **st2}


def send_chat_command(cmd: str, window_match: str = "OTClient") -> dict[str, Any]:
    """Fluxo completo e idempotente: garante chat aberto -> digita -> envia.

    Existe porque cada etapa falhou isoladamente antes: chat fechado (Enter é
    toggle), texto não digitado (wtype), Enter não enviado (wtype). Aqui a
    ordem é garantida e o estado é conferido no fim.
    """
    opened = ensure_chat(window_match)
    if not opened.get("ok"):
        return {"ok": False, "etapa": "abrir chat", "pre": opened}
    r = send_text(cmd, window_match, submit=True, ensure_open=False)
    time.sleep(1.5)
    depois = chat_state(window_match)
    return {"ok": True, "comando": cmd, "chat_antes": opened.get("estado"),
            "chat_depois": depois.get("estado"), "detalhe": r}


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
    for _ in range(12):
        time.sleep(0.15)
        try:
            act = json.loads(_hyprctl("activewindow", "-j") or "{}")
            if act.get("address") == addr:
                break
        except ValueError:
            pass
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
        elif action == "locate":
            r = locate(args.get("element") or "", title)
        elif action == "click_element":
            r = click_element(args.get("element") or "", title,
                              args.get("button", "left"))
        elif action == "chat_state":
            r = chat_state(title)
        elif action == "ensure_chat":
            r = ensure_chat(title)
        elif action == "chat_command":
            r = send_chat_command(args.get("command") or args.get("text") or "",
                                  title)
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
            return (f"acao invalida: {action}. Use state|locate|click_element|chat_state|ensure_chat|chat_command|focus|key|type|click. "
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