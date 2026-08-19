"""Testes do motor de Triggers (core/triggers.py)."""

from __future__ import annotations

import time
from pathlib import Path

import pytest

from jarvis.core.triggers import Trigger, TriggerEngine, TriggerState


# ---------------------------------------------------------------------------
# Básico
# ---------------------------------------------------------------------------


def test_register_and_status() -> None:
    engine = TriggerEngine()
    engine.register(Trigger(
        name="test_trigger",
        description=" teste",
        condition=lambda: True,
        action=lambda: None,
    ))
    status = engine.status()
    assert len(status) == 1
    assert status[0]["name"] == "test_trigger"
    assert status[0]["enabled"] is True


def test_run_condition_met() -> None:
    executed = {"n": 0}
    engine = TriggerEngine()
    engine.register(Trigger(
        name="always_true",
        description="test",
        condition=lambda: True,
        action=lambda: executed.update(n=executed["n"] + 1),
        idempotent=False,
    ))
    report = engine.run_all()
    assert report[0]["action"] == "executed"
    assert executed["n"] == 1


def test_run_condition_not_met() -> None:
    engine = TriggerEngine()
    engine.register(Trigger(
        name="always_false",
        description="test",
        condition=lambda: False,
        action=lambda: (_ for _ in ()).throw(AssertionError("should not run")),
        idempotent=False,  # para testar o path "condition not met"
    ))
    report = engine.run_all()
    assert report[0]["action"] == "skipped"
    assert "condition not met" in report[0]["reason"]


def test_cooldown() -> None:
    executed = {"n": 0}
    engine = TriggerEngine()
    engine.register(Trigger(
        name="cooled",
        description="test",
        condition=lambda: True,
        action=lambda: executed.update(n=executed["n"] + 1),
        cooldown_s=10.0,
        idempotent=False,
    ))
    engine.run_all()  # 1ª execução
    assert executed["n"] == 1
    report2 = engine.run_all()  # 2ª — cooldown
    assert report2[0]["action"] == "skipped"
    assert "cooldown" in report2[0]["reason"]
    assert executed["n"] == 1  # não executou de novo


def test_idempotent_skips_unchanged() -> None:
    executed = {"n": 0}
    engine = TriggerEngine()
    engine.register(Trigger(
        name="idempotent_test",
        description="test",
        condition=lambda: True,
        action=lambda: executed.update(n=executed["n"] + 1),
        cooldown_s=0,  # sem cooldown
        idempotent=True,
    ))
    engine.run_all()  # 1ª: condição True → executa
    assert executed["n"] == 1
    engine.run_all()  # 2ª: condição True (não mudou) → skip
    assert executed["n"] == 1


def test_idempotent_runs_on_change() -> None:
    counter = {"v": 0}
    executed = {"n": 0}

    def toggling_condition() -> bool:
        counter["v"] += 1
        return counter["v"] % 2 == 0

    engine = TriggerEngine()
    engine.register(Trigger(
        name="toggle_test",
        description="test",
        condition=toggling_condition,
        action=lambda: executed.update(n=executed["n"] + 1),
        cooldown_s=0,
        idempotent=True,
    ))
    engine.run_all()  # v=1, False → skip
    engine.run_all()  # v=2, True → executa
    engine.run_all()  # v=3, False → skip (mudou de True pra False)
    engine.run_all()  # v=4, True → executa
    assert executed["n"] == 2


def test_condition_error() -> None:
    def bad_condition() -> bool:
        raise RuntimeError("condition broken")

    engine = TriggerEngine()
    engine.register(Trigger(
        name="broken",
        description="test",
        condition=bad_condition,
        action=lambda: None,
    ))
    report = engine.run_all()
    assert report[0]["action"] == "error"
    assert "condition broken" in report[0]["error"]


def test_action_error() -> None:
    def bad_action() -> None:
        raise RuntimeError("action broken")

    engine = TriggerEngine()
    engine.register(Trigger(
        name="action_fail",
        description="test",
        condition=lambda: True,
        action=bad_action,
        idempotent=False,
    ))
    report = engine.run_all()
    assert report[0]["action"] == "error"
    assert "action broken" in report[0]["error"]


def test_disabled_trigger() -> None:
    executed = {"n": 0}
    engine = TriggerEngine()
    engine.register(Trigger(
        name="disabled",
        description="test",
        condition=lambda: True,
        action=lambda: executed.update(n=executed["n"] + 1),
        enabled=False,
    ))
    engine.run_all()
    assert executed["n"] == 0


def test_run_one() -> None:
    executed = {"n": 0}
    engine = TriggerEngine()
    engine.register(Trigger(
        name="target",
        description="test",
        condition=lambda: True,
        action=lambda: executed.update(n=executed["n"] + 1),
        idempotent=False,
    ))
    engine.register(Trigger(
        name="other",
        description="test",
        condition=lambda: True,
        action=lambda: None,
        idempotent=False,
    ))
    engine.run_one("target")
    assert executed["n"] == 1
    assert engine.run_one("nonexistent") is None


# ---------------------------------------------------------------------------
# Persistência
# ---------------------------------------------------------------------------


def test_persist_and_reload(tmp_path: Path) -> None:
    engine = TriggerEngine(state_dir=tmp_path)
    engine.register(Trigger(
        name="persist_test",
        description="test",
        condition=lambda: True,
        action=lambda: None,
        idempotent=False,
    ))
    engine.run_all()

    # Recarrega do disco
    engine2 = TriggerEngine(state_dir=tmp_path)
    engine2.register(Trigger(
        name="persist_test",
        description="test",
        condition=lambda: True,
        action=lambda: None,
        idempotent=False,
    ))
    state = engine2._states.get("persist_test")
    assert state is not None
    assert state.run_count == 1
    assert state.last_condition is True


def test_corrupted_state_file(tmp_path: Path) -> None:
    (tmp_path / "trigger-states.json").write_text("not json")
    engine = TriggerEngine(state_dir=tmp_path)
    # Não deve crashar
    assert engine._states == {}


# ---------------------------------------------------------------------------
# Triggers pré-definidos
# ---------------------------------------------------------------------------


def test_create_default_triggers() -> None:
    from jarvis.core.triggers import create_default_triggers

    engine = create_default_triggers()
    names = [t["name"] for t in engine.status()]
    assert "disk_alert" in names
    assert "doctor_alert" in names
    assert "cpu_alert" in names
