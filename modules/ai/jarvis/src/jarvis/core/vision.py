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
from pathlib import Path
from typing import Any

SCREENSHOT_DIR = Path(os.environ.get("JARVIS_SCREENSHOT_DIR", "/tmp"))
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
    """Nível 2: Gemini free (AI Studio, 1M ctx, vision nativo, sem cartão)."""
    import base64
    import io
    import urllib.request

    key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not key:
        return {"ok": False, "error": "GEMINI_API_KEY ausente"}
    try:
        from PIL import Image
        img = Image.open(image_path).convert("RGB")
        img.thumbnail((1024, 1024), Image.LANCZOS)
        buf = io.BytesIO()
        img.save(buf, format="JPEG", quality=80)
        img_b64 = base64.b64encode(buf.getvalue()).decode()
    except ImportError:
        return {"ok": False, "error": "PIL ausente p/ redimensionar"}
    payload = json.dumps({
        "contents": [{"parts": [
            {"inline_data": {"mime_type": "image/jpeg", "data": img_b64}},
            {"text": question},
        ]}],
        "generationConfig": {"temperature": 0.0, "maxOutputTokens": 2000},
    }).encode()
    try:
        req = urllib.request.Request(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-2.5-flash:generateContent?key={key}",
            data=payload, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            data = json.loads(r.read().decode())
        parts = data.get("candidates", [{}])[0].get("content", {}).get("parts", [])
        text = "".join(p.get("text", "") for p in parts).strip()
        if not text:
            return {"ok": False, "error": "gemini retornou vazio"}
        return {"ok": True, "via": "gemini", "text": text}
    except Exception as e:
        return {"ok": False, "error": f"gemini falhou: {str(e)[:150]}"}


def _ocr_text(image_path: str, lang: str = "por+eng") -> dict[str, Any]:
    """Nível 3 (final): Tesseract OCR — sempre funciona se há imagem."""
    if not _has_binary("tesseract"):
        return {"ok": False, "error": "tesseract ausente (nix: tesseract)"}
    try:
        result = subprocess.run(
            ["tesseract", image_path, "stdout", "-l", lang, "--psm", "6"],
            capture_output=True, text=True, timeout=60,
        )
        text = (result.stdout or "").strip()
        if not text:
            return {"ok": False, "error": "OCR não encontrou texto"}
        return {"ok": True, "via": "ocr", "text": text}
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "OCR timeout"}
    except (OSError, subprocess.SubprocessError) as exc:
        return {"ok": False, "error": f"OCR erro: {exc}"}


def observe_with_fallback(args: dict[str, Any]) -> str:
    """Observe que NUNCA falha por falta de vision: local → gemini → OCR.

    Retorna descrição + tag `via:` (local/gemini/ocr). Só falha de verdade
    sem display (nada p/ capturar) — aí diz isso honestamente.
    """
    mode = args.get("mode", "full")
    window_title = args.get("window_title")
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

    for fn in (_vision_local, _vision_gemini):
        try:
            r = fn(image_path, question)
        except Exception as e:
            r = {"ok": False, "error": str(e)[:150]}
        if r.get("ok"):
            return (f"{r['text']}\n\n[via: {r['via']} | "
                    f"screenshot: {image_path} ({shot.get('size_kb', '?')}KB)]")
        attempts.append(r.get("error", "?"))

    ocr = _ocr_text(image_path)
    if ocr.get("ok"):
        return (f"[visão indisponível ({' | '.join(attempts)}); fallback OCR]\n"
                f"{ocr['text']}\n\n[via: ocr | screenshot: {image_path}]")

    return (f"OBSERVE FALHOU em todos os níveis — local: {attempts[0] if attempts else '?'}; "
            f"gemini: {attempts[1] if len(attempts) > 1 else '?'}; ocr: {ocr.get('error')}. "
            f"Screenshot salva em {image_path}.")
