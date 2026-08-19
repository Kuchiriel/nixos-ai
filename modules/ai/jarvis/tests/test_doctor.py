"""Testes do `jarvis doctor` (core/doctor.py) com mocks HTTP."""

import requests

from jarvis.core.config import Config
from jarvis.core.doctor import (
    ComponentHealth,
    check_disk,
    check_embeddings,
    check_llm,
    check_qdrant,
    check_ui,
    doctor_report,
    run_doctor,
)


class FakeResp:
    def __init__(self, payload=None, status_code=200):
        self._payload = payload if payload is not None else {"result": {"collections": []}}
        self.status_code = status_code

    def json(self):
        return self._payload


def test_check_llm_ok(monkeypatch) -> None:
    cfg = Config()

    def fake_get(url, timeout=3):
        if url.endswith("/health"):
            return FakeResp()
        # /models
        return FakeResp({"data": [{"id": "qwen2.5-coder-7b"}]})

    monkeypatch.setattr("jarvis.core.doctor.requests.get", fake_get)
    h = check_llm(cfg)
    assert h.status == "ok"
    assert h.data.get("model") == "qwen2.5-coder-7b"


def test_check_llm_down(monkeypatch) -> None:
    cfg = Config()

    def fake_get(url, timeout=3):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr("jarvis.core.doctor.requests.get", fake_get)
    h = check_llm(cfg)
    assert h.status == "down"


def test_check_embeddings_ok(monkeypatch) -> None:
    cfg = Config()

    def fake_get(url, timeout=3):
        return FakeResp()

    monkeypatch.setattr("jarvis.core.doctor.requests.get", fake_get)
    h = check_embeddings(cfg)
    assert h.status == "ok"


def test_check_qdrant_missing_collection(monkeypatch) -> None:
    cfg = Config()

    def fake_get(url, timeout=3):
        return FakeResp({"result": {"collections": [{"name": "code_index"}]}})

    monkeypatch.setattr("jarvis.core.doctor.requests.get", fake_get)
    h = check_qdrant(cfg)
    assert h.status == "degraded"
    assert "memories" in h.detail


def test_check_qdrant_down(monkeypatch) -> None:
    cfg = Config()

    def fake_get(url, timeout=3):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr("jarvis.core.doctor.requests.get", fake_get)
    h = check_qdrant(cfg)
    assert h.status == "down"


def test_check_disk_shape() -> None:
    h = check_disk()
    assert h.name == "disk"
    assert h.status in ("ok", "degraded")
    assert "total_gb" in h.data


def test_doctor_report_overall_down(monkeypatch) -> None:
    cfg = Config()

    def fake_get(url, timeout=3):
        raise requests.ConnectionError("refused")

    monkeypatch.setattr("jarvis.core.doctor.requests.get", fake_get)
    report = doctor_report(cfg)
    assert report["overall"] == "down"
    names = [c["name"] for c in report["checks"]]
    assert "llama_cpp" in names and "qdrant" in names and "disk" in names


def test_run_doctor_returns_checks(monkeypatch) -> None:
    cfg = Config()

    def fake_get(url, timeout=3):
        return FakeResp({"data": [{"id": "m"}], "result": {"collections": []}})

    monkeypatch.setattr("jarvis.core.doctor.requests.get", fake_get)
    checks = run_doctor(cfg)
    assert all(isinstance(c, ComponentHealth) for c in checks)
    # 6 originais + 3 novos proativos (network, sockets, btrfs)
    assert len(checks) == 9


def test_check_ui_shape(monkeypatch) -> None:
    """check_ui nunca quebra e sempre retorna ok ou degraded (nunca down)."""
    # sem Hyprland/waybar (ex: ambiente sem sessão gráfica) → degraded
    monkeypatch.setattr("jarvis.core.doctor._proc_running", lambda name: False)
    monkeypatch.setattr("jarvis.core.doctor._user_unit_active", lambda unit: (False, "inativo"))
    h = check_ui()
    assert h.name == "ui"
    assert h.status == "degraded"
    assert "waybar" in h.detail or "hyprland" in h.detail


def test_check_ui_all_ok(monkeypatch) -> None:
    monkeypatch.setattr("jarvis.core.doctor._proc_running", lambda name: True)
    monkeypatch.setattr("jarvis.core.doctor._user_unit_active", lambda unit: (True, "ativo"))
    monkeypatch.setattr("pathlib.Path.exists", lambda self: True)
    # sistema fora de VM → mpvpaper ativo é ok
    monkeypatch.setattr("jarvis.core.doctor.subprocess.run",
                        lambda *a, **k: type("R", (), {"returncode": 1})())
    h = check_ui()
    assert h.status == "ok"
