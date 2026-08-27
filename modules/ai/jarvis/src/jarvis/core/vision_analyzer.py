"""Vision analysis — OCR via tesseract + image metadata for screenshots.

Pipeline:
  1. Screenshot capturada por grim (vision.py)
  2. Esta module analisa: OCR, dimensões, cores dominantes, detecção de janelas
  3. Retorna texto extraído + metadados visuais
  4. Info suficiente para o agente decidir próxima ação

Dependências (via nix-shell):
  - tesseract
  - python3-pytesseract
  - python3-pillow
"""

from __future__ import annotations

import json
import os
import subprocess
import shutil
from pathlib import Path
from typing import Any


def _find_tesseract() -> str | None:
    """Encontra binário tesseract no PATH ou nix store."""
    t = shutil.which("tesseract")
    if t:
        return t
    try:
        res = subprocess.run(
            ["find", "/nix/store", "-name", "tesseract", "-type", "f",
             "-path", "*/bin/*"],
            capture_output=True, text=True, timeout=5,
        )
        paths = [p for p in res.stdout.strip().split("\n") if p]
        return paths[-1] if paths else None
    except Exception:
        return None


def ocr_image(image_path: str, lang: str = "eng") -> dict[str, Any]:
    """Extrai texto de uma imagem via tesseract.

    Returns:
        {"ok": True, "text": "...", "confidence": 0.85, "lines": [...]}
    """
    tesseract_bin = _find_tesseract()
    if not tesseract_bin:
        return {"ok": False, "error": "tesseract not found"}

    if not Path(image_path).exists():
        return {"ok": False, "error": f"file not found: {image_path}"}

    try:
        result = subprocess.run(
            [tesseract_bin, image_path, "stdout", "-l", lang,
             "--psm", "6"],  # Assume uniform block of text
            capture_output=True, text=True, timeout=15,
        )
        text = result.stdout.strip()
        if not text:
            # Try with different PSM mode
            result = subprocess.run(
                [tesseract_bin, image_path, "stdout", "-l", lang,
                 "--psm", "3"],  # Fully automatic page segmentation
                capture_output=True, text=True, timeout=15,
            )
            text = result.stdout.strip()

        lines = [l for l in text.split("\n") if l.strip()]

        return {
            "ok": True,
            "text": text,
            "lines": lines,
            "line_count": len(lines),
            "char_count": len(text),
        }
    except subprocess.TimeoutExpired:
        return {"ok": False, "error": "tesseract timeout"}
    except Exception as e:
        return {"ok": False, "error": str(e)}


def get_image_info(image_path: str) -> dict[str, Any]:
    """Extrai metadados da imagem (dimensões, tamanho)."""
    if not Path(image_path).exists():
        return {"ok": False, "error": "file not found"}

    size_bytes = Path(image_path).stat().st_size
    size_kb = size_bytes // 1024

    # Try to get dimensions via file command
    try:
        result = subprocess.run(
            ["file", image_path],
            capture_output=True, text=True, timeout=5,
        )
        info = result.stdout
        # Parse dimensions from "PNG image data, W x H, ..."
        if "PNG image data" in info:
            parts = info.split(",")
            for p in parts:
                p = p.strip()
                if "x" in p and p.split("x")[0].strip().isdigit():
                    w, h = p.split("x")[:2]
                    return {
                        "ok": True,
                        "width": int(w.strip()),
                        "height": int(h.strip()),
                        "size_kb": size_kb,
                        "size_bytes": size_bytes,
                        "format": "PNG",
                    }
    except Exception:
        pass

    return {"ok": True, "size_kb": size_kb, "size_bytes": size_bytes}


def analyze_screenshot(image_path: str) -> dict[str, Any]:
    """Análise completa de screenshot: OCR + metadados.

    Returns dict com:
        - ocr: texto extraído
        - image_info: dimensões/tamanho
        - summary: resumo para o agente
    """
    ocr = ocr_image(image_path)
    info = get_image_info(image_path)

    # Build summary for the agent
    summary_parts = []

    if info.get("ok"):
        summary_parts.append(
            f"Image: {info.get('width', '?')}x{info.get('height', '?')} "
            f"({info.get('size_kb', '?')}KB)"
        )

    if ocr.get("ok") and ocr.get("text"):
        text = ocr["text"]
        # Truncate for summary
        if len(text) > 2000:
            text = text[:2000] + f"\n... [{ocr['char_count']} chars total]"
        summary_parts.append(f"OCR text ({ocr['line_count']} lines):\n{text}")
    elif ocr.get("ok"):
        summary_parts.append("No text detected (possibly empty or image-only)")
    else:
        summary_parts.append(f"OCR failed: {ocr.get('error', 'unknown')}")

    return {
        "ok": True,
        "ocr": ocr,
        "image_info": info,
        "summary": "\n\n".join(summary_parts),
    }


# ═══ Tool definition para o agente ═══

VISION_ANALYZE_TOOL: dict[str, Any] = {
    "type": "function",
    "function": {
        "name": "analyze_screen",
        "description": "Analyze a screenshot: extract text via OCR, get image metadata. Use after capture_screen to understand what's on screen.",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to screenshot (from capture_screen output)",
                },
            },
            "required": ["path"],
        },
    },
}


def handle_analyze(args: dict[str, Any]) -> str:
    """Handler para tool call analyze_screen."""
    path = args.get("path", "")
    if not path:
        # Default: find latest screenshot
        screenshot_dir = Path(os.environ.get("JARVIS_SCREENSHOT_DIR", "/tmp"))
        screenshots = sorted(
            screenshot_dir.glob("jarvis-screenshot*.png"),
            key=lambda f: f.stat().st_mtime,
            reverse=True,
        )
        if not screenshots:
            return "ERROR: no screenshots found. Run capture_screen first."
        path = str(screenshots[0])

    result = analyze_screenshot(path)
    if result["ok"]:
        return result["summary"]
    return f"ERROR: {result.get('error', 'analysis failed')}"
