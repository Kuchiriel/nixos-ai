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

    # 3. Send to model via llama.cpp API
    import os
    import requests

    api_url = os.environ.get("JARVIS_LLM_URL", "http://127.0.0.1:8080")
    payload = {
        "model": "local",
        "messages": [
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{img_b64}"}},
                    {"type": "text", "text": question},
                ],
            }
        ],
        "max_tokens": 2000,
        "temperature": 0.0,
    }

    try:
        r = requests.post(
            f"{api_url}/v1/chat/completions",
            json=payload,
            timeout=180,
        )
        data = r.json()
        msg = data["choices"][0]["message"]
        content = msg.get("content", "")
        reasoning = msg.get("reasoning_content", "")

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

    except requests.Timeout:
        return f"ERROR: vision API timeout (120s). Screenshot saved at {image_path}"
    except Exception as e:
        return f"ERROR: vision analysis failed: {e}. Screenshot saved at {image_path}"
