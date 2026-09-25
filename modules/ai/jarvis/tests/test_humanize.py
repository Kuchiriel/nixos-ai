"""Computer-use: humanize (Wurm) + observe fallback (vision→gemini→OCR)."""

from __future__ import annotations

import json

from jarvis.core.humanize import HumanHand


def test_bezier_never_straight():
    pts = HumanHand.bezier_path(0, 0, 400, 0, n=20)
    assert len(pts) == 21
    assert pts[0] == (0, 0) and pts[-1] == (400, 0)
    # curva: algum ponto fora da reta y=0
    assert any(y != 0 for _, y in pts)


def test_bezier_varies_per_call():
    a = HumanHand.bezier_path(0, 0, 400, 300)
    b = HumanHand.bezier_path(0, 0, 400, 300)
    assert a != b  # jitter aleatório


def test_dry_run_never_touches_hardware():
    h = HumanHand(dry_run=True)
    assert h.click(100, 200)["dry"] is True
    assert h.type("abc")["dry"] is True
    assert h.key("Return")["dry"] is True
    assert h.actions == 0  # dry não conta fadiga


def test_dry_run_never_sleeps():
    import time
    h = HumanHand(dry_run=True)
    t = time.time()
    h.move(10, 10)
    h.click(10, 10)
    assert time.time() - t < 1.0


def test_handle_dev_tool_human_dry():
    from jarvis.core.devtools import handle_dev_tool
    out = json.loads(handle_dev_tool("human_click", {"x": 5, "y": 5, "dry_run": True}))
    assert out["ok"] is True and out["dry"] is True
    out2 = json.loads(handle_dev_tool("human_type", {"text": "oi"}))
    # sem wtype no sandbox → erro honesto, nunca exception
    assert "ok" in out2
    out3 = json.loads(handle_dev_tool("human_key", {}))
    assert out3["ok"] is False and "args ausentes" in out3["error"]


def test_observe_fallback_no_display(monkeypatch):
    from jarvis.core import vision as V
    monkeypatch.delenv("WAYLAND_DISPLAY", raising=False)
    monkeypatch.delenv("DISPLAY", raising=False)
    out = V.observe_with_fallback({"mode": "full"})
    assert out.startswith("SEM DISPLAY")


def test_ocr_missing_is_honest(monkeypatch):
    from jarvis.core import vision as V
    monkeypatch.setattr(V.shutil, "which", lambda _: None)
    r = V._ocr_text("/tmp/inexistente.png")
    assert r["ok"] is False and "tesseract" in r["error"]


def test_vision_tool_unchanged():
    from jarvis.core.vision import VISION_TOOL
    assert VISION_TOOL["function"]["name"] == "capture_screen"
