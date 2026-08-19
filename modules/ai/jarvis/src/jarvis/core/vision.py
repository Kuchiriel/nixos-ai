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
                import json
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
                import json
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
    """Remove screenshots antigos (> max_age_s segundos). Retorna数量 removida."""
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
