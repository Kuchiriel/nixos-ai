"""Testes do `core.heal` — ciclo self-heal com doctor/restart mockados."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from jarvis.core.heal import (
    ALLOWLIST,
    HealAction,
    heal_once,
    heal_report,
    state_dir,
)


def _fake_doctor(checks: list[dict]) -> dict:
    return {"overall": "ok", "checks": checks}


def _down(name: str, detail: str = "down") -> dict:
    return {"name": name, "status": "down", "detail": detail}


def _ok(name: str) -> dict:
    return {"name": name, "status": "ok", "detail": "ok"}


@pytest.fixture
def fake_doctor(monkeypatch):
    calls = {"n": 0}

    def _set(checks):
        calls["n"] += 1
        monkeypatch.setattr(
            "jarvis.core.heal.doctor_report",
            lambda cfg=None: _fake_doctor(checks),
        )
    return _set


def test_allowlist_only_known_services():
    assert ALLOWLIST == ("llama-cpp-server", "llama-cpp-embeddings", "qdrant")


def test_heal_restarts_down_service(monkeypatch, tmp_path, fake_doctor):
    fake_doctor([_down("qdrant")])
    restarted = []

    def fake_restart(service: str, scope: str):
        restarted.append((service, scope))
        return True, "restart OK"

    monkeypatch.setattr("jarvis.core.heal._restart_service", fake_restart)
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))

    report = heal_once()
    assert restarted == [("qdrant", "system")]
    assert report.overall == "healed"
    assert report.actions[0].action == "restart"
    assert report.actions[0].ok

    # audit gravado
    audit = (tmp_path / "heal-audit.jsonl").read_text(encoding="utf-8")
    assert "qdrant" in audit
    assert "restart" in audit


def test_heal_respects_cooldown(monkeypatch, tmp_path, fake_doctor):
    fake_doctor([_down("qdrant")])
    calls = {"n": 0}

    def fake_restart(service: str, scope: str):
        calls["n"] += 1
        return True, "restart OK"

    monkeypatch.setattr("jarvis.core.heal._restart_service", fake_restart)
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))

    heal_once()  # 1º restart — grava timestamp
    report2 = heal_once()  # 2º dentro do cooldown → report_only
    assert calls["n"] == 1
    assert report2.actions[0].action == "report_only"
    assert "cooldown" in report2.actions[0].skipped_reason


def test_heal_unknown_component_reports_only(monkeypatch, tmp_path, fake_doctor):
    fake_doctor([_down("misterio")])
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    report = heal_once()
    assert report.actions[0].action == "report_only"
    assert "sem serviço mapeado" in report.actions[0].skipped_reason


def test_heal_restart_failure_marks_down(monkeypatch, tmp_path, fake_doctor):
    fake_doctor([_down("qdrant")])
    monkeypatch.setattr("jarvis.core.heal._restart_service", lambda s, sc: (False, "unit falhou"))
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    report = heal_once()
    assert report.overall == "down"
    assert report.actions[0].action == "restart"
    assert not report.actions[0].ok


def test_heal_ok_services_untouched(monkeypatch, tmp_path, fake_doctor):
    fake_doctor([_ok("llama_cpp"), _ok("qdrant")])
    monkeypatch.setattr("jarvis.core.heal._restart_service", lambda s, sc: (True, "x"))
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    report = heal_once()
    assert report.overall == "ok"
    assert report.actions == []


def test_heal_learns_lesson_on_restart(monkeypatch, tmp_path, fake_doctor):
    fake_doctor([_down("qdrant")])
    lessons = []

    class FakeMemory:
        def remember_lesson(self, **kw):
            lessons.append(kw)

    def fake_learn(service, component, detail):
        FakeMemory().remember_lesson(
            task=f"serviço {service} ficou down",
            error_pattern=f"doctor: {component} down — {detail}",
            fix="restart automático do serviço via systemctl",
        )

    monkeypatch.setattr("jarvis.core.heal._learn_lesson", fake_learn)
    monkeypatch.setattr("jarvis.core.heal._restart_service", lambda s, sc: (True, "restart OK"))
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))

    heal_once()
    assert len(lessons) == 1
    assert lessons[0]["task"] == "serviço qdrant ficou down"
    assert "qdrant" in lessons[0]["error_pattern"]


def test_heal_report_json_shape(monkeypatch, tmp_path, fake_doctor):
    fake_doctor([_down("qdrant")])
    monkeypatch.setattr("jarvis.core.heal._restart_service", lambda s, sc: (True, "ok"))
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))
    rep = heal_report()
    assert rep["overall"] == "healed"
    assert rep["actions"][0]["service"] == "qdrant"
    assert rep["actions"][0]["ok"] is True


def test_state_dir_env(monkeypatch, tmp_path):
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path / "s"))
    assert state_dir() == tmp_path / "s"
    assert state_dir().exists()


def test_heal_alerts_on_restart_and_failure(monkeypatch, tmp_path, fake_doctor):
    alerts = []

    def fake_alert(service, component, detail, *, healed):
        alerts.append((service, healed))

    monkeypatch.setattr("jarvis.core.heal._alert", fake_alert)
    monkeypatch.setattr("jarvis.core.heal._restart_service", lambda s, sc: (True, "restart OK"))
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))

    fake_doctor([_down("qdrant")])
    heal_once()
    assert alerts == [("qdrant", True)]  # healed

    alerts.clear()
    (tmp_path / "heal-restarts.json").unlink(missing_ok=True)  # zera o cooldown
    monkeypatch.setattr("jarvis.core.heal._restart_service", lambda s, sc: (False, "falhou"))
    heal_once(alerts=True)
    assert alerts == [("qdrant", False)]  # não healed


def test_heal_no_alerts_flag(monkeypatch, tmp_path, fake_doctor):
    alerts = []
    monkeypatch.setattr("jarvis.core.heal._alert", lambda *a, **k: alerts.append(a))
    monkeypatch.setattr("jarvis.core.heal._restart_service", lambda s, sc: (True, "ok"))
    monkeypatch.setenv("JARVIS_STATE_DIR", str(tmp_path))

    fake_doctor([_down("qdrant")])
    heal_once(alerts=False)
    assert alerts == []
