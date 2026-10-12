"""Vision local — captura de tela e contexto visual via Hyprland/Wayland.

Pipeline:
  1. `grim` captura tela (Wayland-native, sem X11)
  2. `slurp` permite seleção de região (opcional)
  3. Imagem salva em /tmp/jarvis-screenshot.png
  4. (futuro) Análise via LLM local com vision (Qwen-VL)

Fallback gracioso: se grim/slurp não existem (SSH/VM sem display),
retorna erro claro em vez de exception.

Integração com o agente: tool call `capture_screen` disponível
para o agente analisar erros visuais (ex: erros de terminal, estado da tela).
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

SCREENSHOT_DIR = Path(os.environ.get("JARVIS_SCREENSHOT_DIR", "/tmp"))

# CAUSA RAIZ (2026-10-02): TODAS as APIs de visão rejeitavam o request porque
# o python-urllib envia `User-Agent: Python-urllib/3.13`, que a borda bloqueia:
#   - Groq     -> 403 Cloudflare "error code: 1010"
#   - Gemini   -> 401 "invalid authentication credentials"
# Com um UA de cliente HTTP normal, as MESMAS chaves passaram. Sem isto a
# cascata jurava que as chaves estavam mortas e eu quase aposentei as 4.
_UA = "curl/8.6.0 (jarvis-vision)"
_HEADERS = {"Content-Type": "application/json", "User-Agent": _UA}


def _http_get(url: str, headers: dict[str, str],
              timeout: float) -> Any:
    """GET JSON com User-Agent garantido."""
    h = dict(_HEADERS)
    h.update(headers)
    req = urllib.request.Request(url, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())


def _http_json(url: str, payload: bytes, headers: dict[str, str],
               timeout: float) -> dict[str, Any]:
    """POST JSON com User-Agent garantido. Erros HTTP voltam como dict."""
    h = dict(_HEADERS)
    h.update(headers)
    req = urllib.request.Request(url, data=payload, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode())
SCREENSHOT_PREFIX = "jarvis-screenshot"


def _has_display() -> bool:
    """Verifica se há display gráfico disponível."""
    return bool(os.environ.get("WAYLAND_DISPLAY") or os.environ.get("DISPLAY"))


def _has_binary(name: str) -> bool:
    return shutil.which(name) is not None


def capture_full(timeout: float = 5.0) -> dict[str, Any]:
    """Captura tela inteira.

    Returns:
        {"ok": True, "path": "/tmp/jarvis-screenshot-12345.png", "size_kb": 123}
        ou {"ok": False, "error": "..."}
    """
    if not _has_display():
        return {"ok": False, "error": "sem display gráfico (WAYLAND_DISPLAY/DISPLAY não definido)"}
    if not _has_binary("grim"):
        return {"ok": False, "error": "grim não encontrado no PATH (instale: nix-env -iA nixpkgs.grim)"}

    ts = int(time.time())
    path = SCREENSHOT_DIR / f"{SCREENSHOT_PREFIX}-{ts}.png"

    try:
        result = subprocess.run(
            ["grim", str(path)],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            return {"ok": False, "error": f"grim falhou: {result.stderr.strip()[:200]}"}
        if not path.exists():
            return {"ok": False, "error": "grim executou mas arquivo não foi criado"}
        size_kb = path.stat().st_size // 1024
        return {"ok": True, "path": str(path), "size_kb": size_kb}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"grim timeout após {timeout}s"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": f"erro ao executar grim: {exc}"}


def capture_region(timeout: float = 10.0) -> dict[str, Any]:
    """Captura região selecionada via slurp + grim.

    Returns:
        {"ok": True, "path": "...", "size_kb": ...}
    """
    if not _has_display():
        return {"ok": False, "error": "sem display gráfico"}
    if not _has_binary("slurp") or not _has_binary("grim"):
        return {"ok": False, "error": "slurp ou grim não encontrado no PATH"}

    ts = int(time.time())
    path = SCREENSHOT_DIR / f"{SCREENSHOT_PREFIX}-region-{ts}.png"

    try:
        # slurp seleciona a região → grim captura
        sel = subprocess.run(
            ["slurp"], capture_output=True, text=True, timeout=timeout,
        )
        if sel.returncode != 0:
            return {"ok": False, "error": "seleção cancelada ou slurp falhou"}
        region = sel.stdout.strip()
        if not region:
            return {"ok": False, "error": "slurp retornou região vazia"}

        result = subprocess.run(
            ["grim", "-g", region, str(path)],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            return {"ok": False, "error": f"grim falhou: {result.stderr.strip()[:200]}"}
        if not path.exists():
            return {"ok": False, "error": "grim executou mas arquivo não foi criado"}
        size_kb = path.stat().st_size // 1024
        return {"ok": True, "path": str(path), "size_kb": size_kb}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout após {timeout}s"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": f"erro: {exc}"}



def _hyprctl_raw(*args: str) -> str:
    import subprocess as _sp
    # Sem a assinatura do Hyprland o `hyprctl` devolve VAZIO e o
    # capture_window/capture_region falham sem erro claro (2026-10-02). O
    # saneamento mora em gameinput (fonte única) — aqui só delegamos.
    try:
        from jarvis.core.gameinput import _hyprctl
        return _hyprctl(*args)
    except Exception:
        try:
            return _sp.run(["hyprctl", *args], capture_output=True,
                           text=True, timeout=5).stdout or ""
        except (OSError, _sp.SubprocessError):
            return ""
    except (OSError, _sp.SubprocessError):
        return ""


def _prepare_window(window_title: str, opaque: bool = True) -> dict[str, Any]:
    """Foca a janela e tira a TRANSPARÊNCIA antes de capturar (2026-10-02).

    Dois problemas que só aparecem em jogo/terminal, medidos hoje:

    - TRANSPARÊNCIA: o Hyprland deixa a janela do OTClient (e o terminal)
      semitransparentes. Grim captura o que está COMPOSTO por baixo, então o
      OCR lia o opencode por trás do jogo e a visão descrevia a janela errada.
      `opaque/alpha 1, noblur 1, nofade 1` na regra da janela resolve.
    - FOCO: sem focar, o keystroke vai para o terminal em vez do jogo.

    Devolve o que foi feito (e um aviso se o foco não pegou) para o chamador
    reportar — não engole a falha, porque "digitei e nada aconteceu" sem
    explicação é o pior debug do mundo.
    """
    out: dict[str, Any] = {"window": window_title, "opaque": False,
                           "focado": False}
    try:
        from jarvis.core.gameinput import find_window
        w = find_window(window_title)
    except Exception as e:
        return {**out, "erro": f"hyprctl indisponivel: {e}"}
    if not w:
        return {**out, "erro": f"janela '{window_title}' nao encontrada"}

    addr = w.get("address", "")
    at, size = w.get("at", [0, 0]), w.get("size", [0, 0])
    # focus + mouse no centro (o jogo precisa do ponteiro sobre ele)
    subprocess.run(["hyprctl", "dispatch", "focuswindow", f"address:{addr}"],
                   capture_output=True, timeout=5)
    # Dorme e CONFIRMA o foco antes de qualquer tecla. Sem esta espera o
    # keystroke é disparado com a janela ainda inativa e se perde — foi
    # exatamente o sintoma medido em 02/10 (Enter não abria o chat).
    focado = False
    for _ in range(12):
        time.sleep(0.15)
        try:
            act = json.loads(_hyprctl_raw("activewindow", "-j") or "{}")
            if act.get("address") == addr:
                focado = True
                break
        except ValueError:
            pass
    subprocess.run(["hyprctl", "dispatch", "movecursor",
                    str(at[0] + size[0] // 2), str(at[1] + size[1] // 2)],
                   capture_output=True, timeout=5)
    out["address"] = addr
    out["focado"] = focado
    if not focado:
        out["erro"] = "foco nao confirmado apos 1.8s"

    # tira transparência só nesta janela (regra temporária, some ao fechar)
    try:
        if not opaque:
            return out
        # sem o address a regra vira global; restringe por address
        subprocess.run(["hyprctl", "keyword", "windowrule",
                        f"opaque/alpha 1, noblur 1, nofade 1, address:{addr}"],
                       capture_output=True, timeout=5)
        out["opaque"] = True
    except Exception as e:
        out["erro_opacity"] = str(e)[:80]
    time.sleep(0.6)      # deixa o compositor reaplicar antes de capturar
    return out

def capture_window(window_title: str | None = None, timeout: float = 5.0) -> dict[str, Any]:
    """Captura uma janela específica via hyprctl + grim.

    Se window_title não for fornecido, captura a janela ativa.
    """
    if not _has_display():
        return {"ok": False, "error": "sem display gráfico"}

    ts = int(time.time())
    path = SCREENSHOT_DIR / f"{SCREENSHOT_PREFIX}-window-{ts}.png"

    # Obtém geometria da janela via hyprctl
    try:
        if window_title:
            proc = subprocess.run(
                ["hyprctl", "clients", "-j"],
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode == 0:
                clients = json.loads(proc.stdout)
                target = None
                for c in clients:
                    title = c.get("title", "")
                    if window_title.lower() in title.lower():
                        target = c
                        break
                if not target:
                    return {"ok": False, "error": f"janela '{window_title}' não encontrada"}
                geom = target.get("at", [0, 0])
                size = target.get("size", [800, 600])
                region = f"{geom[0]},{geom[1]} {size[0]}x{size[1]}"
            else:
                return {"ok": False, "error": "hyprctl clients falhou"}
        else:
            # Janela ativa
            proc = subprocess.run(
                ["hyprctl", "activewindow", "-j"],
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode == 0:
                win = json.loads(proc.stdout)
                geom = win.get("at", [0, 0])
                size = win.get("size", [800, 600])
                region = f"{geom[0]},{geom[1]} {size[0]}x{size[1]}"
            else:
                return {"ok": False, "error": "hyprctl activewindow falhou"}
    except (OSError, subprocess.SubprocessError, ValueError) as exc:
        return {"ok": False, "error": f"erro ao obter geometria: {exc}"}

    if not _has_binary("grim"):
        return {"ok": False, "error": "grim não encontrado"}

    try:
        result = subprocess.run(
            ["grim", "-g", region, str(path)],
            capture_output=True, text=True, timeout=timeout,
        )
        if result.returncode != 0:
            return {"ok": False, "error": f"grim falhou: {result.stderr.strip()[:200]}"}
        if not path.exists():
            return {"ok": False, "error": "grim executou mas arquivo não foi criado"}
        size_kb = path.stat().st_size // 1024
        return {"ok": True, "path": str(path), "size_kb": size_kb, "region": region}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": f"timeout após {timeout}s"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": f"erro: {exc}"}


def cleanup_old_screenshots(max_age_s: int = 3600) -> int:
    """Remove screenshots antigos (> max_age_s segundos). Retorna quantidade removida."""
    now = time.time()
    removed = 0
    try:
        for f in SCREENSHOT_DIR.glob(f"{SCREENSHOT_PREFIX}*.png"):
            if now - f.stat().st_mtime > max_age_s:
                f.unlink()
                removed += 1
    except OSError:
        pass
    return removed


# ---------------------------------------------------------------------------
# Tool definition para o agente
# ---------------------------------------------------------------------------

VISION_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "capture_screen",
        "description": "Capture the screen (full, region, or active window) for visual analysis.",
        "parameters": {
            "type": "object",
            "properties": {
                "mode": {
                    "type": "string",
                    "enum": ["full", "region", "window"],
                    "description": "Capture mode: full screen, user-selected region, or active window.",
                },
                "window_title": {
                    "type": "string",
                    "description": "Window title to capture (for mode=window). Omit for active window.",
                },
            },
            "required": ["mode"],
        },
    },
}


def handle_capture(args: dict[str, Any]) -> str:
    """Handler para tool call capture_screen (chamado pelo agente)."""
    mode = args.get("mode", "full")
    window_title = args.get("window_title")
    # Foco + opacidade ANTES de capturar: é o que faz a visão/OCR lerem a
    # janela certa em vez do terminal que está por trás.
    _want_focus = args.get("focus_window", True)
    _want_opaque = args.get("opaque", True)
    prep = (_prepare_window(window_title, opaque=_want_opaque)
            if (mode == "window" and window_title and _want_focus) else None)

    if mode == "full":
        result = capture_full()
    elif mode == "region":
        result = capture_region()
    elif mode == "window":
        result = capture_window(window_title)
    else:
        return f"ERROR: modo desconhecido '{mode}'. Use: full, region, window"

    if result["ok"]:
        return f"Screenshot capturada: {result['path']} ({result.get('size_kb', '?')}KB)"
    return f"ERROR: {result['error']}"


def observe_screen(args: dict[str, Any]) -> str:
    """Captura screenshot E envia ao modelo para análise.

    Pipeline completo: grim → resize → base64 → llama.cpp vision → descrição.
    Retorna a descrição do que o modelo vê na tela.
    """
    import base64
    import io
    import json

    # 1. Capture screenshot
    mode = args.get("mode", "full")
    window_title = args.get("window_title")
    # Foco + opacidade ANTES de capturar: é o que faz a visão/OCR lerem a
    # janela certa em vez do terminal que está por trás.
    _want_focus = args.get("focus_window", True)
    _want_opaque = args.get("opaque", True)
    prep = (_prepare_window(window_title, opaque=_want_opaque)
            if (mode == "window" and window_title and _want_focus) else None)
    question = args.get("question", "Describe what you see. List applications, errors, and UI state.")

    if mode == "full":
        result = capture_full()
    elif mode == "window":
        result = capture_window(window_title)
    else:
        result = capture_full()

    if not result.get("ok"):
        return f"ERROR: screenshot failed: {result.get('error', 'unknown')}"

    image_path = result["path"]

    # 2. Resize + encode
    try:
        from PIL import Image
        img = Image.open(image_path)
        img.thumbnail((1024, 1024), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        img_b64 = base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        # Fallback: send raw file as base64
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

    # 3. Send to model via caminho canônico (LLMClient: breaker +
    # telemetria + fallback). Antes: requests.post manual que pulava tudo.
    from jarvis.providers.llm import LLMClient, LLMError

    messages = [
        {
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                {"type": "text", "text": question},
            ],
        }
    ]

    try:
        with LLMClient() as client:
            resp = client.chat_full(messages, temperature=0.0, max_tokens=2000)
        content = resp.content
        reasoning = resp.reasoning

        # Build response
        parts = []
        if content:
            parts.append(content)
        elif reasoning:
            # If only reasoning (thinking), use it as fallback
            parts.append(f"[model thinking only]\n{reasoning[:1000]}")
        else:
            parts.append("Model returned empty response")

        parts.append(f"\n[screenshot: {image_path} ({result.get('size_kb', '?')}KB)]")
        return "\n".join(parts)

    except LLMError as e:
        return f"ERROR: vision analysis failed: {e}. Screenshot saved at {image_path}"


# ---------------------------------------------------------------------------
# Fallback em cascata — observe NUNCA falha por falta de modelo vision
# (dono 24/09): mmproj local → Gemini free → NVIDIA NIM vision → OCR.
# Cada nível registra `via:` no output (honestidade > adivinhação).
# ---------------------------------------------------------------------------

def _vision_local(image_path: str, question: str) -> dict[str, Any]:
    """Nível 1: modelo local com mmproj (via LLMClient canônico)."""
    import base64
    import io

    try:
        from PIL import Image
        img = Image.open(image_path)
        img.thumbnail((1024, 1024), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        img_b64 = base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

    from jarvis.providers.llm import LLMClient, LLMError

    messages = [{
        "role": "user",
        "content": [
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
            {"type": "text", "text": question},
        ],
    }]
    try:
        with LLMClient() as client:
            resp = client.chat_full(messages, temperature=0.0, max_tokens=2000)
        content = (resp.content or "").strip()
        if not content and resp.reasoning:
            content = f"[model thinking only]\n{resp.reasoning[:1000]}"
        if not content:
            return {"ok": False, "error": "modelo local retornou vazio (sem mmproj?)"}
        return {"ok": True, "via": "local", "text": content}
    except LLMError as e:
        return {"ok": False, "error": f"vision local falhou: {e}"}
    except Exception as e:
        return {"ok": False, "error": f"vision local erro: {e}"}


def _vision_gemini(image_path: str, question: str,
                   timeout: float = 60.0) -> dict[str, Any]:
    """Nível 2: Gemini free (AI Studio, vision nativa, sem cartão)."""
    import base64
    import json
    import urllib.request

    # A chave vive em /etc/litellm.env; keys.get() le a env E cai pro arquivo.
    # Antes era so os.environ, entao a chave nunca chegava ao processo e este
    # nivel nao era nunca tentado (o observe caia direto no OCR).
    try:
        from jarvis.core import keys as _keys
        key = _keys.get("gemini")
    except Exception:
        key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        return {"ok": False, "error": "GEMINI_API_KEY ausente"}

    # Encode da imagem. Sem PIL, manda o arquivo CRU (a Gemini aceita PNG) em
    # vez de abortar: PIL ausente nao e motivo p/ pular uma vision free.
    mime = "image/jpeg"
    try:
        from PIL import Image
        import io
        img = Image.open(image_path).convert("RGB")
        img.thumbnail((1024, 1024), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        img_b64 = base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        mime = "image/png"
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

    # sem modelo hardcoded: o catálogo decide (free rotaciona toda semana)
    models = _discover_vision_models("gemini")[:3]
    if not models:
        return {"ok": False, "error": "nenhum modelo de visão no catálogo"}
    last = "?"
    for model in models:
        payload = json.dumps({
            "contents": [{"parts": [
                {"inline_data": {"mime_type": mime, "data": img_b64}},
                {"text": question},
            ]}],
            "generationConfig": {"temperature": 0.0, "maxOutputTokens": 2000,
                              # sem thoughts: 2.5-flash gasta o orçamento neles e
                              # devolve finishReason=MAX_TOKENS sem nenhum texto.
                              "thinkingConfig": {"thinkingBudget": 0}},
        }).encode()
        try:
            data = _http_json(
                "https://generativelanguage.googleapis.com/v1beta/models/"
                f"{model}:generateContent?key={key}",
                payload, {}, timeout)
            parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
            text = "".join(p.get("text", "") for p in parts).strip()
            if text:
                return {"ok": True, "via": f"gemini:{model}", "text": text}
            # MAX_TOKENS sem texto = orçamento gasto em thoughts, não é auth
            last = "sem texto (provável thoughts)"
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} {e.read().decode()[:80]}"
            continue
        except Exception as e:
            last = str(e)[:100]
            continue
    return {"ok": False, "error": f"gemini falhou: {last}"}


def _vision_groq(image_path: str, question: str,
                 timeout: float = 60.0) -> dict[str, Any]:
    """Nível 2b: Groq vision (grátis, llama-3.2-11b-vision-preview).

    DIAGNÓSTICO 2026-10-02: a chave em GEMINI_API_KEY NÃO é do Google — não
    começa com "AIza" e a API respondeu 401. As chaves que funcionam de fato
    no /etc/litellm.env são GROQ_API_KEY (gsk_...) e OPENROUTER_API_KEY
    (sk-or...). Groq tem visão gratuita, então entra na cascata antes do OCR.
    """
    import base64
    import json
    import urllib.request

    try:
        from jarvis.core import keys as _keys
        key = _keys.get("groq")
    except Exception:
        key = os.environ.get("GROQ_API_KEY", "")
    if not key:
        return {"ok": False, "error": "GROQ_API_KEY ausente"}

    mime = "image/jpeg"
    try:
        from PIL import Image
        import io
        img = Image.open(image_path).convert("RGB")
        img.thumbnail((1024, 1024), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        img_b64 = base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        mime = "image/png"
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

    payload = json.dumps({
        "model": "llama-3.2-11b-vision-preview",
        "messages": [{"role": "user", "content": [
            {"type": "image_url",
             "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
            {"type": "text", "text": question},
        ]}],
        "max_tokens": 1000,
        "temperature": 0.0,
    }).encode()
    try:
        data = _http_json(
            "https://api.groq.com/openai/v1/chat/completions", payload,
            {"Authorization": f"Bearer {key}"}, timeout)
        text = (data.get("choices", [{}])[0].get("message", {})
                .get("content", "") or "").strip()
        if not text:
            return {"ok": False, "error": "groq retornou vazio"}
        return {"ok": True, "via": "groq-vision", "text": text}
    except Exception as e:
        return {"ok": False, "error": f"groq falhou: {str(e)[:150]}"}


def _vision_openrouter(image_path: str, question: str,
                       timeout: float = 90.0) -> dict[str, Any]:
    """Nível 2c: OpenRouter com modelo de visão `:free` (sem cartão).

    DIAGNÓSTICO 2026-10-02: no /etc/litellm.env a chave em GEMINI_API_KEY NÃO
    é do Google (não começa com "AIza" → 401) e a de GROQ_API_KEY devolve 403
    até em /models (expirada/revogada). A que FUNCIONA é OPENROUTER_API_KEY, e
    ela tem visão gratuita: `google/gemma-4-26b-a4b-it:free` e
    `google/gemma-4-31b-it:free` (descobertos via /api/v1/models). Este é o
    nível que devolve visão de verdade neste host.
    """
    import base64
    import json
    import urllib.request

    try:
        from jarvis.core import keys as _keys
        key = _keys.get("openrouter")
    except Exception:
        key = os.environ.get("OPENROUTER_API_KEY", "")
    if not key:
        return {"ok": False, "error": "OPENROUTER_API_KEY ausente"}

    # catálogo :free com input_modalities contendo "image" (dinâmico)
    errs: list[str] = []
    for model in _discover_vision_models("openrouter")[:4]:
        mime = "image/jpeg"
        try:
            from PIL import Image
            import io
            img = Image.open(image_path).convert("RGB")
            img.thumbnail((1024, 1024), Image.LANCZOS)
            buf = io.BytesIO()
            img.save(buf, format="JPEG", quality=80)
            img_b64 = base64.b64encode(buf.getvalue()).decode()
        except ImportError:
            mime = "image/png"
            with open(image_path, "rb") as f:
                img_b64 = base64.b64encode(f.read()).decode()

        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
                {"type": "text", "text": question},
            ]}],
            "max_tokens": 800,
            "temperature": 0.0,
        }).encode()
        try:
            data = _http_json(
                "https://openrouter.ai/api/v1/chat/completions", payload,
                {"Authorization": f"Bearer {key}",
                 "HTTP-Referer": "https://opencode.ai",
                 "X-Title": "JARVIS"}, timeout)
            text = (data.get("choices", [{}])[0].get("message", {})
                    .get("content", "") or "").strip()
            if text:
                return {"ok": True, "via": f"openrouter:{model}", "text": text}
        except urllib.error.HTTPError as e:
            errs.append(f"{model}: HTTP {e.code} {e.read().decode()[:60]}")
        except Exception as e:
            errs.append(f"{model}: {str(e)[:60]}")
        continue
    return {"ok": False, "error": "openrouter: " +
            ("; ".join(errs[:3]) or "nenhum modelo :free com visão no catálogo")}


def _vision_nvidia(image_path: str, question: str,
                   timeout: float = 75.0) -> dict[str, Any]:
    """Nível 2d: NVIDIA NIM vision — GRÁTIS, com crédito, e FUNCIONANDO.

    DIAGNÓSTICO 2026-10-02 (build.nvidia.com): `meta/llama-3.2-11b-vision-
    instruct` respondeu de primeira, sem GPU local. Foi o único provider de
    visão que autenticou neste host:
        gemini    401 — a chave em GEMINI_API_KEY não é do Google (não é AIza…)
        groq      403 — Cloudflare code 1010 bloqueia este IP/região
        openrouter 401 — "User not found", chave sem conta
    NIM é creditado (tem cota gratuita generosa) e o endpoint é
    integrate.api.nvidia.com/v1/chat/completions.
    """
    import base64
    import json
    import urllib.request

    try:
        from jarvis.core import keys as _keys
        key = _keys.get("nvidia")
    except Exception:
        key = os.environ.get("NVIDIA_API_KEY", "")
    if not key:
        return {"ok": False, "error": "NVIDIA_API_KEY ausente"}

    mime = "image/jpeg"
    try:
        from PIL import Image
        import io
        img = Image.open(image_path).convert("RGB")
        img.thumbnail((1024, 1024), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        img_b64 = base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        mime = "image/png"
        with open(image_path, "rb") as f:
            img_b64 = base64.b64encode(f.read()).decode()

    models = _discover_vision_models("nvidia")[:3]
    if not models:
        return {"ok": False, "error": "nenhum VLM no catálogo NIM"}
    last = "?"
    for model in models:
        payload = json.dumps({
            "model": model,
            "messages": [{"role": "user", "content": [
                {"type": "image_url",
                 "image_url": {"url": f"data:{mime};base64,{img_b64}"}},
                {"type": "text", "text": question},
            ]}],
            "max_tokens": 800,
            "temperature": 0.0,
        }).encode()
        try:
            data = _http_json(
                "https://integrate.api.nvidia.com/v1/chat/completions", payload,
                {"Authorization": f"Bearer {key}",
                 "Accept": "application/json"}, timeout)
            text = (data.get("choices", [{}])[0].get("message", {})
                    .get("content", "") or "").strip()
            if text:
                return {"ok": True, "via": f"nvidia:{model}", "text": text}
            last = "retornou vazio"
        except urllib.error.HTTPError as e:
            last = f"HTTP {e.code} {e.read().decode()[:80]}"
            continue
        except Exception as e:
            last = str(e)[:100]
            continue
    return {"ok": False, "error": f"nvidia falhou: {last}"}



# --------------------------------------------------------------------------
# DESCOBERTA DINÂMICA DE MODELO (2026-10-02)
#
# Modelos "free"/baratos mudam toda semana — e foi exatamente o que aconteceu:
# a Groq descontinuou TODOS os VLM em 2026-10-01 (llama-3.2-11b-vision,
# llama-4-maverick em 09/03, llama-4-scout em 17/07); a OpenRouter tirou
# llama-3.3-70b:free do :free; o gemma-4:free cai em 429 sem parar. Hardcodar
# slug garante 404/429 em semanas. Então: lê o catálogo do provider, filtra o
# que aceita imagem, ordena por preferência e guarda 1h de cache.
# --------------------------------------------------------------------------
_MODEL_TTL = 3600.0
_MODEL_CACHE: dict[str, tuple[list[str], float]] = {}

# termos que indicam entrada de imagem
_NEG = ("embed", "tts", "safety", "moderation", "audio", "rerank")


def _catalog(url: str, headers: dict[str, str],
             timeout: float = 40.0) -> list[dict[str, Any]]:
    """GET JSON com UA. Catálogo vazio em qualquer erro (nunca levanta)."""
    try:
        return _http_get(url, headers, timeout)
    except Exception:
        return []


def _discover_vision_models(provider: str) -> list[str]:
    """Modelos com visão do `provider`, ordenados por preferência.

    Cache de 1h: é o suficiente para o catálogo free rotacionar sem refazer
    request a cada `observe_screen`, e curto o bastante para pegar a troca.
    """
    hit = _MODEL_CACHE.get(provider)
    if hit and time.time() - hit[1] < _MODEL_TTL:
        return hit[0]

    found: list[str] = []
    try:
        if provider == "gemini":
            key = _secret("gemini")
            data = _catalog(
                "https://generativelanguage.googleapis.com/v1beta/"
                f"models?key={key}&pageSize=200", {})
            names = [m.get("name", "").replace("models/", "")
                     for m in data.get("models", [])
                     if "generateContent" in
                     (m.get("supportedGenerationMethods") or [])]
            # "-image"/"image-preview" geram imagem (input texto), não
            # entendem imagem — fora, senão o catálogo as põe na frente.
            vis = [n for n in names
                   if not any(t in n.lower() for t in _NEG)
                   and not n.lower().endswith("-image")
                   and "-image-" not in n.lower()]
            # flash primeiro (rápido/grátis), depois lite, depois o resto
            found = sorted(vis, key=lambda n: (
                0 if "-flash" in n and "lite" not in n else
                1 if "-flash-lite" in n else 2, n))

        elif provider == "nvidia":
            key = _secret("nvidia")
            data = _catalog("https://integrate.api.nvidia.com/v1/models",
                            {"Authorization": f"Bearer {key}"})
            ids = [m.get("id", "") for m in
                   (data.get("data") if isinstance(data, dict) else data)]
            vis = [i for i in ids
                   if any(t in i.lower() for t in ("vision", "-vl", "vlm"))
                   and "embed" not in i.lower()]
            # 12/10: 90b ANTES de 11b. O 11b alucinou janelas de login ao
            # descrever UI de jogo (medido no baseline do reskin); o 90b é
            # o VLM forte do catálogo NIM e deve ser tentado primeiro.
            found = sorted(vis, key=lambda i: (
                0 if "90b" in i.lower() else
                1 if "11b" in i.lower() else 2, i))

        elif provider == "openrouter":
            key = _secret("openrouter")
            data = _catalog("https://openrouter.ai/api/v1/models",
                            {"Authorization": f"Bearer {key}"})
            rows = data.get("data", []) if isinstance(data, dict) else []
            for m in rows:
                arch = m.get("architecture") or {}
                price = (m.get("pricing") or {}).get("prompt")
                if "image" not in (arch.get("input_modalities") or []):
                    continue
                if price != "0":        # só :free — sem crédito não roda
                    continue
                if any(t in m["id"].lower() for t in _NEG):
                    continue
                found.append(m["id"])
    except Exception:
        found = []

    if found:
        _MODEL_CACHE[provider] = (found, time.time())
    elif hit:                        # catálogo falhou: usa o cache velho
        return hit[0]
    return found


def _takes_timeout(fn) -> bool:
    """A funcao aceita `timeout=`? (viaGameinput usa click sem timeout)."""
    import inspect
    try:
        return "timeout" in inspect.signature(fn).parameters
    except (TypeError, ValueError):
        return False


def _secret(name: str) -> str:
    try:
        from jarvis.core import keys as _keys
        return _keys.get(name)
    except Exception:
        return os.environ.get(name.upper(), "")

def _ocr_text(image_path: str, lang: str = "por+eng",
               timeout: float = 60.0) -> dict[str, Any]:
    """Nível 3 (final): Tesseract OCR — local, grátis, sempre disponível.

    DIAGNÓSTICO 2026-10-02: o OCR antigo usava só `--psm 6` (bloco uniforme de
    texto), que é ruim para interface de JOGO — HUD espalhado, números
    pequenos, spread de inventário. Em tela escura de Tibia/OTClient ele
    devolvia lixo ou vazio. Aqui:
      - roda 3 modos de segmentação e fica com o que tem mais caracteres
        (psm 6 = bloco, 11 = sparse/espalhado, 3 = auto);
      - se PIL existir, gera uma cópia com AUTO-CONTRASTE/THRESHOLD, porque
        o jogo é escuro e o tesseract precisa de fundo claro;
      - tenta `por` e depois `eng` (o nome dos itens vem em inglês do server).
    """
    if not _has_binary("tesseract"):
        return {"ok": False, "error": "tesseract ausente (nix: tesseract)"}

    # Pré-processa: escurece/ruído de jogo vira binário de alto contraste.
    path = image_path
    try:
        from PIL import Image, ImageOps
        img = Image.open(image_path).convert("L")
        img = ImageOps.autocontrast(img)
        path = image_path.rsplit(".", 1)[0] + "-ocr.png"
        img.point(lambda p: 255 if p > 140 else 0).save(path)
    except ImportError:
        path = image_path  # sem PIL: usa o original

    best = ""
    for psm in ("11", "6", "3"):        # sparse (jogo) > bloco > auto
        for lg in (lang, "eng"):
            try:
                r = subprocess.run(
                    ["tesseract", path, "stdout", "-l", lg, "--psm", psm],
                    capture_output=True, text=True,
                    timeout=max(5, timeout / 3))
            except (subprocess.TimeoutExpired, OSError,
                    subprocess.SubprocessError):
                continue
            t = (r.stdout or "").strip()
            if len(t) > len(best):
                best = t
    if not best:
        return {"ok": False, "error": "OCR não encontrou texto"}
    return {"ok": True, "via": "ocr-multipsm", "text": best}


# Provedores que responderam 401/403 ficam fora das próximas tentativas.
# DIAGNÓSTICO 2026-10-02: as chaves de vision do /etc/litellm.env estão
# expiradas/revogadas (Gemini 401, Groq 403, OpenRouter 401). Sem isto, cada
# observe gastava 3 round-trips em rede morrendo antes de chegar no OCR — e o
# MCP estourava o timeout. Agora a falha é lembrada e o OCR responde na hora.
_DEAD_PROVIDERS: dict[str, tuple[str, float]] = {}
_DEAD_TTL = 300.0   # 5 min: provider morto sai da cascata sem custar chamada,
                    # mas uma chave renovada volta sozinha (sem reiniciar)


def _mark_dead(via: str, err: str) -> None:
    if any(m in err for m in ("401", "403", "404", "402", "429",
                              "User not found", "Internal Server",
                              "decommissioned")):
        _DEAD_PROVIDERS[via] = (err[:120], time.time())


def _is_dead(via: str) -> bool:
    hit = _DEAD_PROVIDERS.get(via)
    if not hit:
        return False
    err, when = hit
    if time.time() - when > _DEAD_TTL:      # TTL expirou: tenta de novo
        _DEAD_PROVIDERS.pop(via, None)
        return False
    return True


def observe_with_fallback(args: dict[str, Any]) -> str:
    """Observe que NUNCA falha por falta de vision: local → gemini → OCR.

    Retorna descrição + tag `via:` (local/gemini/ocr). Só falha de verdade
    sem display (nada p/ capturar) — aí diz isso honestamente.
    """
    mode = args.get("mode", "full")
    window_title = args.get("window_title")
    # Foco + opacidade ANTES de capturar: é o que faz a visão/OCR lerem a
    # janela certa em vez do terminal que está por trás.
    _want_focus = args.get("focus_window", True)
    _want_opaque = args.get("opaque", True)
    prep = (_prepare_window(window_title, opaque=_want_opaque)
            if (mode == "window" and window_title and _want_focus) else None)
    question = args.get("question",
                        "Describe what you see. List applications, errors, and UI state.")

    if mode == "window":
        shot = capture_window(window_title)
    elif mode == "region":
        shot = capture_region()
    else:
        shot = capture_full()
    if not shot.get("ok"):
        return f"SEM DISPLAY: {shot.get('error', 'captura impossível')}"

    image_path = shot["path"]
    attempts = []

    # Nível 0 (barato, sem rede): vision local. Só tenta 1x se já sabermos
    # que o llama-router está fora — 8080 devolve 500 e custa segundos.
    # ordem: local (grátis) → nvidia (funciona) → gemini → groq → openrouter
    # Groq saiu da cascata: EM 2026-10-01 a Groq descontinuou TODOS os VLM
    # (llama-3.2-11b-vision, llama-4-maverick 09/03, llama-4-scout 17/07) e
    # passou a servir só texto. Chamar era gastar request em 404 garantido.
    # Ordem: local (grátis) → gemini (grátis, funciona) → nvidia (crédito)
    # → openrouter (crédito) → OCR.
    # TETO GERAL: com 4 níveis e um deles lento, a soma passou de 120s e o MCP
    # (timeout 180s) ficava no limite. 45s é folgado para o caso comum
    # (medido: nvidia 1,8s | gemini 12,5s) e curto o bastante para nunca
    # estourar. Ao estourar, devolve o que já conseguiu + o que sobrou.
    budget = float(args.get("budget", 45.0))
    deadline = time.time() + budget

    levels = [(_vision_local, "local"),
              (_vision_gemini, "gemini"),
              (_vision_nvidia, "nvidia-nim-vision"),
              (_vision_openrouter, "openrouter")]

    for fn, via in levels:
        # orçamento por nível: o llama local SEMPRE dá 500 neste host (medido) e
        # consumia 25,3s do orçamento antes de o Gemini ser tentado. Corto pra
        # 8s e, se estourar, marco como morto pra não repetir.
        if _is_dead(via):
            attempts.append(f"{via}: {_DEAD_PROVIDERS[via][0]} (marcado)")
            continue
        restante = deadline - time.time()
        if restante <= 1.0:
            attempts.append(f"{via}: sem tempo (orcamento {budget:.0f}s)")
            continue
        # TETO POR CHAMADA: checar o deadline antes não adianta — uma chamada
        # longa estoura sozinha (medido: 90,2s porque o nível local consumia
        # 25s e o gemini ainda levava 60s de timeout). Cada nível agora recebe
        # timeout = min(cap, restante), então a soma respeita o orçamento.
        cap = min(20.0, restante)
        try:
            r = (fn(image_path, question, timeout=cap)
                 if _takes_timeout(fn)
                 else fn(image_path, question))
        except Exception as e:
            r = {"ok": False, "error": str(e)[:150]}
        if r.get("ok"):
            return (f"{r['text']}\n\n[via: {r['via']} | "
                    f"screenshot: {image_path} ({shot.get('size_kb', '?')}KB)"
                    + (f" | janela focada+opaca: {prep.get('address')}"
                       if prep else "") + "]")
        err = r.get("error", "?")
        # 500 do llama local é "modelo não tem visão" — não é chave morta,
        # mas também não adianta repetir toda chamada.
        _mark_dead(via, err)
        attempts.append(err)

    restante = deadline - time.time()
    ocr = (_ocr_text(image_path, timeout=max(8.0, min(20.0, restante)))
           if restante > 3 else {"ok": False, "error": "orcamento esgotado"})
    if ocr.get("ok"):
        return (f"[visão indisponível ({' | '.join(attempts)}); fallback OCR]\n"
                f"{ocr['text']}\n\n[via: ocr | screenshot: {image_path}]")

    return (f"OBSERVE FALHOU em todos os níveis — local: {attempts[0] if attempts else '?'}; "
            f"gemini: {attempts[1] if len(attempts) > 1 else '?'}; ocr: {ocr.get('error')}. "
            f"Screenshot salva em {image_path}.")
